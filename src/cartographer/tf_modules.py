"""The Terraform module tree: parsed `.tf` files, local module instances and the resources they hold."""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hcl2

from cartographer.tf_policies import OPTS, unq
from cartographer.tf_values import attrs

HEADER = re.compile(r'^(resource|data)\s+"([^"]+)"\s+"([^"]+)"|^(module|output)\s+"([^"]+)"', re.MULTILINE)
META = {"source", "version", "providers", "for_each", "count", "depends_on"}


@dataclass
class Block:
    body: dict
    file: str
    line: int


@dataclass
class Module:
    directory: Path
    resources: dict[tuple[str, str], Block] = field(default_factory=dict)
    data: dict[tuple[str, str], Block] = field(default_factory=dict)
    locals: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    calls: dict[str, Block] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)


def parse_module(directory: Path, repo_root: Path) -> Module:
    mod = Module(directory)
    for path in sorted(directory.glob("*.tf")):
        raw = path.read_text()
        rel = path.relative_to(repo_root).as_posix()
        lines = {}
        for m in HEADER.finditer(raw):
            key = m.group(1, 2, 3) if m.group(1) else m.group(4, 5)
            lines[key] = raw.count("\n", 0, m.start()) + 1
        doc = hcl2.loads(raw, serialization_options=OPTS)
        for kind, target in (("resource", mod.resources), ("data", mod.data)):
            for item in doc.get(kind, []):
                for rtype, names in item.items():
                    for name, body in names.items():
                        t, n = unq(rtype), unq(name)
                        target[(t, n)] = Block(body, rel, lines.get((kind, t, n), 0))
        for item in doc.get("module", []):
            for name, body in item.items():
                mod.calls[unq(name)] = Block(body, rel, lines.get(("module", unq(name)), 0))
        for item in doc.get("output", []):
            for name, body in item.items():
                mod.outputs[unq(name)] = body.get("value")
        for item in doc.get("variable", []):
            for name, body in item.items():
                mod.variables[unq(name)] = body.get("default")
        for item in doc.get("locals", []):
            mod.locals.update(attrs(item))
    return mod


@dataclass(eq=False)
class Inst:
    mod: Module
    prefix: str
    args: list[dict[str, Any]]
    parent: Inst | None
    multi: bool
    instances: list[str] | None = None
    children: dict[str, Inst] = field(default_factory=dict)

    def walk(self) -> Iterator[Inst]:
        yield self
        done: set[int] = set()
        for name in sorted(self.children):
            if id(child := self.children[name]) not in done:
                done.add(id(child))
                yield from child.walk()


def local_source(blk: Block) -> str | None:
    source = unq(blk.body.get("source", ""))
    return source if source.startswith(("./", "../")) else None


def build(directory: Path, repo_root: Path, prefix: str, args: list, parent: Inst | None, multi: bool,
          depth: int = 0, instances: list[str] | None = None) -> Inst:
    """Instantiate a module. Calls of one local source in the same parent collapse into one `module.<family>` instance."""
    inst = Inst(parse_module(directory, repo_root), prefix, args, parent, multi, instances)
    by_dir: dict[Path, list[str]] = {}
    for name, blk in inst.mod.calls.items():
        if depth < 8 and (source := local_source(blk)):
            by_dir.setdefault((directory / source).resolve(), []).append(name)
    for target, names in by_dir.items():
        calls = [inst.mod.calls[n] for n in names]
        family = len(names) > 1
        label = names[0]
        if family:
            label = f"{target.name}-family" if target.name in inst.mod.calls and target.name not in names else target.name
        child = build(
            target, repo_root, f"{prefix}module.{label}.",
            [{k: v for k, v in attrs(c.body).items() if k not in META} for c in calls], inst,
            multi or family or any("count" in c.body or "for_each" in c.body for c in calls), depth + 1,
            sorted(names) if family else None,
        )
        inst.children.update(dict.fromkeys(names, child))
    return inst


@dataclass
class Res:
    address: str
    type: str
    inst: Inst
    block: Block
    multi: bool
    extra: dict[str, Any] = field(default_factory=dict)


def remote_info(blk: Block) -> dict[str, str]:
    """Remote module source without ?ref= query or credentials, plus its version when pinned."""
    source = re.sub(r"(://)[^/@]*@", r"\1", unq(blk.body.get("source", ""))).split("?")[0]
    return {"source": source, **({"version": unq(blk.body["version"])} if "version" in blk.body else {})}
