"""Dynamic bundle loader — the Lambda-style piece.

Fetches a code bundle referenced by SourceMeta, caches it on disk, imports the
declared entrypoint, and returns a callable factory. Loaded entrypoints are
cached per-process keyed by source.checksum (falling back to name+version).
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import shutil
import sys
import tempfile
import threading
import zipfile
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from runtime_common.schemas import SourceMeta


class BundleFetchError(RuntimeError):
    pass


class BundleImportError(BundleFetchError):
    """Raised when a bundle's module cannot be imported (e.g. SyntaxError, ImportError)."""


class BundleSignatureError(BundleFetchError):
    """Raised when a bundle's cosign/sigstore signature cannot be verified."""


def _load_public_key(pem: str) -> Any:
    """Load an EC or Ed25519 public key from a PEM string."""
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    try:
        return load_pem_public_key(pem.encode())
    except Exception as exc:
        raise ValueError(f"invalid bundle_signing_public_key PEM: {exc}") from exc


class BundleLoader:
    def __init__(
        self,
        cache_dir: str,
        max_entries: int,
        verify_signatures: bool = False,
        signing_public_key: str | None = None,
    ) -> None:
        self._cache_root = Path(cache_dir)
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        # keyed by checksum (or name:version fallback) -> factory callable
        self._entries: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()
        self._verify_signatures = verify_signatures
        self._public_key: Any = None
        if verify_signatures:
            if not signing_public_key:
                raise ValueError(
                    "bundle_verify_signatures=True requires bundle_signing_public_key to be set"
                )
            self._public_key = _load_public_key(signing_public_key)

    def _entry_key(self, meta: SourceMeta) -> str:
        if meta.checksum:
            return meta.checksum
        return f"{meta.name}:{meta.version}"

    def load(self, meta: SourceMeta) -> Any:
        key = self._entry_key(meta)
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]

            bundle_dir = self._fetch(meta)
            entrypoint = self._import(bundle_dir, meta)

            self._entries[key] = entrypoint
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return entrypoint

    def warm_checksums(self) -> set[str]:
        """Return the set of checksums currently held in the in-process cache."""
        with self._lock:
            return {k for k in self._entries if k.startswith("sha256:")}

    def _bundle_path(self, meta: SourceMeta) -> Path:
        if meta.checksum:
            digest = meta.checksum.replace("sha256:", "")[:16]
        else:
            digest = hashlib.sha256(
                f"{meta.name}:{meta.version}:{meta.bundle_uri}".encode()
            ).hexdigest()[:16]
        return self._cache_root / f"{meta.name}-{meta.version}-{digest}"

    def _fetch(self, meta: SourceMeta) -> Path:
        target = self._bundle_path(meta)
        if target.exists():
            return target

        parsed = urlparse(meta.bundle_uri)
        with tempfile.TemporaryDirectory(prefix="bundle-") as staging:
            staging_dir = Path(staging)
            archive = staging_dir / "bundle.zip"

            if parsed.scheme in ("http", "https"):
                # follow_redirects=True is required for S3-backed bundle storage:
                # backend's /bundles/{sha256}.zip returns 307 → NCP presigned URL.
                with httpx.stream(
                    "GET", meta.bundle_uri, timeout=60.0, follow_redirects=True
                ) as resp:
                    resp.raise_for_status()
                    with archive.open("wb") as fh:
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            fh.write(chunk)
            elif parsed.scheme == "file":
                shutil.copy(parsed.path, archive)
            elif parsed.scheme == "oci":
                self._fetch_oci(meta.bundle_uri, archive)
            else:
                raise BundleFetchError(f"unsupported bundle scheme: {parsed.scheme}")

            archive_bytes = archive.read_bytes()

            if meta.checksum:
                raw_checksum = meta.checksum.removeprefix("sha256:")
                digest = hashlib.sha256(archive_bytes).hexdigest()
                if digest != raw_checksum:
                    raise BundleFetchError(
                        f"checksum mismatch for {meta.name}@{meta.version}: "
                        f"expected {raw_checksum}, got {digest}"
                    )

            if self._verify_signatures:
                if not meta.sig_uri:
                    raise BundleSignatureError(
                        f"signature verification required but sig_uri missing for "
                        f"{meta.name}@{meta.version}"
                    )
                sig_b64 = self._fetch_sig(meta.sig_uri)
                self._verify_bundle_sig(archive_bytes, sig_b64)

            extracted = staging_dir / "extracted"
            extracted.mkdir()
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(extracted)

            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(extracted), str(target))
        return target

    def _fetch_sig(self, sig_uri: str) -> str:
        parsed = urlparse(sig_uri)
        if parsed.scheme in ("http", "https"):
            # follow_redirects: same reason as in _fetch (S3 presigned redirect).
            resp = httpx.get(sig_uri, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.text.strip()
        if parsed.scheme == "file":
            return Path(parsed.path).read_text().strip()
        raise BundleFetchError(f"unsupported sig_uri scheme: {parsed.scheme!r}")

    def _verify_bundle_sig(self, data: bytes, sig_b64: str) -> None:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, ed25519

        try:
            sig_bytes = base64.b64decode(sig_b64)
        except Exception as exc:
            raise BundleSignatureError(f"signature is not valid base64: {exc}") from exc

        try:
            key = self._public_key
            if isinstance(key, ec.EllipticCurvePublicKey):
                key.verify(sig_bytes, data, ec.ECDSA(hashes.SHA256()))
            elif isinstance(key, ed25519.Ed25519PublicKey):
                key.verify(sig_bytes, data)
            else:
                raise BundleSignatureError(f"unsupported key type: {type(key).__name__}")
        except InvalidSignature as exc:
            raise BundleSignatureError(
                "bundle signature verification failed — file may be tampered or key mismatch"
            ) from exc
        except BundleSignatureError:
            raise
        except Exception as exc:
            raise BundleSignatureError(f"signature verification error: {exc}") from exc

    def _fetch_oci(self, uri: str, dest: Path) -> None:
        """Fetch a bundle stored as a single-layer OCI artifact.

        URI format: oci://registry/repo:tag  or  oci://registry/repo@sha256:<digest>
        The registry must host the bundle zip as the first (and usually only) layer blob.
        Anonymous pull and Bearer-token auth are both supported via OCI Distribution Spec v2.
        """
        parsed = urlparse(uri)
        registry = parsed.netloc  # e.g. "registry.example.com" or "localhost:5000"
        # path is like "/repo:tag" or "/repo@sha256:abc"
        path = parsed.path.lstrip("/")

        if "@" in path:
            repo, reference = path.split("@", 1)
        elif ":" in path:
            repo, reference = path.rsplit(":", 1)
        else:
            repo, reference = path, "latest"

        base_url = f"https://{registry}"

        with httpx.Client(timeout=60.0) as client:
            # Resolve manifest to find the blob digest
            manifest_url = f"{base_url}/v2/{repo}/manifests/{reference}"
            headers = {
                "Accept": (
                    "application/vnd.oci.image.manifest.v1+json,"
                    "application/vnd.docker.distribution.manifest.v2+json"
                )
            }
            resp = client.get(manifest_url, headers=headers)

            # Handle WWW-Authenticate Bearer challenge
            if resp.status_code == 401:
                www_auth = resp.headers.get("www-authenticate", "")
                token = self._oci_bearer_token(client, www_auth, repo)
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                resp = client.get(manifest_url, headers=headers)

            if resp.status_code != 200:
                raise BundleFetchError(
                    f"OCI manifest fetch failed for {uri}: HTTP {resp.status_code}"
                )

            manifest = resp.json()
            layers = manifest.get("layers") or manifest.get("fsLayers", [])
            if not layers:
                raise BundleFetchError(f"OCI manifest has no layers: {uri}")

            # Take the first layer — bundle zip stored as application/octet-stream layer
            first_layer = layers[0]
            blob_digest = first_layer.get("digest") or first_layer.get("blobSum")
            if not blob_digest:
                raise BundleFetchError(f"OCI layer has no digest: {uri}")

            blob_url = f"{base_url}/v2/{repo}/blobs/{blob_digest}"
            with client.stream("GET", blob_url, headers=headers) as blob_resp:
                blob_resp.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in blob_resp.iter_bytes(chunk_size=65536):
                        fh.write(chunk)

    @staticmethod
    def _oci_bearer_token(client: httpx.Client, www_auth: str, repo: str) -> str | None:
        """Parse WWW-Authenticate Bearer challenge and fetch a token."""
        if not www_auth.lower().startswith("bearer "):
            return None
        params: dict[str, str] = {}
        for part in www_auth[7:].split(","):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                params[k.strip()] = v.strip().strip('"')
        realm = params.get("realm")
        if not realm:
            return None
        token_params: dict[str, str] = {}
        if "service" in params:
            token_params["service"] = params["service"]
        token_params["scope"] = params.get("scope", f"repository:{repo}:pull")
        resp = client.get(realm, params=token_params)
        if resp.status_code != 200:
            return None
        return resp.json().get("token") or resp.json().get("access_token")

    def _import(self, bundle_dir: Path, meta: SourceMeta) -> Callable[..., Any]:
        module_name, _, attr = meta.entrypoint.partition(":")
        if not attr:
            raise BundleFetchError(f"entrypoint must be 'module:attr', got {meta.entrypoint!r}")

        scoped_path = str(bundle_dir)
        if scoped_path not in sys.path:
            sys.path.insert(0, scoped_path)

        try:
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise BundleImportError(
                f"failed to import bundle {meta.name}@{meta.version}: {exc}"
            ) from exc

        factory = getattr(module, attr, None)
        if factory is None:
            raise BundleFetchError(f"entrypoint attribute {attr!r} not found in {module_name}")
        return factory
