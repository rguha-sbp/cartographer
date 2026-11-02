"""Azure network facts: virtual networks with their address spaces and the subnet tier each subnet-attached resource sits in.

Azure has no internet-gateway route, so a subnet's tier comes from the evidence around it: an internet-facing endpoint
(public), an explicit outbound path (private), or default outbound access switched off (isolated)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cartographer.clouds.refs import CIDR, Ref, derive, sources, tier_in, token
from cartographer.tf_policies import unq
from cartographer.tf_values import find, text

if TYPE_CHECKING:
    from cartographer.tf_extract import Extractor
    from cartographer.tf_modules import Inst, Res

NETWORK_KEY = re.compile(r"(\w*_)?virtual_network_(id|name)")
# virtual_network_subnet_id is VNet integration: outbound only, never a placement
SUBNET_KEY = re.compile(r"(?!virtual_network_subnet_ids?$)(\w*_)?subnet_ids?")
FRONTEND = "frontend_ip_configuration"
PUBLIC_IP_KEY = re.compile(r"public_ip_address(_id)?")
RESERVED_PUBLIC = {"GatewaySubnet", "AzureBastionSubnet", "AzureFirewallSubnet"}
NOT_PLACED = {"azurerm_subnet", "azurerm_virtual_network"}
TOKEN = token(r"azurerm_\w+", "azurerm_(?:virtual_network|subnet)")


@dataclass(frozen=True)
class Subnet:
    address: str  # an inline subnet is `<virtual network address>.subnet[<index>]`
    network: str | None
    body: dict
    owner: Res  # the azurerm_subnet, or the virtual network an inline subnet is declared in


class Network:
    def __init__(self, ex: Extractor) -> None:
        self.ex = ex
        self.by_address = ex.by_address
        self._body_refs: dict[str, dict[Ref, None]] = {}
        self._subnet_refs: dict[str, list[Subnet]] = {}
        self.nets: dict[str, dict] = {}
        self.subnets: dict[str, Subnet] = {}
        self.public: dict[str, str] = {}
        self.outbound: dict[str, str] = {}
        self.ambiguous: dict[str, str] = {}  # resource -> why a subnet reference could not be placed

    def refs(self, inst: Inst, obj: Any) -> dict[Ref, None]:
        return sources(inst, obj, TOKEN)

    def body_refs(self, r: Res) -> dict[Ref, None]:
        if r.address not in self._body_refs:
            self._body_refs[r.address] = self.refs(r.inst, r.block.body)
        return self._body_refs[r.address]

    def literal(self, res: Res, expr: Any) -> str | None:
        found = self.ex.value(res.inst, expr)
        return found if isinstance(found, str) else None

    def cidrs(self, vnet: Res) -> list[str]:
        """Every address prefix of a local virtual network, or none when any of them is not a literal."""
        raw = vnet.block.body.get("address_space")
        found = [self.ex.value(vnet.inst, v) for v in (raw if isinstance(raw, list) else [raw])]
        return list(dict.fromkeys(found)) if all(isinstance(v, str) and CIDR.fullmatch(v) for v in found) else []  # type: ignore[arg-type]

    @staticmethod
    def _net(address: str, name: str, cidrs: list[str], remote: bool, res: Res) -> dict:
        return {"address": address, "name": name, "cidrs": cidrs, "remote": remote,
                "file": res.block.file, "line": res.block.line}

    def collect_networks(self) -> None:
        for r in self.ex.res:
            if r.type == "azurerm_virtual_network":
                self.nets[r.address] = self._net(r.address, r.address.rsplit(".", 1)[1], self.cidrs(r), False, r)
        for r in self.ex.res:
            for value in find(r.block.body, NETWORK_KEY):
                for ref in self.refs(r.inst, value):
                    if ref.remote and ref.address not in self.nets:
                        self.nets[ref.address] = self._net(ref.address, derive(ref.name or ""), [], True, r)

    def collect_subnets(self) -> None:
        for r in self.ex.res:
            body = r.block.body
            if r.type == "azurerm_subnet":
                owner = next((x.address for x in self.refs(r.inst, body.get("virtual_network_name")) if x.address in self.nets), None)
                self.subnets[r.address] = Subnet(r.address, owner, body, r)
            elif r.type == "azurerm_virtual_network":
                inline = body.get("subnet") or []
                for i, block in enumerate(inline if isinstance(inline, list) else [inline]):
                    address = f"{r.address}.subnet[{i}]"
                    self.subnets[address] = Subnet(address, r.address, block, r)

    def subnet_refs(self, r: Res) -> list[Subnet]:
        """The local subnets `r` sits in: its own subnet attributes, and those of the network interfaces it uses."""
        if r.address in self._subnet_refs:
            return self._subnet_refs[r.address]
        found: dict[str, Subnet] = {}
        for ref in self.body_refs(r):
            nic = self.by_address.get(ref.address)
            if nic is not None and nic.type == "azurerm_network_interface":
                found |= {s.address: s for s in self.direct_subnets(nic)}
                if nic.address in self.ambiguous:
                    self.ambiguous.setdefault(r.address, self.ambiguous[nic.address])
        found |= {s.address: s for s in self.direct_subnets(r)}
        self._subnet_refs[r.address] = list(found.values())
        return self._subnet_refs[r.address]

    def direct_subnets(self, r: Res, body: Any = None) -> list[Subnet]:
        return [s for value in find(r.block.body if body is None else body, SUBNET_KEY)
                for ref in self.refs(r.inst, value) for s in self.subnet_of(r, ref, value)]

    def public_subnets(self, r: Res) -> list[Subnet]:
        """The subnets `r` exposes: all it names when it has a public ip, except those only frontends without one name."""
        body = r.block.body
        if not self.has_public_ip(body):
            return []
        raw = body.get(FRONTEND) or []
        frontends = raw if isinstance(raw, list) else [raw]
        exposed = [{k: v for k, v in body.items() if k != FRONTEND}, *(f for f in frontends if self.has_public_ip(f))]
        shared = {s.address for part in exposed for s in self.direct_subnets(r, part)}
        internal = {s.address for f in frontends if not self.has_public_ip(f) for s in self.direct_subnets(r, f)} - shared
        return [s for s in self.subnet_refs(r) if s.address not in internal]

    def subnet_of(self, r: Res, ref: Ref, value: Any) -> list[Subnet]:
        if ref.address in self.subnets:
            return [self.subnets[ref.address]]
        inline = [s for s in self.subnets.values() if s.address.startswith(f"{ref.address}.subnet[")]
        if len(inline) > 1 and len(named := [s for s in inline if self.quoted_in(s, value)]) != 1:
            self.ambiguous.setdefault(r.address, f"{ref.address} has {len(inline)} inline subnets and the reference does not single out one")
            return []
        return named if len(inline) > 1 else inline

    def quoted_in(self, s: Subnet, expr: Any) -> bool:
        """Whether the reference expression quotes the inline subnet's name or one of its address prefixes."""
        quoted = text(expr).replace('\\"', '"')
        prefixes = s.body.get("address_prefixes")
        literals = [self.literal(s.owner, v) for v in [s.body.get("name"), *(prefixes if isinstance(prefixes, list) else [prefixes])]]
        return any(f'"{lit}"' in quoted for lit in literals if lit)

    def collect_evidence(self) -> None:
        default_route = self.appliance_route_tables()
        outbound_pools = {
            ref.address
            for r in self.ex.res if r.type == "azurerm_lb_outbound_rule"
            for ref in self.refs(r.inst, r.block.body.get("backend_address_pool_id"))
        }
        for r in self.ex.res:
            if r.type == "azurerm_lb_outbound_rule":
                continue
            subnets = self.subnet_refs(r)
            self.public.update({s.address: "public ip" for s in self.public_subnets(r)})
            if r.type == "azurerm_subnet_nat_gateway_association":
                self.outbound.update({s.address: "nat gateway" for s in subnets})
            if r.type == "azurerm_subnet_route_table_association" and any(
                ref.address in default_route for ref in self.refs(r.inst, r.block.body.get("route_table_id"))
            ):
                self.outbound.update({s.address: "route to virtual appliance" for s in subnets})
            if any(ref.address in outbound_pools for ref in self.body_refs(r)):
                self.outbound.update({s.address: "load balancer outbound rule" for s in subnets})

    @staticmethod
    def has_public_ip(body: Any) -> bool:
        return any(v is not None and unq(v) not in ("", "null") for v in find(body, PUBLIC_IP_KEY))

    def appliance_route_tables(self) -> set[str]:
        """Route tables with a `0.0.0.0/0` route to a virtual appliance, inline or as a separate azurerm_route."""
        def to_appliance(res: Res, route: Any) -> bool:
            return (isinstance(route, dict) and self.literal(res, route.get("address_prefix")) == "0.0.0.0/0"
                    and self.literal(res, route.get("next_hop_type")) == "VirtualAppliance")

        tables: set[str] = set()
        for r in self.ex.res:
            if r.type == "azurerm_route_table":
                inline = r.block.body.get("route") or []
                if any(to_appliance(r, route) for route in (inline if isinstance(inline, list) else [inline])):
                    tables.add(r.address)
            elif r.type == "azurerm_route" and to_appliance(r, r.block.body):
                tables |= {x.address for x in self.refs(r.inst, r.block.body.get("route_table_name"))}
        return tables

    def tier(self, s: Subnet) -> tuple[str, str]:
        """(tier, what decided it) for a local subnet."""
        name = self.literal(s.owner, s.body.get("name"))
        if s.address in self.public:
            return "public", f"{s.address} {self.public[s.address]}"
        if name in RESERVED_PUBLIC:
            return "public", f"{s.address} reserved name {name}"
        if s.address in self.outbound:
            return "private", f"{s.address} {self.outbound[s.address]}"
        if self.literal(s.owner, s.body.get("default_outbound_access_enabled")) == "false":
            return "isolated", f"{s.address} default_outbound_access_enabled = false"
        tags = s.body.get("tags")
        tagged = [self.literal(s.owner, v) for k, v in tags.items() if unq(k) == "Name"] if isinstance(tags, dict) else []
        named = tier_in(" ".join(x for x in (name, *tagged) if x))
        return (named, f"{s.address} name") if named else ("private", f"{s.address} default")

    def remote_network(self, name: str) -> str | None:
        """Address of the remote network whose name prefixes an output name (`shared_vnet_private_subnet_id`)."""
        hyphenated = derive(name)
        named = [(len(n["name"]), a) for a, n in self.nets.items() if n["remote"] and hyphenated.startswith(n["name"] + "-")]
        return max(named)[1] if named else None

    def place_remote(self, ref: Ref) -> tuple[str, str, str] | None:
        """(network address, tier, what decided the tier) for a subnet of another stack, None when either is unknown."""
        tier, net = tier_in(ref.name or ""), self.remote_network(ref.name or "")
        return (net, tier, ref.name or "") if net and tier else None

    def placements(self) -> list[dict]:
        found: dict[tuple[str, str, str], tuple[str, Res]] = {}
        for r in self.ex.res:
            if r.type in NOT_PLACED or self.ex.folded(r.address):
                continue
            for s in self.subnet_refs(r):
                if s.network in self.nets:
                    tier, via = self.tier(s)
                    found.setdefault((r.address, s.network, tier), (via, r))
            for value in find(r.block.body, SUBNET_KEY):
                for ref in self.refs(r.inst, value):
                    if ref.remote and (placed := self.place_remote(ref)):
                        found.setdefault((r.address, placed[0], placed[1]), (placed[2], r))
        return [{"resource": address, "network": net, "tier": tier, "via": via, "file": r.block.file, "line": r.block.line}
                for (address, net, tier), (via, r) in sorted(found.items())]


def network_facts(ex: Extractor) -> dict:
    net = Network(ex)
    net.collect_networks()
    net.collect_subnets()
    net.collect_evidence()
    return {"networks": [v for _, v in sorted(net.nets.items())], "placements": net.placements(), "unplaced": net.ambiguous}
