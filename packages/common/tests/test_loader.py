"""Unit tests for runtime_common.loader."""

import base64
import hashlib
import io
import zipfile

import pytest
import respx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from httpx import Response

from runtime_common.loader import BundleFetchError, BundleLoader, BundleSignatureError
from runtime_common.schemas import SourceMeta


def _make_ec_keypair():
    """Return (private_key, public_key_pem) for a P-256 key pair."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_key, public_key_pem


def _make_ed25519_keypair():
    """Return (private_key, public_key_pem) for an Ed25519 key pair."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_key, public_key_pem


def _ec_sign(private_key, data: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric import ec as _ec

    sig = private_key.sign(data, _ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode()


def _ed25519_sign(private_key, data: bytes) -> str:
    sig = private_key.sign(data)
    return base64.b64encode(sig).decode()


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _meta(
    name="myagent",
    version="v1",
    entrypoint="mymod:factory",
    checksum=None,
    bundle_uri="file:///dummy",
):
    return SourceMeta(
        kind="agent",
        name=name,
        version=version,
        runtime_pool="agent:custom",
        entrypoint=entrypoint,
        bundle_uri=bundle_uri,
        checksum=checksum,
    )


def test_load_from_file(tmp_path):
    module_src = "def factory(): return 'hello'\n"
    bundle_bytes = _make_zip({"mymod.py": module_src})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)

    checksum = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()
    meta = _meta(bundle_uri=f"file://{zip_path}", checksum=checksum)

    cache_dir = str(tmp_path / "cache")
    loader = BundleLoader(cache_dir=cache_dir, max_entries=8)
    factory = loader.load(meta)
    assert factory() == "hello"


def test_cache_hit_returns_same(tmp_path):
    module_src = "calls = []\ndef factory():\n    calls.append(1)\n    return len(calls)\n"
    bundle_bytes = _make_zip({"mymod.py": module_src})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)

    checksum = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()
    meta = _meta(bundle_uri=f"file://{zip_path}", checksum=checksum)

    cache_dir = str(tmp_path / "cache")
    loader = BundleLoader(cache_dir=cache_dir, max_entries=8)
    f1 = loader.load(meta)
    f2 = loader.load(meta)
    assert f1 is f2


def test_checksum_mismatch_raises(tmp_path):
    bundle_bytes = _make_zip({"mymod.py": "def factory(): pass\n"})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)

    # Wrong checksum
    meta = _meta(bundle_uri=f"file://{zip_path}", checksum="sha256:badhash")

    loader = BundleLoader(cache_dir=str(tmp_path / "cache"), max_entries=8)
    with pytest.raises(BundleFetchError, match="checksum mismatch"):
        loader.load(meta)


def test_unsupported_scheme_raises(tmp_path):
    meta = _meta(bundle_uri="ftp://example.com/bundle.zip")
    loader = BundleLoader(cache_dir=str(tmp_path / "cache"), max_entries=8)
    with pytest.raises(BundleFetchError, match="unsupported bundle scheme"):
        loader.load(meta)


def test_missing_attr_raises(tmp_path):
    bundle_bytes = _make_zip({"mymod.py": "x = 1\n"})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)

    checksum = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()
    meta = _meta(
        bundle_uri=f"file://{zip_path}",
        checksum=checksum,
        entrypoint="mymod:nonexistent_attr",
        name="missing-attr",
    )
    loader = BundleLoader(cache_dir=str(tmp_path / "cache"), max_entries=8)
    with pytest.raises(BundleFetchError, match="not found"):
        loader.load(meta)


def test_warm_checksums(tmp_path):
    module_src = "def factory(): return 'w'\n"
    bundle_bytes = _make_zip({"mymod.py": module_src})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)

    checksum = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()
    meta = _meta(bundle_uri=f"file://{zip_path}", checksum=checksum, name="warmtest")

    loader = BundleLoader(cache_dir=str(tmp_path / "cache"), max_entries=8)
    assert loader.warm_checksums() == set()

    loader.load(meta)
    assert checksum in loader.warm_checksums()


def test_lru_eviction(tmp_path):
    # max_entries=2: loading a 3rd entry evicts the first
    cache_dir = str(tmp_path / "cache")
    loader = BundleLoader(cache_dir=cache_dir, max_entries=2)

    checksums = []
    for i in range(3):
        module_src = f"def factory(): return {i}\n"
        bundle_bytes = _make_zip({f"mod{i}.py": module_src})
        zip_path = tmp_path / f"bundle{i}.zip"
        zip_path.write_bytes(bundle_bytes)
        cs = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()
        checksums.append(cs)
        meta = SourceMeta(
            kind="agent",
            name=f"agent{i}",
            version="v1",
            runtime_pool="agent:custom",
            entrypoint=f"mod{i}:factory",
            bundle_uri=f"file://{zip_path}",
            checksum=cs,
        )
        loader.load(meta)

    warm = loader.warm_checksums()
    assert checksums[0] not in warm  # evicted
    assert checksums[1] in warm
    assert checksums[2] in warm


def test_entrypoint_missing_colon_raises(tmp_path):
    loader = BundleLoader(cache_dir=str(tmp_path / "cache"), max_entries=8)
    bundle_bytes = _make_zip({"x.py": "pass\n"})
    zip_path = tmp_path / "b.zip"
    zip_path.write_bytes(bundle_bytes)
    bad_meta = _meta(bundle_uri=f"file://{zip_path}", entrypoint="no_colon_here", name="nocolon")
    with pytest.raises(BundleFetchError, match="entrypoint must be"):
        loader.load(bad_meta)


def test_cache_eviction_max_entries_one(tmp_path):
    """max_entries=1: loading a second bundle evicts the first."""
    cache_dir = str(tmp_path / "cache")
    loader = BundleLoader(cache_dir=cache_dir, max_entries=1)

    # Bundle A
    bytes_a = _make_zip({"mod_a.py": "def factory(): return 'A'\n"})
    path_a = tmp_path / "bundle_a.zip"
    path_a.write_bytes(bytes_a)
    cs_a = "sha256:" + hashlib.sha256(bytes_a).hexdigest()
    meta_a = SourceMeta(
        kind="agent",
        name="agent-a",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="mod_a:factory",
        bundle_uri=f"file://{path_a}",
        checksum=cs_a,
    )

    # Bundle B
    bytes_b = _make_zip({"mod_b.py": "def factory(): return 'B'\n"})
    path_b = tmp_path / "bundle_b.zip"
    path_b.write_bytes(bytes_b)
    cs_b = "sha256:" + hashlib.sha256(bytes_b).hexdigest()
    meta_b = SourceMeta(
        kind="agent",
        name="agent-b",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="mod_b:factory",
        bundle_uri=f"file://{path_b}",
        checksum=cs_b,
    )

    loader.load(meta_a)
    assert cs_a in loader.warm_checksums()

    loader.load(meta_b)
    warm = loader.warm_checksums()
    assert cs_a not in warm, "bundle A should have been evicted"
    assert cs_b in warm


def test_warm_checksums_only_sha256_prefixed(tmp_path):
    """warm_checksums() must only return keys that start with 'sha256:'."""
    cache_dir = str(tmp_path / "cache")
    loader = BundleLoader(cache_dir=cache_dir, max_entries=8)

    # Load a bundle WITHOUT a checksum → key is name:version, no sha256: prefix
    bytes_no_cs = _make_zip({"nocs.py": "def factory(): return 'nocs'\n"})
    path_no_cs = tmp_path / "no_cs.zip"
    path_no_cs.write_bytes(bytes_no_cs)
    meta_no_cs = SourceMeta(
        kind="agent",
        name="no-checksum-agent",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="nocs:factory",
        bundle_uri=f"file://{path_no_cs}",
        checksum=None,
    )
    loader.load(meta_no_cs)
    # The fallback key "no-checksum-agent:v1" should NOT appear in warm_checksums
    assert loader.warm_checksums() == set()

    # Now load a bundle WITH a sha256 checksum
    bytes_with_cs = _make_zip({"withcs.py": "def factory(): return 'yes'\n"})
    path_with_cs = tmp_path / "with_cs.zip"
    path_with_cs.write_bytes(bytes_with_cs)
    cs = "sha256:" + hashlib.sha256(bytes_with_cs).hexdigest()
    meta_with_cs = SourceMeta(
        kind="agent",
        name="cs-agent",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="withcs:factory",
        bundle_uri=f"file://{path_with_cs}",
        checksum=cs,
    )
    loader.load(meta_with_cs)
    assert cs in loader.warm_checksums()


# ---------------------------------------------------------------------------
# Signature verification tests
# ---------------------------------------------------------------------------


def test_signature_valid_ec(tmp_path):
    private_key, pub_pem = _make_ec_keypair()
    bundle_bytes = _make_zip({"sig_mod.py": "def factory(): return 'signed'\n"})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)
    checksum = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()

    sig_b64 = _ec_sign(private_key, bundle_bytes)
    sig_path = tmp_path / "bundle.zip.sig"
    sig_path.write_text(sig_b64)

    meta = SourceMeta(
        kind="agent",
        name="sig-agent",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="sig_mod:factory",
        bundle_uri=f"file://{zip_path}",
        checksum=checksum,
        sig_uri=f"file://{sig_path}",
    )
    loader = BundleLoader(
        cache_dir=str(tmp_path / "cache"),
        max_entries=8,
        verify_signatures=True,
        signing_public_key=pub_pem,
    )
    assert loader.load(meta)() == "signed"


def test_signature_valid_ed25519(tmp_path):
    private_key, pub_pem = _make_ed25519_keypair()
    bundle_bytes = _make_zip({"ed_mod.py": "def factory(): return 'ed'\n"})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)
    checksum = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()

    sig_b64 = _ed25519_sign(private_key, bundle_bytes)
    sig_path = tmp_path / "bundle.zip.sig"
    sig_path.write_text(sig_b64)

    meta = SourceMeta(
        kind="agent",
        name="ed-agent",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="ed_mod:factory",
        bundle_uri=f"file://{zip_path}",
        checksum=checksum,
        sig_uri=f"file://{sig_path}",
    )
    loader = BundleLoader(
        cache_dir=str(tmp_path / "cache"),
        max_entries=8,
        verify_signatures=True,
        signing_public_key=pub_pem,
    )
    assert loader.load(meta)() == "ed"


def test_signature_tampered_file_raises(tmp_path):
    private_key, pub_pem = _make_ec_keypair()
    original_bytes = _make_zip({"t_mod.py": "def factory(): return 'ok'\n"})
    tampered_bytes = _make_zip({"t_mod.py": "def factory(): return 'evil'\n"})

    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(tampered_bytes)

    sig_b64 = _ec_sign(private_key, original_bytes)
    sig_path = tmp_path / "bundle.zip.sig"
    sig_path.write_text(sig_b64)

    meta = SourceMeta(
        kind="agent",
        name="tampered-agent",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="t_mod:factory",
        bundle_uri=f"file://{zip_path}",
        sig_uri=f"file://{sig_path}",
    )
    loader = BundleLoader(
        cache_dir=str(tmp_path / "cache"),
        max_entries=8,
        verify_signatures=True,
        signing_public_key=pub_pem,
    )
    with pytest.raises(BundleSignatureError, match="verification failed"):
        loader.load(meta)


def test_signature_wrong_key_raises(tmp_path):
    signing_key, _ = _make_ec_keypair()
    _, verifying_pub_pem = _make_ec_keypair()  # different key

    bundle_bytes = _make_zip({"wk_mod.py": "def factory(): return 'ok'\n"})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)

    sig_b64 = _ec_sign(signing_key, bundle_bytes)
    sig_path = tmp_path / "bundle.zip.sig"
    sig_path.write_text(sig_b64)

    meta = SourceMeta(
        kind="agent",
        name="wrongkey-agent",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="wk_mod:factory",
        bundle_uri=f"file://{zip_path}",
        sig_uri=f"file://{sig_path}",
    )
    loader = BundleLoader(
        cache_dir=str(tmp_path / "cache"),
        max_entries=8,
        verify_signatures=True,
        signing_public_key=verifying_pub_pem,
    )
    with pytest.raises(BundleSignatureError, match="verification failed"):
        loader.load(meta)


def test_signature_missing_sig_uri_raises(tmp_path):
    _, pub_pem = _make_ec_keypair()
    bundle_bytes = _make_zip({"ns_mod.py": "def factory(): return 'ok'\n"})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)
    checksum = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()

    meta = SourceMeta(
        kind="agent",
        name="nosig-agent",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="ns_mod:factory",
        bundle_uri=f"file://{zip_path}",
        checksum=checksum,
        sig_uri=None,
    )
    loader = BundleLoader(
        cache_dir=str(tmp_path / "cache"),
        max_entries=8,
        verify_signatures=True,
        signing_public_key=pub_pem,
    )
    with pytest.raises(BundleSignatureError, match="sig_uri missing"):
        loader.load(meta)


def test_signature_skipped_when_disabled(tmp_path):
    bundle_bytes = _make_zip({"sk_mod.py": "def factory(): return 'skip'\n"})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)
    checksum = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()

    meta = _meta(bundle_uri=f"file://{zip_path}", checksum=checksum, name="skip-sig")
    loader = BundleLoader(cache_dir=str(tmp_path / "cache"), max_entries=8)
    assert loader.load(meta)() is not None


def test_signature_bad_base64_raises(tmp_path):
    _, pub_pem = _make_ec_keypair()
    bundle_bytes = _make_zip({"bb_mod.py": "def factory(): return 'ok'\n"})
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)

    sig_path = tmp_path / "bundle.zip.sig"
    sig_path.write_text("not-valid-base64!!!")

    meta = SourceMeta(
        kind="agent",
        name="badbase64-agent",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="bb_mod:factory",
        bundle_uri=f"file://{zip_path}",
        sig_uri=f"file://{sig_path}",
    )
    loader = BundleLoader(
        cache_dir=str(tmp_path / "cache"),
        max_entries=8,
        verify_signatures=True,
        signing_public_key=pub_pem,
    )
    with pytest.raises(BundleSignatureError, match="not valid base64"):
        loader.load(meta)


def test_loader_init_fails_without_key_when_verify_enabled():
    with pytest.raises(ValueError, match="bundle_signing_public_key"):
        BundleLoader(cache_dir="/tmp", max_entries=8, verify_signatures=True)


def test_loader_init_fails_with_bad_pem():
    with pytest.raises(ValueError, match="invalid bundle_signing_public_key"):
        BundleLoader(
            cache_dir="/tmp",
            max_entries=8,
            verify_signatures=True,
            signing_public_key="not-a-pem",
        )


@respx.mock
def test_load_from_oci(tmp_path):
    """OCI scheme: manifest → blob fetch sequence."""
    bundle_bytes = _make_zip({"oci_mod.py": "def factory(): return 'oci'\n"})
    blob_digest = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()

    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "layers": [
            {
                "mediaType": "application/octet-stream",
                "digest": blob_digest,
                "size": len(bundle_bytes),
            }
        ],
    }

    respx.get("https://reg.example.com/v2/myrepo/manifests/v1").mock(
        return_value=Response(200, json=manifest)
    )
    respx.get(f"https://reg.example.com/v2/myrepo/blobs/{blob_digest}").mock(
        return_value=Response(200, content=bundle_bytes)
    )

    meta = SourceMeta(
        kind="agent",
        name="oci-agent",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="oci_mod:factory",
        bundle_uri="oci://reg.example.com/myrepo:v1",
        checksum=blob_digest,
    )
    loader = BundleLoader(cache_dir=str(tmp_path / "cache"), max_entries=8)
    factory = loader.load(meta)
    assert factory() == "oci"


@respx.mock
def test_load_from_oci_with_bearer_auth(tmp_path):
    """OCI scheme: 401 challenge → token fetch → retry manifest."""
    bundle_bytes = _make_zip({"auth_mod.py": "def factory(): return 'auth'\n"})
    blob_digest = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()

    manifest = {
        "schemaVersion": 2,
        "layers": [{"digest": blob_digest, "size": len(bundle_bytes)}],
    }

    # First manifest request returns 401 with Bearer challenge
    respx.get("https://reg.example.com/v2/private/manifests/v2").mock(
        side_effect=[
            Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer realm="https://auth.example.com/token",'
                        'service="reg.example.com",'
                        'scope="repository:private:pull"'
                    )
                },
            ),
            Response(200, json=manifest),
        ]
    )
    respx.get("https://auth.example.com/token").mock(
        return_value=Response(200, json={"token": "test-jwt-token"})
    )
    respx.get(f"https://reg.example.com/v2/private/blobs/{blob_digest}").mock(
        return_value=Response(200, content=bundle_bytes)
    )

    meta = SourceMeta(
        kind="agent",
        name="auth-agent",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="auth_mod:factory",
        bundle_uri="oci://reg.example.com/private:v2",
        checksum=blob_digest,
    )
    loader = BundleLoader(cache_dir=str(tmp_path / "cache"), max_entries=8)
    factory = loader.load(meta)
    assert factory() == "auth"
