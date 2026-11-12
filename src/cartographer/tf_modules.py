"""The Terraform module tree: parsed `.tf` files, local module instances and the resources they hold."""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hcl2

from cartographer.tf_policies import OPTS, unq
from cartographer.tf_values import UNRESOLVED, attrs

HEADER = re.compile(r'^(resource|data)\s+"([^"]+)"\s+"([^"]+)"|^(module|output)\s+"([^"]+)"', re.MULTILINE)
META = {"source", "version", "providers", "for_each", "count", "depends_on"}
SINGLE = re.compile(r"\$\{(var|local)\.(\w+)\}")
MAX_DEPTH = 8


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
    providers: dict[str, dict] = field(default_factory=dict)  # `name` or `name.alias` -> provider block body


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
        for item in doc.get("provider", []):
            for name, body in item.items():
                alias = body.get("alias")
                mod.providers[f"{unq(name)}.{unq(alias)}" if alias else unq(name)] = body
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
    provider_map: dict[str, str] = field(default_factory=dict)  # a provider key of this module -> the parent's key; "" when calls disagree
    children: dict[str, Inst] = field(default_factory=dict)
    _values: dict[tuple, str | None | object] = field(default_factory=dict, repr=False)  # `value` per (expr, depth, agree)

    def walk(self) -> Iterator[Inst]:
        yield self
        done: set[int] = set()
        for name in sorted(self.children):
            if id(child := self.children[name]) not in done:
                done.add(id(child))
                yield from child.walk()

    def value(self, expr: Any, depth: int = 0, agree: bool = False) -> str | None | object:
        """The literal `expr` is here, through `local.`, module arguments and variable defaults; None when absent,
        UNRESOLVED when it is no literal. A variable reads the first call that passes it. With `agree`, every call this
        instance stands for must give the same value (one that passes none reads the default), else UNRESOLVED: what
        identifies a remote state must hold for every call."""
        head = _head(expr, depth)
        if not isinstance(head, tuple):
            return head
        if (key := (head, depth, agree)) not in self._values:  # every call path of a deep module tree asks again
            self._values[key] = self._read(*head, depth, agree)
        return self._values[key]

    def _read(self, kind: str, name: str, depth: int, agree: bool) -> str | None | object:
        calls = self.args if kind == "var" and self.parent is not None else []
        passed = [a[name] for a in calls if name in a]
        options = [(self.parent, v) for v in (passed if agree else passed[:1])]
        if not passed or (agree and len(passed) < len(calls)):
            options.append((self, (self.mod.locals if kind == "local" else self.mod.variables).get(name)))
        found = {where.value(target, depth + 1, agree) for where, target in options}  # type: ignore[union-attr]
        return found.pop() if len(found) == 1 and None not in found else UNRESOLVED


def bare(text: Any) -> str:
    """An expression without its quotes and its one `${...}`: `"${aws_vpc.main.id}"` -> `aws_vpc.main.id`."""
    return unq(text if isinstance(text, str) else str(text)).removeprefix("${").removesuffix("}")


def _head(expr: Any, depth: int) -> str | None | object | tuple[str, str]:
    """A literal `expr` (None when absent, UNRESOLVED when no literal), or the (`var` | `local`, name) it reads."""
    if expr is None:
        return None
    if isinstance(expr, (bool, int, float)):
        return str(expr).lower()
    if not isinstance(expr, str):
        return UNRESOLVED
    s = unq(expr)
    if not (m := SINGLE.fullmatch(s)):
        return UNRESOLVED if "${" in s else s
    return UNRESOLVED if depth >= MAX_DEPTH else (m[1], m[2])


def declared_provider(inst: Inst | None, key: str) -> tuple[Inst | None, str]:
    """Follow the provider `key` (`name` or `name.alias`) that `inst` uses up through the `providers` maps of the module
    calls: the instance that declares it and its key there. The instance is None when no module declares it (the key
    is then the root's), the key "" when the calls of one instance map it to different providers."""
    while inst is not None and key and key not in inst.mod.providers:
        key = inst.provider_map.get(key, key)
        inst = inst.parent
    return inst, key


def provider_map(calls: list[Block]) -> dict[str, str]:
    maps = [{unq(k): bare(v) for k, v in b.body.get("providers", {}).items() if k != "__is_block__"}
            for b in calls]
    return {key: found.pop() if len(found := {m.get(key) for m in maps}) == 1 else "" for key in {k for m in maps for k in m}}


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
        child.provider_map = provider_map(calls)
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
