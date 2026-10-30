"""Where the code that Terraform deploys lives: local source paths in the HCL plus the repo's lambda manifest."""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from cartographer.tf_policies import unq

MANIFEST = "lambda-manifests.json"
PATH_ATTRS = {
    "source_dir", "source_file", "context", "build_context", "docker_context", "code_path", "source_path", "src_path",
}
PATH_VARS = {"${path.module}": "module", "${path.root}": "root", "${path.cwd}": "root"}
INTERPOLATION = re.compile(r"\$\{")


def _path_values(obj: Any) -> Iterator[str]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if unq(key) in PATH_ATTRS and isinstance(value, str):
                yield unq(value)
            else:
                yield from _path_values(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _path_values(value)


def _resolve(value: str, module_dir: Path, root_dir: Path, repo_root: Path) -> Path | None:
    for token, base in PATH_VARS.items():
        value = value.replace(token, str(module_dir if base == "module" else root_dir))
    if INTERPOLATION.search(value):
        return None
    candidates = [Path(value)] if Path(value).is_absolute() else [root_dir / value, module_dir / value]
    for path in candidates:
        path = path.resolve()
        if path.is_dir() and path.is_relative_to(repo_root):
            return path
    return None


def _manifest(repo_root: Path) -> tuple[Path, list[str]] | None:
    path = repo_root / MANIFEST
    if not path.is_file():
        return None
    cfg = json.loads(path.read_text())
    return repo_root / cfg["basedir"], cfg.get("shared_paths", [])


def code_roots(insts: list, repo_root: Path) -> list[tuple[Path, str | None]]:
    """(directory, owner address) per code root, outermost first. Roots nested in an earlier root are dropped."""
    root_dir = insts[0].mod.directory
    found: list[tuple[Path, str | None]] = []
    for inst in insts:
        mod = inst.mod
        blocks = [(f"{inst.prefix}{t}.{n}", b) for (t, n), b in mod.resources.items()]
        blocks += [(f"{inst.prefix}module.{n}", b) for n, b in mod.calls.items()]
        for address, blk in blocks:
            for value in _path_values(blk.body):
                if path := _resolve(value, mod.directory, root_dir, repo_root):
                    found.append((path, address))
        for (rtype, name), blk in mod.data.items():
            if rtype != "archive_file":
                continue
            owner = next((a for a, b in blocks if re.search(rf"data\.archive_file\.{name}\b", json.dumps(b.body))), None)
            for value in _path_values(blk.body):
                if path := _resolve(value, mod.directory, root_dir, repo_root):
                    found.append((path, owner))
    manifest = _manifest(repo_root)
    if manifest:
        basedir, shared = manifest
        for inst in insts:
            for name, blk in inst.mod.calls.items():
                partner = unq(blk.body.get("name", ""))
                tree = basedir / "functions" / partner.replace("-", "_")
                if partner and "${" not in partner and tree.is_dir():
                    owner = inst.children[name].prefix.rstrip(".") if name in inst.children else f"{inst.prefix}module.{name}"
                    found.append((tree, owner))
        found += [(basedir / s, None) for s in shared if (basedir / s).is_dir()]
    roots: list[tuple[Path, str | None]] = []
    for path, owner in sorted(set(found), key=lambda f: (len(f[0].parts), str(f[0]), f[1] is None, f[1] or "")):
        if not any(path.is_relative_to(kept) for kept, _ in roots):
            roots.append((path, owner))
    return roots
