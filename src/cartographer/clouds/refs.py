"""Reference following shared by the clouds' network facts: which subnets, networks and remote states a value points at.
Only `.tf` text is read: a remote state is compared by what its data block says, never opened."""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cartographer.clouds.remote_state import LITERAL_INDEX, State, remote_key, state_of
from cartographer.tf_policies import norm_keys, unq
from cartographer.tf_values import find

TIERS = ("isolated", "private", "public")
SUBNET_WORDS = (*TIERS, "subnet", "subnets")  # the words of a name that say it is a subnet
CIDR = re.compile(r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}")
PATH = r"(?:\.[\w-]+|\[[^\]]*\])*"  # the attributes and indexes after a reference: `.vpc`, `["blue"]`, `[0]`
SEGMENT = re.compile(r'\.([\w-]+)|\[\s*(?:"([^"]*)"|(\d+)|([^\]]*))\s*\]')
INSTANCE = re.compile(r"^(?:\[[^\]]*\])+")  # the index of a module call with `count` or `for_each`
MODULE_PREFIX = re.compile(r'(?:module\.[\w-]+(?:\[(?:"[^"]*"|[^\]"]*)\])?\.)*')  # `module.a["k"].module.b.`
# the arguments by which a lookup selects its network or subnet, or the network its subnet is in
SELECTORS = ("id", "name", "filter", "tags", "vpc_id", "virtual_network_name")
NETWORK_LOOKUPS = ("aws_vpc", "azurerm_virtual_network")  # lookups that find a network, not a subnet
NETWORK_ARGS = ("vpc_id", "virtual_network_name")  # the argument by which a resource names its network
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
    within: tuple[Ref, ...] = ()  # a lookup's: what its selectors read (`aws_vpc.main`, a looked-up VPC)
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


@dataclass
class _Walk:
    """One `sources` call: the pattern it follows, the (instance, reference, path) it has read, and what each lookup
    reads (`_looked_up`), shared so a lookup that many paths reach is followed once."""

    pattern: re.Pattern[str]
    seen: set = field(default_factory=set)
    lookups: dict[tuple, tuple[list[Ref], list[Ref]] | None] = field(default_factory=dict)


def sources(inst: Inst, obj: Any, pattern: re.Pattern[str]) -> dict[Ref, None]:
    """Resources and remote references `obj` points at, followed through locals, module variables and outputs. An
    attribute path (`var.base.networking.vpc_id`) reads only its part of an object literal, across every hop."""
    return _follow(inst, obj, (), _Walk(pattern))


def _follow(inst: Inst, obj: Any, unread: tuple[str | None, ...], walk: _Walk) -> dict[Ref, None]:
    """`sources`, where `unread` is the attribute path a reference that is all of `obj` still has to read."""
    text = obj if isinstance(obj, str) else str(obj)
    out: dict[Ref, None] = {}
    for m in walk.pattern.finditer(text):
        own = m["path"] or m["outpath"] or ""
        if m["head"] == "module":
            own = INSTANCE.sub("", own)  # `module.net[0].x`: every instance of a module has the same outputs
        path = (*segments(own), *unread)  # `merge(local.a, local.b).vpc_id` reads `vpc_id` of each
        if len(path) > MAX_PATH or (key := (id(inst), m[0], path)) in walk.seen:
            continue
        walk.seen.add(key)
        head, second = m["head"], m["second"]
        if m["kind"]:
            out[Ref(f"{inst.prefix}{m['remote']}", _render(m["out"], path),
                    state_of(inst, m["kind"], m["state"], m["index"]), _tier((m["out"], *path)))] = None
        elif m["ds"]:
            found, whole = _looked_up(inst, m["ds"], m["ds_type"], walk)
            same = {r: None for r in whole if not r.remote and r.address.split(".")[-2] == m["ds_type"].removesuffix("s")}
            out |= same or {_lookup(inst, m, tuple(found)): None}
        elif head == "var" and inst.parent is not None:
            for args in inst.args:
                if second in args:
                    out |= _follow_parts(inst.parent, _dig(args[second], path), walk)
        elif head == "local" and second in inst.mod.locals:
            out |= _follow_parts(inst, _dig(inst.mod.locals[second], path), walk)
        elif head == "module" and second in inst.children and path and path[0] in inst.children[second].mod.outputs:
            child = inst.children[second]
            out |= _follow_parts(child, _dig(child.mod.outputs[path[0]], path[1:]), walk)
        elif resource := inst.mod.resources.get((head, second)):
            if path and path[0] in NETWORK_ARGS and path[0] in (body := norm_keys(resource.body)):
                out |= _follow(inst, body[path[0]], path[1:], walk)  # `aws_subnet.a.vpc_id` is the subnet's VPC
            else:
                out[Ref(f"{inst.prefix}{head}.{second}")] = None
    return out


def _follow_parts(inst: Inst, parts: list[tuple[Any, tuple[str | None, ...]]], walk: _Walk) -> dict[Ref, None]:
    return {ref: None for value, unread in parts for ref in _follow(inst, value, unread, walk)}


def _looked_up(inst: Inst, name: str, ds_type: str, walk: _Walk) -> tuple[list[Ref], list[Ref]]:
    """What the lookup `data.<ds_type>.<name>` reads through its `SELECTORS`, and what a selector that is one whole
    reference reads (`id = aws_vpc.main.id`, not `"${aws_vpc.main.tags.Name}-peer"`): only such a selector can find a
    resource of this stack itself. Each lookup is followed once per walk, with its own `seen`, so every path that reaches
    it finds the same references; a lookup that reads itself reads nothing the second time."""
    visit = (id(inst), ds_type, name)
    if visit not in walk.lookups:
        walk.lookups[visit] = None
        block = inst.mod.data.get((ds_type, name))
        selectors = {k: v for k, v in norm_keys(block.body).items() if k in SELECTORS} if block else {}

        def read(value: Any) -> list[Ref]:
            return list(_follow(inst, value, (), _Walk(walk.pattern, lookups=walk.lookups)))

        walk.lookups[visit] = (read(selectors), read(list(_whole(selectors, walk.pattern))))
    return walk.lookups[visit] or ([], [])


def _whole(value: Any, pattern: re.Pattern[str]) -> Iterator[str]:
    """The strings in `value` that are one reference and nothing else: `${aws_vpc.main.id}`, `"${local.vpc_id}"`."""
    if isinstance(value, (dict, list)):
        for v in value.values() if isinstance(value, dict) else value:
            yield from _whole(v, pattern)
        return
    expr = unq(value)
    expr = expr[2:-1] if expr.startswith("${") and expr.endswith("}") and expr.count("${") == 1 else expr
    if (m := pattern.match(expr)) and re.fullmatch(PATH, expr[m.end():]):
        yield expr


def _lookup(inst: Inst, m: re.Match[str], within: tuple[Ref, ...]) -> Ref:
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


def place_remote(networks: dict[str, dict], ref: Ref, why: dict[str, str], address: str) -> tuple[str, str, str] | None:
    """(network key, tier, what decided the tier) for a subnet another stack or a lookup gives to the resource at
    `address`. A lookup `within` a network this stack knows is in that network; otherwise `_candidates` rank the
    networks. When no network fits, two fit equally well, or the subnet name gives no tier, the result is None and
    `why` gets the reason for `address`."""
    via = ref.name or ""
    candidates = {k: () for r in ref.within if (k := r.key()) in networks} if ref.within else _candidates(networks, ref)
    ranked = sorted(candidates, key=candidates.__getitem__, reverse=True)
    if not ranked:
        why.setdefault(address, f"{via} fits no network this stack knows")
    elif len(ranked) > 1 and candidates[ranked[0]] == candidates[ranked[1]]:
        why.setdefault(address, f"{via} fits networks {' and '.join(sorted(networks[k]['address'] for k in ranked[:2]))} "
                                "equally well")
    elif not ref.tier:
        why.setdefault(address, f"{via} is in {networks[ranked[0]]['address']}, its name gives no subnet tier")
    else:
        return ranked[0], ref.tier, via
    return None


def collect_remote(networks: dict[str, dict], resources: list[Res], network_key: re.Pattern[str],
                   subnet_key: re.Pattern[str], pattern: re.Pattern[str]) -> None:
    """Record the remote networks the resources name: in a network argument (`vpc_id`), or as what a subnet lookup is
    in (`vpc-id = data.aws_vpc.shared.id`)."""
    for r in resources:
        for value in find(r.block.body, network_key):
            for ref in sources(r.inst, value, pattern):
                if ref.remote:
                    add_remote(networks, ref, r)
        for value in find(r.block.body, subnet_key):
            for ref in sources(r.inst, value, pattern):
                for net in ref.within:
                    if net.remote:
                        add_remote(networks, net, r)


def _candidates(networks: dict[str, dict], ref: Ref) -> dict[str, tuple]:
    """The remote networks a subnet name fits, each with its rank. A network fits when its name without indexes
    starts the subnet's (`shared-vpc` for `shared-vpc-private-subnet`, `vpcs.blue` for `vpcs.blue.private-subnet`,
    never `vpcs.blue` for `vpcs.blue-east.private-subnet`) and its indexes are the subnet's or none. A remote output's
    subnet only fits a network of its own state or a lookup; one whose name names no network (`private_subnet_ids`)
    fits every network of its own state. Rank: own state, then the subnet's indexes, then the longest name, then for
    a lookup one its own module looks up."""
    stem, indexes = _stem(network_name(ref.name or ""))
    named: dict[str, tuple] = {}
    unnamed: dict[str, tuple] = {}
    for key, n in networks.items():
        own = ref.state is not None and key == remote_key(ref.state, n["name"])
        lookup = key == n["address"]
        name, own_indexes = _stem(n["name"])
        if not n["remote"] or not (own or ref.state is None or lookup) or own_indexes not in ((), indexes):
            continue
        rank = (own, own_indexes == indexes)
        if _starts(name.split("."), stem.split(".")):
            named[key] = (*rank, len(name), ref.state is None and lookup and _module(key) == _module(ref.address))
        elif own and not _names_network(stem):
            unnamed[key] = rank
    return named or unnamed


def _starts(network: list[str], subnet: list[str]) -> bool:
    """True when a network's parts start a subnet's: all but the last part equal, and the last part equal or the first
    words of a part whose other words are about subnets (`shared-vpc` of `shared-vpc-private-subnet`, `vpc` of
    `vpc-subnets`, but not `blue` of `blue-east`)."""
    last = len(network) - 1
    if len(network) > len(subnet) or network[:last] != subnet[:last]:
        return False
    head, part = network[last], subnet[last]
    return part == head or (part.startswith(head + "-") and not set(part[len(head) + 1:].split("-")).isdisjoint(SUBNET_WORDS))


def _names_network(stem: str) -> bool:
    """True when a subnet name says more than its tier: `other-vpc-private-subnet` names a network, `private-subnet`
    does not."""
    return any(word not in SUBNET_WORDS for word in re.split(r"[.-]", stem))


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


def unplaced(why: dict[str, str], placements: list[dict]) -> dict[str, str]:
    """Why each resource that no placement fact places has a subnet that could not be placed: it is marked."""
    placed = {p["resource"] for p in placements}
    return {address: reason for address, reason in why.items() if address not in placed}


def blocks(value: Any) -> list[dict]:
    """The nested blocks of an attribute; one set as an expression (`subnet = var.x`) has none that can be read."""
    return [b for b in (value if isinstance(value, list) else [value]) if isinstance(b, dict)]


def network_name(name: str) -> str:
    """The network a remote output or lookup and the path it reads name: each attribute or key `derive`d, joined by
    `.`, each index kept in brackets (`shared_vpc_ids[0]` -> `shared-vpc[0]`). A last attribute that identifies the
    network itself is no part of it (`network.vpc_id` -> `network`, `vpcs.blue.id` -> `vpcs.blue`), another one is
    (`network.app_vpc_id` -> `network.app-vpc`)."""
    parts = PART.findall(name)
    if len(parts) > 1 and IDENTIFYING.fullmatch(parts[-1]):
        parts = parts[:-1]
    return "".join(p if p.startswith("[") else f".{derive(p)}" for p in parts).removeprefix(".")


def derive(name: str) -> str:
    """The network name a remote output or data source name implies: `shared_vpc_id` -> `shared-vpc`,
    `hub_vnet_name` -> `hub-vnet`."""
    return re.sub(rf"_(?:{SUFFIX})$", "", name).replace("_", "-")


def tier_in(name: str) -> str | None:
    return next((t for t in TIERS if t in name.lower()), None)
