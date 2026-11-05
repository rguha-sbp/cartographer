"""AWS network facts: VPCs with their CIDRs and the subnet tier each VPC-attached resource sits in."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cartographer.clouds.refs import CIDR, Ref, derive, sources, tier_in, token
from cartographer.tf_policies import unq
from cartographer.tf_values import find

if TYPE_CHECKING:
    from cartographer.tf_extract import Extractor
    from cartographer.tf_modules import Res

VPC_KEY = re.compile(r"(\w*_)?vpc_id")
SUBNET_KEY = re.compile(r"(\w*_)?subnets?(_ids?)?")
NOT_PLACED = {"aws_subnet", "aws_route_table_association", "aws_network_acl_association"}
TOKEN = token("aws_subnet|aws_vpc", "aws_(?:vpc|subnets?)")


def _local_tier(res: Res) -> tuple[str, str]:
    body = res.block.body
    if str(body.get("map_public_ip_on_launch")).strip('"').lower() == "true":
        return "public", "map_public_ip_on_launch"
    tags = body.get("tags")
    tagged = [v for k, v in tags.items() if unq(k) == "Name"] if isinstance(tags, dict) else []
    named = tier_in(" ".join(map(str, [body.get("name", ""), *tagged])))
    return (named, "name") if named else ("private", "default")


class Network:
    def __init__(self, ex: Extractor) -> None:
        self.ex = ex
        self.by_address = {r.address: r for r in ex.res}
        self.vpcs: dict[str, dict] = {}

    def cidrs(self, vpc: Res) -> list[str]:
        """Every CIDR of a local VPC, or none when any of them is not a literal."""
        blocks = [(vpc.inst, vpc.block.body.get("cidr_block"))]
        for r in self.ex.res:
            if r.type == "aws_vpc_ipv4_cidr_block_association" and Ref(vpc.address) in sources(
                r.inst, r.block.body.get("vpc_id"), TOKEN
            ):
                blocks.append((r.inst, r.block.body.get("cidr_block")))
        found = [self.ex.value(inst, value) for inst, value in blocks]
        if not all(isinstance(v, str) and CIDR.fullmatch(v) for v in found):
            return []
        return list(dict.fromkeys(found))  # type: ignore[arg-type]

    def collect_vpcs(self) -> None:
        for r in self.ex.res:
            if r.type == "aws_vpc":
                self.vpcs[r.address] = self._vpc(r.address, r.address.rsplit(".", 1)[1], self.cidrs(r), Ref(r.address), r)
        for r in self.ex.res:
            for value in find(r.block.body, VPC_KEY):
                for ref in sources(r.inst, value, TOKEN):
                    if ref.remote and ref.address not in self.vpcs:
                        self.vpcs[ref.address] = self._vpc(ref.address, derive(ref.name or ""), [], ref, r)

    @staticmethod
    def _vpc(address: str, name: str, cidrs: list[str], ref: Ref, res: Res) -> dict:
        return {"address": address, "name": name, "cidrs": cidrs, "remote": ref.remote, "stack": ref.stack,
                "file": res.block.file, "line": res.block.line}

    def remote_vpc(self, ref: Ref) -> str | None:
        """Address of the remote VPC of the same stack whose name prefixes an output name
        (`shared_vpc_private_subnet_ids`)."""
        hyphenated = derive(ref.name or "")
        named = [(len(v["name"]), a) for a, v in self.vpcs.items()
                 if v["remote"] and v["stack"] == ref.stack and hyphenated.startswith(v["name"] + "-")]
        return max(named)[1] if named else None

    def place(self, ref: Ref) -> tuple[str, str, str] | None:
        """(vpc address, tier, what decided the tier) for a subnet reference, None when either is unknown."""
        if ref.remote:
            tier, vpc = tier_in(ref.name or ""), self.remote_vpc(ref)
            return (vpc, tier, ref.name or "") if vpc and tier else None
        subnet = self.by_address[ref.address]
        if subnet.type != "aws_subnet":
            return None
        tier, how = _local_tier(subnet)
        vpc = next((r.address for r in sources(subnet.inst, subnet.block.body.get("vpc_id"), TOKEN) if r.address in self.vpcs), None)
        return (vpc, tier, f"{ref.address} {how}") if vpc else None

    def placements(self) -> list[dict]:
        found: dict[tuple[str, str, str], tuple[str, Res]] = {}
        for r in self.ex.res:
            if r.type in NOT_PLACED:
                continue
            for value in find(r.block.body, SUBNET_KEY):
                for ref in sources(r.inst, value, TOKEN):
                    if placed := self.place(ref):
                        found.setdefault((r.address, placed[0], placed[1]), (placed[2], r))
        return [{"resource": address, "network": vpc, "tier": tier, "via": via, "file": r.block.file, "line": r.block.line}
                for (address, vpc, tier), (via, r) in sorted(found.items())]


def network_facts(ex: Extractor) -> dict:
    net = Network(ex)
    net.collect_vpcs()
    return {"networks": [v for _, v in sorted(net.vpcs.items())], "placements": net.placements()}
