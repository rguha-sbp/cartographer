"""Network facts for tfdiagram: VPCs with their CIDRs and the subnet tier each VPC-attached resource sits in."""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cartographer.tf_policies import unq

if TYPE_CHECKING:
    from cartographer.tf_extract import Extractor, Inst, Res

TIERS = ("isolated", "private", "public")
CIDR = re.compile(r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}")
VPC_KEY = re.compile(r"(\w*_)?vpc_id")
SUBNET_KEY = re.compile(r"(\w*_)?subnets?(_ids?)?")
SINGLE = re.compile(r"\$\{(var|local)\.(\w+)\}")
NOT_PLACED = {"aws_subnet", "aws_route_table_association", "aws_network_acl_association"}
MAX_DEPTH = 8
TOKEN = re.compile(
    r"(?<![\w.\-])(?:(?P<remote>data\.(?:tfe_outputs|terraform_remote_state)\.\w+"
    r"\.(?:nonsensitive_values|values|outputs)\.(?P<out>\w+)|data\.aws_(?:vpc|subnets?)\.(?P<ds>\w+))"
    r"|(?P<head>var|local|module|aws_subnet|aws_vpc)\.(?P<second>[\w-]+)(?:\[[^\]]*\])?(?:\.(?P<third>[\w-]+))?)"
)


@dataclass(frozen=True)
class Ref:
    """A local aws_subnet or aws_vpc (`name` None) or a reference to another stack (`name` is its output or data name)."""

    address: str
    name: str | None = None

    @property
    def remote(self) -> bool:
        return self.name is not None


def _derive(name: str) -> str:
    return re.sub(r"_ids?$", "", name).replace("_", "-")


def _find(obj: Any, key: re.Pattern[str]) -> Iterator[Any]:
    """Values of every attribute whose name matches `key`, at any block depth."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if key.fullmatch(unq(k)):
                yield v
            else:
                yield from _find(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _find(v, key)


def _tier_in(name: str) -> str | None:
    return next((t for t in TIERS if t in name.lower()), None)


def _local_tier(res: Res) -> tuple[str, str]:
    body = res.block.body
    if str(body.get("map_public_ip_on_launch")).strip('"').lower() == "true":
        return "public", "map_public_ip_on_launch"
    tags = body.get("tags")
    tagged = [v for k, v in tags.items() if unq(k) == "Name"] if isinstance(tags, dict) else []
    named = _tier_in(" ".join(map(str, [body.get("name", ""), *tagged])))
    return (named, "name") if named else ("private", "default")


class Network:
    def __init__(self, ex: Extractor) -> None:
        self.ex = ex
        self.by_address = {r.address: r for r in ex.res}
        self.vpcs: dict[str, dict] = {}

    def sources(self, inst: Inst, obj: Any, seen: set | None = None) -> dict[Ref, None]:
        """Subnets, VPCs and remote references `obj` points at, followed through locals and module variables."""
        seen = set() if seen is None else seen
        out: dict[Ref, None] = {}
        for m in TOKEN.finditer(obj if isinstance(obj, str) else str(obj)):
            if (key := (id(inst), m[0])) in seen:
                continue
            seen.add(key)
            head, second, third = m["head"], m["second"], m["third"]
            if m["remote"]:
                out[Ref(m["remote"], m["out"] or m["ds"])] = None
            elif head == "var" and inst.parent is not None:
                for args in inst.args:
                    if second in args:
                        out |= self.sources(inst.parent, args[second], seen)
            elif head == "local" and second in inst.mod.locals:
                out |= self.sources(inst, inst.mod.locals[second], seen)
            elif head == "module" and second in inst.children and third in inst.children[second].mod.outputs:
                child = inst.children[second]
                out |= self.sources(child, child.mod.outputs[third], seen)
            elif (head, second) in inst.mod.resources:
                out[Ref(f"{inst.prefix}{head}.{second}")] = None
        return out

    def literal(self, inst: Inst, value: Any, depth: int = 0) -> str | None:
        """The string `value` is, or resolves through locals and variable defaults to, when it is a CIDR."""
        s = unq(value) if isinstance(value, str) else ""
        if m := SINGLE.fullmatch(s):
            kind, name = m.groups()
            if depth >= MAX_DEPTH:
                return None
            if kind == "local":
                return self.literal(inst, inst.mod.locals.get(name), depth + 1)
            passed = [a[name] for a in inst.args if name in a]
            if passed and inst.parent is not None:
                return self.literal(inst.parent, passed[0], depth + 1)
            return self.literal(inst, inst.mod.variables.get(name), depth + 1)
        return s if CIDR.fullmatch(s) else None

    def cidrs(self, vpc: Res) -> list[str]:
        """Every CIDR of a local VPC, or none when any of them is not a literal."""
        blocks = [(vpc.inst, vpc.block.body.get("cidr_block"))]
        for r in self.ex.res:
            if r.type == "aws_vpc_ipv4_cidr_block_association" and Ref(vpc.address) in self.sources(
                r.inst, r.block.body.get("vpc_id")
            ):
                blocks.append((r.inst, r.block.body.get("cidr_block")))
        found = [self.literal(inst, value) for inst, value in blocks]
        return [] if None in found else list(dict.fromkeys(found))  # type: ignore[arg-type]

    def collect_vpcs(self) -> None:
        for r in self.ex.res:
            if r.type == "aws_vpc":
                self.vpcs[r.address] = self._vpc(r.address, r.address.rsplit(".", 1)[1], self.cidrs(r), False, r)
        for r in self.ex.res:
            for value in _find(r.block.body, VPC_KEY):
                for ref in self.sources(r.inst, value):
                    if ref.remote and ref.address not in self.vpcs:
                        self.vpcs[ref.address] = self._vpc(ref.address, _derive(ref.name or ""), [], True, r)

    @staticmethod
    def _vpc(address: str, name: str, cidrs: list[str], remote: bool, res: Res) -> dict:
        return {"address": address, "name": name, "cidrs": cidrs, "remote": remote,
                "file": res.block.file, "line": res.block.line}

    def remote_vpc(self, name: str) -> str | None:
        """Address of the remote VPC whose name prefixes an output name (`shared_vpc_private_subnet_ids`)."""
        hyphenated = _derive(name)
        named = [(len(v["name"]), a) for a, v in self.vpcs.items() if v["remote"] and hyphenated.startswith(v["name"] + "-")]
        return max(named)[1] if named else None

    def place(self, ref: Ref) -> tuple[str, str, str] | None:
        """(vpc address, tier, what decided the tier) for a subnet reference, None when either is unknown."""
        if ref.remote:
            tier, vpc = _tier_in(ref.name or ""), self.remote_vpc(ref.name or "")
            return (vpc, tier, ref.name or "") if vpc and tier else None
        subnet = self.by_address[ref.address]
        if subnet.type != "aws_subnet":
            return None
        tier, how = _local_tier(subnet)
        vpc = next((r.address for r in self.sources(subnet.inst, subnet.block.body.get("vpc_id")) if r.address in self.vpcs), None)
        return (vpc, tier, f"{ref.address} {how}") if vpc else None

    def placements(self) -> list[dict]:
        found: dict[tuple[str, str, str], tuple[str, Res]] = {}
        for r in self.ex.res:
            if r.type in NOT_PLACED:
                continue
            for value in _find(r.block.body, SUBNET_KEY):
                for ref in self.sources(r.inst, value):
                    if placed := self.place(ref):
                        found.setdefault((r.address, placed[0], placed[1]), (placed[2], r))
        return [{"resource": address, "vpc": vpc, "tier": tier, "via": via, "file": r.block.file, "line": r.block.line}
                for (address, vpc, tier), (via, r) in sorted(found.items())]


def network_facts(ex: Extractor) -> dict:
    net = Network(ex)
    net.collect_vpcs()
    ids = {a: f"v{i}" for i, a in enumerate(sorted(net.vpcs), 1)}
    return {
        "vpcs": [{"id": ids[a], **v} for a, v in sorted(net.vpcs.items())],
        "placements": [{"id": f"p{i}", **p, "vpc": ids[p["vpc"]]} for i, p in enumerate(net.placements(), 1)],
    }
