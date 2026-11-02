"""Stage 1 of tfdiagram: Terraform folder -> facts.json. No HCL evaluation, only parsing and reference scanning."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from cartographer import icons
from cartographer.clouds import CLOUDS, IGNORED_PROVIDERS, cloud_of_type, resolve_module
from cartographer.clouds.base import UNRESOLVED, Cloud, Getter, Resolution
from cartographer.tf_hints import collect_hints
from cartographer.tf_modules import META, Block, Inst, Res, build, remote_info
from cartographer.tf_policies import unq
from cartographer.tf_values import attrs, text

REF = re.compile(r"(?<![\w.\-])([A-Za-z_]\w*)\.([A-Za-z_][\w-]*)(?:\[[^\]]*\])?(?:\.([A-Za-z_][\w-]*))?")
SINGLE = re.compile(r"\$\{(var|local)\.(\w+)\}")
SKIP_ATTRS = {"tags", "depends_on", "provider", "lifecycle", "count", "for_each", "tags_all"}
MAX_DEPTH = 8


class Extractor:
    def __init__(self, infra_dir: Path, repo_root: Path) -> None:
        self.infra_dir = infra_dir
        self.repo_root = repo_root.resolve()
        root = build((repo_root / infra_dir).resolve(), repo_root, "", [], None, False)
        found: list[Res] = []
        self.insts = list(root.walk())
        for inst in self.insts:
            for (rtype, name), blk in inst.mod.resources.items():
                found.append(Res(f"{inst.prefix}{rtype}.{name}", rtype, inst, blk, inst.multi or self.is_multi(blk)))
            for name, blk in inst.mod.calls.items():
                if name not in inst.children:
                    found.append(Res(f"{inst.prefix}module.{name}", "module", inst, blk,
                                     inst.multi or self.is_multi(blk), remote_info(blk)))
        resolved = {r.address: self.resolve(r) for r in found}
        self.res = sorted((r for r in found if resolved[r.address].kind != "drop"), key=lambda r: r.address)
        self.resolution = {r.address: resolved[r.address] for r in self.res}
        self.owner = {r.address: self.owner_of(r) for r in self.res}
        self.clouds = [c for c in CLOUDS.values() if c in self.owner.values()]
        self.edge_specs = {t: specs for c in self.clouds for t, specs in c.edge_specs.items()}
        self.network_attrs = frozenset().union(*(c.network_attrs for c in self.clouds))
        self.data_ref_types = frozenset().union(*(c.data_ref_types for c in self.clouds))
        self.param_types = frozenset().union(*(c.param_types for c in self.clouds))
        self.types = {r.address: r.type for r in self.res}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.services: dict[str, dict[str, set[str]]] = {}
        self.stats = {"unparsed_policies": 0, "constructed_arns": 0, "missing_outputs": 0}

    @staticmethod
    def is_multi(blk: Block) -> bool:
        return "count" in blk.body or "for_each" in blk.body

    def resolve(self, r: Res) -> Resolution:
        if r.type == "module":
            return resolve_module(r.extra["source"])
        if r.type.split("_", 1)[0] in IGNORED_PROVIDERS:
            return Resolution("drop")
        cloud = cloud_of_type(r.type)
        return cloud.resolve(r.type, self.getter(r)) if cloud else Resolution("none")

    def owner_of(self, r: Res) -> Cloud | None:
        if r.type == "module":
            return CLOUDS.get(icons.cloud_of(self.resolution[r.address].icon or ""))
        return cloud_of_type(r.type)

    def value(self, inst: Inst, expr: Any, depth: int = 0) -> str | None | object:
        """The literal `expr` is, through `local.`, module arguments and variable defaults; None when absent."""
        if expr is None:
            return None
        if isinstance(expr, (bool, int, float)):
            return str(expr).lower()
        if not isinstance(expr, str):
            return UNRESOLVED
        s = unq(expr)
        if not (m := SINGLE.fullmatch(s)):
            return UNRESOLVED if "${" in s else s
        kind, name = m.groups()
        if depth >= MAX_DEPTH:
            return UNRESOLVED
        where, target = inst, inst.mod.locals.get(name) if kind == "local" else inst.mod.variables.get(name)
        if kind == "var" and (passed := [a[name] for a in inst.args if name in a]) and inst.parent is not None:
            where, target = inst.parent, passed[0]
        got = self.value(where, target, depth + 1)
        return UNRESOLVED if got is None else got

    def getter(self, r: Res) -> Getter:
        def get(path: str, present: bool = False) -> str | None | bool | object:
            if present:
                return self.is_set(r.block.body, path.split("."))
            node: Any = r.block.body
            for key in path.split("."):
                node = node[0] if isinstance(node, list) and node else node
                if node is None:
                    return None
                if not isinstance(node, dict):
                    return UNRESOLVED
                node = node.get(key)
            node = node[0] if isinstance(node, list) and node else node
            return self.value(r.inst, node)

        return get

    @staticmethod
    def is_set(node: Any, keys: list[str]) -> bool:
        """Whether `keys` names an attribute in any of the repeated blocks along the path, whatever its value."""
        if isinstance(node, list):
            return any(Extractor.is_set(n, keys) for n in node)
        if not keys or not isinstance(node, dict) or keys[0] not in node:
            return False
        return len(keys) == 1 or Extractor.is_set(node[keys[0]], keys[1:])

    def refs(self, inst: Inst, obj: Any, seen: set | None = None) -> set[str]:
        seen = set() if seen is None else seen
        out: set[str] = set()
        for m in REF.finditer(text(obj)):
            head, second, third = m.groups()
            key = (id(inst), head, second, third)
            if key in seen:
                continue
            seen.add(key)
            if head == "var" and inst.parent is not None:
                for args in inst.args:
                    if second in args:
                        out |= self.refs(inst.parent, args[second], seen)
            elif head == "local" and second in inst.mod.locals:
                out |= self.refs(inst, inst.mod.locals[second], seen)
            elif head == "module" and second in inst.children and third:
                child = inst.children[second]
                if third in child.mod.outputs:
                    out |= self.refs(child, child.mod.outputs[third], seen)
                else:
                    self.stats["missing_outputs"] += 1
            elif head == "module" and second in inst.mod.calls and second not in inst.children:
                out.add(f"{inst.prefix}module.{second}")
            elif head == "data" and second in self.data_ref_types and third:
                blk = inst.mod.data.get((second, third))
                out |= self.refs(inst, blk.body, seen) if blk else set()
            elif (head, second) in inst.mod.resources:
                out.add(f"{inst.prefix}{head}.{second}")
        return out

    def leaf_refs(self, inst: Inst, obj: Any, leaf: str | None) -> set[str]:
        if leaf is None:
            return self.refs(inst, obj)
        if isinstance(obj, dict):
            return set().union(*(self.leaf_refs(inst, v, leaf) if k != leaf else self.refs(inst, v) for k, v in obj.items()))
        if isinstance(obj, list):
            return set().union(*(self.leaf_refs(inst, v, leaf) for v in obj))
        return set()

    def add(self, src: str, dst: str, kind: str, details: set[str], r: Res) -> None:
        if src == dst or src not in self.resolution or dst not in self.resolution:
            return
        edge = self.edges.setdefault((src, dst, kind), {"detail": set(), "at": (r.block.file, r.block.line)})
        edge["detail"] |= details
        edge["at"] = min(edge["at"], (r.block.file, r.block.line))

    def folded(self, address: str) -> bool:
        return self.resolution[address].kind == "fold"

    def generic(self, r: Res) -> None:
        body = attrs(r.block.body)
        consumed: set[str | None] = set()
        for spec in self.edge_specs.get(r.type, []):
            srcs = self.refs(r.inst, body.get(spec.src)) if spec.src else {r.address}
            dsts = self.leaf_refs(r.inst, body.get(spec.dst), spec.leaf)
            consumed |= {spec.src, spec.dst}
            for src in sorted(srcs):
                for dst in sorted(dsts):
                    self.add(src, dst, spec.kind, {spec.dst}, r)
        for attr, value in body.items():
            if attr in consumed or attr in SKIP_ATTRS or (r.type == "module" and attr in META):
                continue
            kind = "network" if attr in self.network_attrs else "uses"
            for dst in sorted(self.refs(r.inst, value)):
                if kind == "network" or not (self.folded(r.address) or (dst in self.resolution and self.folded(dst))):
                    self.add(r.address, dst, kind, {attr}, r)

    def entry(self, r: Res) -> dict[str, Any]:
        res, owner = self.resolution[r.address], self.owner[r.address]
        return {
            "address": r.address, "type": r.type, "module": r.inst.prefix.rstrip("."), "multi": r.multi,
            "file": r.block.file, "line": r.block.line, **r.extra,
            **({"instances": r.inst.instances} if r.inst.instances else {}),
            **({"cloud": owner.name, **owner.extra(self, r)} if owner else {}),
            **({"icon": res.icon} if res.icon else {}), **({"fold": "owner"} if res.kind == "fold" else {}),
            "marked": res.marked, **({"reason": res.reason} if res.reason else {}),
            **({"decided_by": res.decided_by} if res.decided_by else {}),
            **({"global": True} if res.scope == "global" else {}),
        }

    def networks(self) -> dict[str, list[dict]]:
        networks: list[dict] = []
        placements: list[dict] = []
        for cloud in self.clouds:
            found = cloud.network_facts(self)
            ids = {}
            for n in found["networks"]:
                ids[n["address"]] = f"n{len(networks) + 1}"
                networks.append({"id": ids[n["address"]], "cloud": cloud.name, **n})
            for p in found["placements"]:
                placements.append({"id": f"p{len(placements) + 1}", "cloud": cloud.name, **p, "network": ids[p["network"]]})
        return {"networks": networks, "placements": placements}

    def run(self) -> dict:
        for r in self.res:
            self.generic(r)
        for cloud in self.clouds:
            cloud.permission_edges(self)
        edges = []
        for i, ((src, dst, kind), e) in enumerate(sorted(self.edges.items())):
            edges.append({"id": f"f{i + 1}", "src": src, "dst": dst, "kind": kind,
                          "detail": ",".join(sorted(e["detail"])), "file": e["at"][0], "line": e["at"][1]})
        return {
            "infra_dir": str(self.infra_dir),
            "resources": [self.entry(r) for r in self.res],
            "edges": edges,
            **collect_hints(self.insts, self.res, self.repo_root, self.param_types),
            **self.networks(),
            "services": [
                {"service": s, "actions": sorted(v["actions"]), "principals": sorted(v["principals"])}
                for s, v in sorted(self.services.items())
            ],
        }


def extract(infra_dir: Path, repo_root: Path) -> dict:
    return Extractor(infra_dir, repo_root).run()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_root", type=Path)
    ap.add_argument("infra_dir", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()
    ex = Extractor(args.infra_dir, args.repo_root)
    facts = ex.run()
    args.out.write_text(json.dumps(facts, indent=1, sort_keys=True) + "\n")
    print(f"{len(facts['resources'])} resources, {len(facts['edges'])} edges, stats={ex.stats}", file=sys.stderr)


if __name__ == "__main__":
    main()
