"""AWS network facts: VPCs with their CIDRs and the subnet tier each VPC-attached resource sits in."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cartographer.clouds.refs import (
    CIDR,
    Ref,
    add_remote,
    network_fact,
    place_remote,
    placement_facts,
    sources,
    tier_in,
    token,
)
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
        found = [inst.value(value) for inst, value in blocks]
        if not all(isinstance(v, str) and CIDR.fullmatch(v) for v in found):
            return []
        return list(dict.fromkeys(found))  # type: ignore[arg-type]

    def collect_vpcs(self) -> None:
        for r in self.ex.res:
            if r.type == "aws_vpc":
                self.vpcs[r.address] = network_fact(r.address.rsplit(".", 1)[1], self.cidrs(r), Ref(r.address), r)
        for r in self.ex.res:
            for value in find(r.block.body, VPC_KEY):
                for ref in sources(r.inst, value, TOKEN):
                    if ref.remote:
                        add_remote(self.vpcs, ref, r)

    def place(self, ref: Ref) -> tuple[str, str, str] | None:
        """(network key, tier, what decided the tier) for a subnet reference, None when either is unknown."""
        if ref.remote:
            return place_remote(self.vpcs, ref)
        subnet = self.by_address[ref.address]
        if subnet.type != "aws_subnet":
            return None
        tier, how = _local_tier(subnet)
        vpc = next((r.key() for r in sources(subnet.inst, subnet.block.body.get("vpc_id"), TOKEN) if r.key() in self.vpcs), None)
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
        return placement_facts(found)


def network_facts(ex: Extractor) -> dict:
    net = Network(ex)
    net.collect_vpcs()
    return {"networks": dict(sorted(net.vpcs.items())), "placements": net.placements()}
