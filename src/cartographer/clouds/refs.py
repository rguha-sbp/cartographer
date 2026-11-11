"""Reference following shared by the clouds' network facts: which subnets, networks and remote states a value points at.
Only `.tf` text is read: a remote state is compared by what its data block says, never opened."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cartographer.clouds.remote_state import LITERAL_INDEX, State, remote_key, state_of
from cartographer.tf_modules import bare
from cartographer.tf_policies import norm_keys, unq

TIERS = ("isolated", "private", "public")
CIDR = re.compile(r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}")
PATH = r"(?:\.[\w-]+|\[[^\]]*\])*"  # the attributes and indexes after a reference: `.vpc`, `["blue"]`, `[0]`
SEGMENT = re.compile(r'\.([\w-]+)|\[\s*(?:"([^"]*)"|(\d+)|([^\]]*))\s*\]')
INSTANCE = re.compile(r"^(?:\[[^\]]*\])+")  # the index of a module call with `count` or `for_each`
MODULE_PREFIX = re.compile(r'(?:module\.[\w-]+(?:\[(?:"[^"]*"|[^\]"]*)\])?\.)*')  # `module.a["k"].module.b.`
# the arguments by which a lookup selects its network or subnet, or the network its subnet is in
SELECTORS = ("id", "name", "filter", "tags", "vpc_id", "virtual_network_name")
NETWORK_LOOKUPS = ("aws_vpc", "azurerm_virtual_network")  # lookups that find a network, not a subnet
MAX_PATH = 16  # longer attribute paths only come from a local or variable that reads itself
SUFFIX = r"ids?|name|arn"  # the attributes that identify a resource rather than read a part of it
IDENTIFIER = re.compile(rf"(?:{SUFFIX})")
# a last attribute that identifies the network itself: `id`, `vpc_id`, `vnet_name`
IDENTIFYING = re.compile(rf"(?:(?:vpc|vnet|virtual_network|network)_)?(?:{SUFFIX})")
INDEX = re.compile(r"\[[^\]]*\]")
PART = re.compile(r"\[[^\]]*\]|[^.\[]+")  # the words and indexes of a `_render`ed name

if TYPE_CHECKING:
    from cartographer.tf_modules import Inst, Res


@dataclass(frozen=True)
class Ref:
    """A local resource (`name` None), a data source lookup (`name` its name, no `state`), or a remote output
    (`name` the output, `state` the `State` its data source names, or that data source's full address when its
    settings are not all literals). A lookup's address carries the module that declares it."""

    address: str
    name: str | None = None  # the output or lookup and the path it reads: `vpcs.blue.id`, `vpc_ids[0]`, `nets[*]`
    state: State | str | None = None
    tier: str | None = None  # the subnet tier the last name in the path gives (`vpcs["private-net"].public_subnet_ids`: public)
    within: tuple[str, ...] = ()  # a lookup's: the other resources of this stack its selectors read (`aws_vpc.main`)
    looks_up: str | None = None  # a lookup's data source type: `aws_vpc`, `aws_subnets`

    @property
    def remote(self) -> bool:
        return self.name is not None

    def key(self) -> str:
        """The key of the network this reference is or reads: a remote output's state and network name, so modules
        that read one network of one state share it; a resource's or lookup's address."""
        return remote_key(self.state, network_name(self.name or "")) if self.state is not None else self.address


def _render(name: str, path: tuple[str | None, ...]) -> str:
    """A name and the path read after it: a list index in brackets, an index that is no literal as `[*]`, an
    attribute or object key after a dot (`vpcs["blue"].id` -> `vpcs.blue.id`)."""
    return name + "".join("[*]" if p is None else f"[{p}]" if p.isdigit() else f".{p}" for p in path)


def segments(path: str) -> tuple[str | None, ...]:
    """The attributes and literal indexes of a reference's path; None for an index that is no literal (`[each.key]`)."""
    return tuple(next((g for g in m.groups()[:3] if g is not None), None) for m in SEGMENT.finditer(path))


def token(heads: str, data: str) -> re.Pattern[str]:
    """A reference to a local resource whose type matches `heads`, a data source matching `data`, or a remote output."""
    return re.compile(
        r"(?<![\w.\-])(?:(?P<remote>data\.(?P<kind>tfe_outputs|terraform_remote_state)\.(?P<state>[\w-]+)(?:\[(?P<index>[^\]]*)\])?"
        rf"\.(?:nonsensitive_values|values|outputs)\.(?P<out>\w+)(?P<outpath>{PATH})"
        rf"|(?P<lookup>data\.(?P<ds_type>{data})\.(?P<ds>[\w-]+))(?:\[(?P<ds_index>[^\]]*)\])?)"
        rf"|(?P<head>var|local|module|{heads})\.(?P<second>[\w-]+)(?P<path>{PATH}))"
    )


def sources(inst: Inst, obj: Any, pattern: re.Pattern[str]) -> dict[Ref, None]:
    """Resources and remote references `obj` points at, followed through locals, module variables and outputs. An
    attribute path (`var.base.networking.vpc_id`) reads only its part of an object literal, across every hop."""
    return _follow(inst, obj, (), pattern, set())


def _follow(inst: Inst, obj: Any, unread: tuple[str | None, ...], pattern: re.Pattern[str], seen: set) -> dict[Ref, None]:
    """`sources`, where `unread` is the attribute path a reference that is all of `obj` still has to read."""
    text = obj if isinstance(obj, str) else str(obj)
    whole = pattern.fullmatch(bare(text))
    out: dict[Ref, None] = {}
    for m in pattern.finditer(text):
        own = m["path"] or m["outpath"] or ""
        if m["head"] == "module":
            own = INSTANCE.sub("", own)  # `module.net[0].x`: every instance of a module has the same outputs
        path = (*segments(own), *(unread if whole else ()))
        if len(path) > MAX_PATH or (key := (id(inst), m[0], path)) in seen:
            continue
        seen.add(key)
        head, second = m["head"], m["second"]
        if m["kind"]:
            out[Ref(f"{inst.prefix}{m['remote']}", _render(m["out"], path),
                    state_of(inst, m["kind"], m["state"], m["index"]), _tier((m["out"], *path)))] = None
        elif m["ds"]:
            found = _looked_up(inst, m["ds"], m["ds_type"], pattern, seen)
            same = {r: None for r in found if r.address.split(".")[-2] == m["ds_type"].removesuffix("s")}
            out |= same or {_lookup(inst, m, tuple(r.address for r in found)): None}
        elif head == "var" and inst.parent is not None:
            for args in inst.args:
                if second in args:
                    out |= _follow_parts(inst.parent, _dig(args[second], path), pattern, seen)
        elif head == "local" and second in inst.mod.locals:
            out |= _follow_parts(inst, _dig(inst.mod.locals[second], path), pattern, seen)
        elif head == "module" and second in inst.children and path and path[0] in inst.children[second].mod.outputs:
            child = inst.children[second]
            out |= _follow_parts(child, _dig(child.mod.outputs[path[0]], path[1:]), pattern, seen)
        elif (head, second) in inst.mod.resources:
            out[Ref(f"{inst.prefix}{head}.{second}")] = None
    return out


def _follow_parts(inst: Inst, parts: list[tuple[Any, tuple[str | None, ...]]], pattern: re.Pattern[str],
                  seen: set) -> dict[Ref, None]:
    return {ref: None for value, unread in parts for ref in _follow(inst, value, unread, pattern, seen)}


def _looked_up(inst: Inst, name: str, ds_type: str, pattern: re.Pattern[str], seen: set) -> list[Ref]:
    """The resources this stack creates that the lookup `data.<ds_type>.<name>` reads through its `SELECTORS`
    (`id = aws_vpc.main.id`). One of type `ds_type` (`aws_subnet` for `aws_subnets`) is what the lookup finds, so it
    is no external network; another one holds what it finds (the VPC of a subnet). Each lookup follows its selectors with its own copy of `seen`, so
    a second read of it finds the same resources."""
    block, visit = inst.mod.data.get((ds_type, name)), (id(inst), ds_type, name)
    if block is None or visit in seen:
        return []
    selectors = {k: v for k, v in norm_keys(block.body).items() if k in SELECTORS}
    return [r for r in _follow(inst, selectors, (), pattern, {*seen, visit}) if not r.remote]


def _lookup(inst: Inst, m: re.Match[str], within: tuple[str, ...]) -> Ref:
    """What a lookup that selects no resource of its own type in this stack reads: an external network, one for
    each literal index of a `count` or `for_each` lookup, or a subnet `within` the resources its selectors read."""
    index = LITERAL_INDEX.fullmatch(m["ds_index"] or "")
    key = (index[0].strip('"'),) if index else ()
    suffix = f"[{index[0]}]" if index else ""
    return Ref(f"{inst.prefix}{m['lookup']}{suffix}", _render(m["ds"], key), tier=_tier((m["ds"], *key)),
               within=within, looks_up=m["ds_type"])


def _tier(path: tuple[str | None, ...]) -> str | None:
    """The tier the last name of a path gives; a key or object name before it never sets the tier. A list index, a
    non-literal index and an identifier attribute (`.id`) are no name."""
    return tier_in(next((p for p in reversed(path) if p is not None and not p.isdigit() and not IDENTIFIER.fullmatch(p)), ""))


def _dig(value: Any, path: tuple[str | None, ...]) -> list[tuple[Any, tuple[str | None, ...]]]:
    """The parts of an object or list literal a path reads, each with the rest of the path where the literal ends. A
    key or index the literal does not have reads nothing; an index that is no literal reads the rest of the path
    from every element (`local.nets[each.key].private_subnet_id`)."""
    for i, attr in enumerate(path):
        if attr is None and isinstance(value, (list, dict)):
            return [part for v in (value if isinstance(value, list) else value.values()) for part in _dig(v, path[i + 1:])]
        if attr is not None and isinstance(value, list) and attr.isdigit():
            value = value[int(attr)] if int(attr) < len(value) else ""
        elif attr is not None and isinstance(value, dict):
            value = next((v for k, v in value.items() if unq(k) == attr), "")
        else:
            return [(value, path[i:])]
    return [(value, ())]


def network_fact(name: str, cidrs: list[str], ref: Ref, res: Res) -> dict:
    """A network fact for the network `ref` is or reads, cited at `res`."""
    return {"address": ref.address, "name": name, "cidrs": cidrs, "remote": ref.remote, "file": res.block.file,
            "line": res.block.line}


def add_remote(networks: dict[str, dict], ref: Ref, res: Res) -> None:
    """Record the network a remote reference reads, once per `Ref.key`. A subnet lookup is no network: what reads its
    network (`data.aws_subnet.x.vpc_id`) names no network this stack can identify."""
    if ref.looks_up is not None and ref.looks_up not in NETWORK_LOOKUPS:
        return
    networks.setdefault(ref.key(), network_fact(network_name(ref.name or ""), [], ref, res))


def place_remote(networks: dict[str, dict], ref: Ref, ties: dict[str, str], address: str) -> tuple[str, str, str] | None:
    """(network key, tier, what decided the tier) for a subnet another stack or a lookup gives to the resource at
    `address`, None when either is unknown. When two networks fit equally well, `ties` gets why for `address`.

    A lookup `within` a network of this stack is in that network. Otherwise the network is a remote one whose name
    without indexes is the subnet's or starts it (`shared-vpc` for `shared_vpc_private_subnet_ids[0]`), with the
    subnet's indexes or none. A remote output's subnet goes to a network of its own state or a lookup, never to one
    of another state; when the subnet name names no network (`private_subnet_ids`), to the only network of its own
    state. Among the candidates, a network of
    its own state wins, then one with the subnet's indexes, then the longest name, then for a lookup one its own
    module looks up."""
    if not ref.tier:
        return None
    via = ref.name or ""
    if ref.within:
        candidates = {key: (True,) for key in ref.within if key in networks}
    else:
        stem, indexes = _stem(network_name(via))
        candidates = {}
        own_state: list[str] = []
        for key, n in networks.items():
            name, own_indexes = _stem(n["name"])
            own = ref.state is not None and key == remote_key(ref.state, n["name"])
            if not n["remote"] or not (own or ref.state is None or key == n["address"]):
                continue
            own_state += [key] if own else []
            if (stem == name or stem.startswith(name + "-")) and own_indexes in ((), indexes):
                same_module = ref.state is None and key == n["address"] and _module(key) == _module(ref.address)
                candidates[key] = (own, own_indexes == indexes, len(name), same_module)
        if not candidates and len(own_state) == 1 and not _names_network(stem):
            candidates = {own_state[0]: (True,)}
    ranked = sorted(candidates, key=candidates.__getitem__, reverse=True)
    if len(ranked) > 1 and candidates[ranked[0]] == candidates[ranked[1]]:
        ties.setdefault(address, f"{via} fits networks {' and '.join(sorted(networks[k]['address'] for k in ranked[:2]))} "
                                 "equally well")
        return None
    return (ranked[0], ref.tier, via) if ranked else None


def _names_network(stem: str) -> bool:
    """True when a subnet name says more than its tier: `other-vpc-private-subnet` names a network, `private-subnet`
    does not."""
    return any(word not in (*TIERS, "subnet", "subnets") for word in stem.split("-"))


def _stem(name: str) -> tuple[str, tuple[str, ...]]:
    """A network name without its indexes, and those indexes: `shared-vpc[0]` -> (`shared-vpc`, (`[0]`,))."""
    return INDEX.sub("", name), tuple(INDEX.findall(name))


def _module(address: str) -> str:
    """The module path a data source address starts with: `module.a.` for `module.a.data.aws_vpc.main`."""
    return MODULE_PREFIX.match(address)[0]


def placement_facts(found: dict[tuple[str, str, str], tuple[str, Res]]) -> list[dict]:
    """The placement facts of (resource, network, tier) -> (what decided the tier, the resource)."""
    return [{"resource": address, "network": network, "tier": tier, "via": via, "file": r.block.file, "line": r.block.line}
            for (address, network, tier), (via, r) in sorted(found.items())]


def unplaced(ties: dict[str, str], placements: list[dict]) -> dict[str, str]:
    """The ties of resources that no placement fact places: those resources are marked, with why."""
    placed = {p["resource"] for p in placements}
    return {address: why for address, why in ties.items() if address not in placed}


def blocks(value: Any) -> list[dict]:
    """The nested blocks of an attribute; one set as an expression (`subnet = var.x`) has none that can be read."""
    return [b for b in (value if isinstance(value, list) else [value]) if isinstance(b, dict)]


def network_name(name: str) -> str:
    """The network a remote output or lookup and the path it reads name: each word `derive`d, joined by `-`, each
    index kept in brackets (`shared_vpc_ids[0]` -> `shared-vpc[0]`). A last attribute that identifies what the
    network itself is no part of it (`network.vpc_id` -> `network`, `vpcs.blue.id` -> `vpcs-blue`), another one is
    (`network.app_vpc_id` -> `network-app-vpc`)."""
    parts = PART.findall(name)
    if len(parts) > 1 and IDENTIFYING.fullmatch(parts[-1]):
        parts = parts[:-1]
    return "".join(p if p.startswith("[") else f"-{derive(p)}" for p in parts).removeprefix("-")


def derive(name: str) -> str:
    """The network name a remote output or data source name implies: `shared_vpc_id` -> `shared-vpc`,
    `hub_vnet_name` -> `hub-vnet`."""
    return re.sub(rf"_(?:{SUFFIX})$", "", name).replace("_", "-")


def tier_in(name: str) -> str | None:
    return next((t for t in TIERS if t in name.lower()), None)
