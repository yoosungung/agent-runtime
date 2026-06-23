"""Checksum-scoped import namespace for dynamic bundle loading."""

from __future__ import annotations

import builtins
import importlib
import importlib.abc
import importlib.machinery
import sys
import threading
from collections.abc import Callable
from pathlib import Path

_REGISTRY_LOCK = threading.Lock()
_ACTIVE_FINDERS: dict[str, _BundleMetaPathFinder] = {}


def namespace_for_key(entry_key: str) -> str:
    """Return the top-level sys.modules prefix for a cache entry key."""
    safe_key = entry_key.replace(":", "_").replace("/", "_")[:80]
    return f"_rt_bundle_{safe_key}"


def resolve_module_file(bundle_dir: Path, module_name: str) -> Path | None:
    """Map a bundle-relative module name to a file path, or None if missing."""
    parts = module_name.split(".")
    as_file = bundle_dir.joinpath(*parts).with_suffix(".py")
    if as_file.is_file():
        return as_file
    as_pkg_init = bundle_dir.joinpath(*parts, "__init__.py")
    if as_pkg_init.is_file():
        return as_pkg_init
    as_dir = bundle_dir.joinpath(*parts)
    if as_dir.is_dir():
        return as_dir
    return None


def module_exists_in_bundle(bundle_dir: Path, module_name: str) -> bool:
    return resolve_module_file(bundle_dir, module_name) is not None


def register_namespace(namespace: str, bundle_dir: Path) -> None:
    """Install a MetaPathFinder for *namespace* backed by *bundle_dir*."""
    with _REGISTRY_LOCK:
        if namespace in _ACTIVE_FINDERS:
            return
        finder = _BundleMetaPathFinder(namespace, bundle_dir.resolve())
        _ACTIVE_FINDERS[namespace] = finder
        sys.meta_path.insert(0, finder)


def unregister_namespace(namespace: str) -> None:
    """Remove finder and purge all modules under *namespace*."""
    with _REGISTRY_LOCK:
        finder = _ACTIVE_FINDERS.pop(namespace, None)
        if finder is not None:
            while finder in sys.meta_path:
                sys.meta_path.remove(finder)
    purge_namespace_modules(namespace)


def purge_namespace_modules(namespace: str) -> None:
    prefix = namespace + "."
    for name in list(sys.modules):
        if name == namespace or name.startswith(prefix):
            del sys.modules[name]


def import_entrypoint(
    bundle_dir: Path,
    entry_key: str,
    module_name: str,
) -> object:
    """Import a bundle entry module inside its checksum-scoped namespace."""
    namespace = namespace_for_key(entry_key)
    register_namespace(namespace, bundle_dir)
    full_name = f"{namespace}.{module_name}"
    return importlib.import_module(full_name)


class _BundleImportHook:
    """Redirect absolute imports to the active bundle namespace during exec."""

    def __init__(self, namespace: str, bundle_dir: Path) -> None:
        self._namespace = namespace
        self._bundle_dir = bundle_dir
        self._original: Callable[..., object] | None = None

    def __enter__(self) -> _BundleImportHook:
        namespace = self._namespace
        bundle_dir = self._bundle_dir
        original = builtins.__import__

        def hooked(
            name: str,
            globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if level == 0 and module_exists_in_bundle(bundle_dir, name):
                return original(
                    f"{namespace}.{name}",
                    globals,
                    locals,
                    fromlist,
                    level,
                )
            return original(name, globals, locals, fromlist, level)

        self._original = original
        builtins.__import__ = hooked
        return self

    def __exit__(self, *args: object) -> None:
        if self._original is not None:
            builtins.__import__ = self._original


class _BundleModuleLoader(importlib.abc.Loader):
    def __init__(
        self,
        fullname: str,
        module_path: Path,
        namespace: str,
        bundle_dir: Path,
        *,
        is_package: bool,
    ) -> None:
        self.fullname = fullname
        self.module_path = module_path
        self.namespace = namespace
        self.bundle_dir = bundle_dir
        self.is_package = is_package

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> object | None:
        return None

    def exec_module(self, module: object) -> None:
        if self.is_package:
            module.__path__ = [str(self.module_path)]  # type: ignore[attr-defined]
            return
        source = self.module_path.read_text(encoding="utf-8")
        code = compile(source, str(self.module_path), "exec", dont_inherit=True)
        with _BundleImportHook(self.namespace, self.bundle_dir):
            exec(code, module.__dict__)  # noqa: S102


class _BundleMetaPathFinder(importlib.abc.MetaPathFinder):
    def __init__(self, namespace: str, bundle_dir: Path) -> None:
        self.namespace = namespace
        self.bundle_dir = bundle_dir

    def find_spec(
        self,
        fullname: str,
        path: object | None = None,
        target: object | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname != self.namespace and not fullname.startswith(f"{self.namespace}."):
            return None

        if fullname == self.namespace:
            return importlib.machinery.ModuleSpec(
                fullname,
                None,
                is_package=True,
                origin=str(self.bundle_dir),
            )

        rel = fullname[len(self.namespace) + 1 :]
        resolved = resolve_module_file(self.bundle_dir, rel)
        if resolved is None:
            return None

        if resolved.is_dir():
            return importlib.machinery.ModuleSpec(
                fullname,
                _BundleModuleLoader(
                    fullname,
                    resolved,
                    self.namespace,
                    self.bundle_dir,
                    is_package=True,
                ),
                is_package=True,
                origin=str(resolved),
            )

        is_pkg = resolved.name == "__init__.py"
        return importlib.machinery.ModuleSpec(
            fullname,
            _BundleModuleLoader(
                fullname,
                resolved,
                self.namespace,
                self.bundle_dir,
                is_package=is_pkg,
            ),
            origin=str(resolved),
            is_package=is_pkg,
        )
