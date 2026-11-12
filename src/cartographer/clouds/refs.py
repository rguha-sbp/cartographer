"""Reference following shared by the clouds' network facts: which subnets, networks and remote states a value points at.
Only `.tf` text is read: a remote state is compared by what its data block says, never opened."""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cartographer.clouds.remote_state import LITERAL_INDEX, State, remote_key, state_of
from cartographer.tf_modules import bare, declared_provider
from cartographer.tf_policies import norm_keys, unq
from cartographer.tf_values import find

TIERS = ("isolated", "private", "public")
SUBNET_WORDS = (*TIERS, "subnet", "subnets")  # the words of a name that say it is a subnet
CIDR = re.compile(r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}")
PATH = r"(?:\.[\w-]+|\[[^\]]*\])*"  # the attributes and indexes after a reference: `.vpc`, `["blue"]`, `[0]`
SEGMENT = re.compile(r'\.([\w-]+)|\[\s*(?:"([^"]*)"|(\d+)|([^\]]*))\s*\]')
INSTANCE = re.compile(r"^(?:\[[^\]]*\])+")  # the index of a module call or resource with `count` or `for_each`
MODULE_PREFIX = re.compile(r'(?:module\.[\w-]+(?:\[(?:"[^"]*"|[^\]"]*)\])?\.)*')  # `module.a["k"].module.b.`
# the arguments and `filter` names by which a lookup picks one resource of the type it looks up: only these can make
# it a resource of this stack, and only together with the same provider and the same `AGREE` arguments
PICKS = {"aws_vpc": ("id", "vpc-id"), "aws_subnet": ("id", "subnet-id"), "aws_subnets": ("subnet-id",),
         "azurerm_virtual_network": ("name",), "azurerm_subnet": ("name",)}
AGREE = {"azurerm_virtual_network": ("resource_group_name",),
         "azurerm_subnet": ("resource_group_name", "virtual_network_name")}
IN_NETWORK = ("vpc_id", "vpc-id", "virtual_network_name")  # what names the network a subnet lookup is in
NETWORK_LOOKUPS = ("aws_vpc", "azurerm_virtual_network")  # lookups that find a network, not a subnet
# the attributes a reference reads through to what they are written as: the tags of a resource or lookup are data
# (`aws_vpc.main.tags.peer_vpc_id` is a tag value, never the VPC), and a resource's network argument names its network
# (`aws_subnet.a.vpc_id` is the subnet's VPC)
TAGS = ("tags", "tags_all")
READ_THROUGH = ("vpc_id", "virtual_network_name", *TAGS)
MAX_READS = 10_000  # distinct references one walk reads; only paths that fan out through functions at every level need more
MAX_HOPS = 100  # locals, variables, outputs and lookups nested deeper only come from generated code; they read nothing
MAX_PATH = 16  # longer attribute paths only come from a local or variable that reads itself
SUFFIX = r"ids?|name|arn"  # the attributes that identify a resource rather than read a part of it
IDENTIFIER = re.compile(rf"(?:{SUFFIX})")
# a last attribute that identifies the network itself: `id`, `vpc_id`, `vnet_name`
IDENTIFYING = re.compile(rf"(?:(?:vpc|vnet|virtual_network|network)_)?(?:{SUFFIX})")
RESOURCE_ARG = re.compile(r"(?!(?:var|local|module|data)\.)([\w-]+)\.([\w-]+)\.([\w-]+)")  # `type.name.argument`
INDEX = re.compile(r"\[[^\]]*\]")
PART = re.compile(r"\[[^\]]*\]|[^.\[]+")  # the words and indexes of a `_render`ed name
MEMBER = re.compile(r'(?:^|[{,\s])([\w-]+|"[^"]*")\s*=\s*$')  # `key = ` before a value in an object inside a function
INTERPOLATION = re.compile(r"\$\{[^}]*\}")
TIER_WORD = re.compile(rf"(?<![a-z])(?:{'|'.join(TIERS)})")  # a tier word that starts a word: never `republic`

if TYPE_CHECKING:
    from cartographer.tf_modules import Inst, Res


class Key(str):
    """An object key read in brackets (`vpcs["blue"]`, `subnet_ids["eu-west-1a"]`): part of a network name, never the
    name that gives a subnet tier."""


@dataclass(frozen=True)
class Ref:
    """A local resource (`name` None), a data source lookup (`name` its name, no `state`), or a remote output
    (`name` the output, `state` the `State` its data source names, or that data source's full address when its
    settings are not all literals). A lookup's address carries the module that declares it."""

    address: str
    name: str | None = None  # the output or lookup and the path it reads: `vpcs.blue.id`, `vpc_ids[0]`, `nets[*]`
    state: State | str | None = None
    tier: str | None = None  # the subnet tier the last name in the path gives (`vpcs["private-net"].public_subnet_ids`: public)
    within: tuple[Ref, ...] = ()  # a subnet lookup's: what names its network (`aws_vpc.main`, a looked-up VPC)
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
    return name + "".join("[*]" if p is None else f"[{p}]" if p.isdecimal() else f".{p}" for p in path)


def segments(path: str) -> tuple[str | None, ...]:
    """The attributes and literal indexes of a reference's path; None for an index that is no literal (`[each.key]`)."""
    return tuple(m[1] or (Key(m[2]) if m[2] is not None else m[3]) for m in SEGMENT.finditer(path))


def token(heads: str, data: str) -> re.Pattern[str]:
    """A reference to a local resource whose type matches `heads`, a data source matching `data`, or a remote output."""
    return re.compile(
        r"(?<![\w.\-])(?:(?P<remote>data\.(?P<kind>tfe_outputs|terraform_remote_state)\.(?P<state>[\w-]+)(?:\[(?P<index>[^\]]*)\])?"
        rf"\.(?:nonsensitive_values|values|outputs)\.(?P<out>\w+)(?P<outpath>{PATH})"
        rf"|(?P<lookup>data\.(?P<ds_type>{data})\.(?P<ds>[\w-]+))(?:\[(?P<ds_index>[^\]]*)\])?(?P<dspath>{PATH}))"
        rf"|(?P<head>var|local|module|{heads})\.(?P<second>[\w-]+)(?P<path>{PATH}))"
    )


@dataclass
class _Budget:
    left: int = MAX_READS


@dataclass
class _Walk:
    """One `sources` call: the pattern it follows, the (instance, reference, path) it has read, and what each lookup
    reads (`_looked_up`), shared so a lookup that many paths reach is followed once."""

    pattern: re.Pattern[str]
    seen: set = field(default_factory=set)
    active: set = field(default_factory=set)  # the variables, locals, module outputs and lookups being followed
    lookups: dict[tuple, tuple[tuple[Ref, ...], Ref | None] | None] = field(default_factory=dict)
    budget: _Budget = field(default_factory=_Budget)  # shared by every `read`: a walk that fans out stops, never hangs

    def read(self, inst: Inst, value: Any) -> dict[Ref, None]:
        """What `value` points at, with a fresh `seen` and the lookups and budget this walk shares."""
        return _follow(inst, value, (), _Walk(self.pattern, active=self.active, lookups=self.lookups, budget=self.budget))


def sources(inst: Inst, obj: Any, pattern: re.Pattern[str]) -> dict[Ref, None]:
    """Resources and remote references `obj` points at, followed through locals, module variables and outputs. An
    attribute path (`var.base.networking.vpc_id`) reads only its part of an object literal, across every hop."""
    return _follow(inst, obj, (), _Walk(pattern))


def _follow(inst: Inst, obj: Any, unread: tuple[str | None, ...], walk: _Walk) -> dict[Ref, None]:
    """`sources`, where `unread` is the attribute path a reference that is all of `obj` still has to read."""
    text = obj if isinstance(obj, str) else str(obj)
    out: dict[Ref, None] = {}
    for m in walk.pattern.finditer(text):
        own = m["path"] or m["outpath"] or m["dspath"] or ""
        if m["head"] not in (None, "var", "local"):
            own = INSTANCE.sub("", own)  # `module.net[0].x`, `aws_subnet.a[0].vpc_id`: every instance has the same shape
        rest = unread
        if unread and (member := MEMBER.search(text[:m.start()])):  # `merge({vpc_id = x, subnet_ids = y}).vpc_id`
            if unread[0] is not None and unread[0] != unq(member[1]):
                continue  # reads `x` only
            rest = unread[1:]
        path = (*segments(own), *rest)  # `merge(local.a, local.b).vpc_id` reads `vpc_id` of each
        if len(path) > MAX_PATH or (key := (id(inst), m[0], path)) in walk.seen or walk.budget.left <= 0:
            continue
        walk.seen.add(key)
        walk.budget.left -= 1
        head, second = m["head"], m["second"]
        if m["kind"]:
            out[Ref(f"{inst.prefix}{m['remote']}", _render(m["out"], path),
                    state_of(inst, m["kind"], m["state"], m["index"]), _tier((m["out"], *path)))] = None
        elif m["ds"] and path and path[0] in TAGS:
            out |= _read_through(inst, inst.mod.data.get((m["ds_type"], m["ds"])), path, walk)
        elif m["ds"]:
            within, picked = _looked_up(inst, m["ds"], m["ds_type"], walk)
            out[picked or _lookup(inst, m, within)] = None
        elif (hops := _hops(inst, head, second, path)) is not None:
            # a local that reads itself reads nothing more; each module output is its own hop, as Terraform orders them
            hop = (id(inst), head, second, path[0] if head == "module" else None)
            if hop not in walk.active and len(walk.active) < MAX_HOPS:
                walk.active.add(hop)
                for where, value, rest in hops:
                    out |= _follow(where, value, rest, walk)
                walk.active.discard(hop)
        elif resource := inst.mod.resources.get((head, second)):
            if path and path[0] in READ_THROUGH:
                out |= _read_through(inst, resource, path, walk)
            else:
                out[Ref(f"{inst.prefix}{head}.{second}")] = None
    return out


def _read_through(inst: Inst, block: Any, path: tuple[str | None, ...], walk: _Walk) -> dict[Ref, None]:
    """What the argument `path[0]` of a resource or lookup block is written as, read along the rest of the path: only
    its part of an object literal (`tags.peer_vpc_id` reads that one tag)."""
    value = norm_keys(block.body).get(path[0], "") if block else ""
    out: dict[Ref, None] = {}
    for part, rest in _dig(value, path[1:]):
        out |= _follow(inst, part, rest, walk)
    return out


def _hops(inst: Inst, head: str, second: str, path: tuple[str | None, ...]) -> list[tuple[Inst, Any, tuple]] | None:
    """Where a variable, local or module output that `inst` reads is defined: each (instance, value, the path still
    to read there); None when `head.second` is none of these."""
    if head == "var" and inst.parent is not None:
        return [(inst.parent, *part) for args in inst.args if second in args for part in _dig(args[second], path)]
    if head == "local" and second in inst.mod.locals:
        return [(inst, *part) for part in _dig(inst.mod.locals[second], path)]
    if head == "module" and second in inst.children and path and path[0] in (child := inst.children[second]).mod.outputs:
        return [(child, *part) for part in _dig(child.mod.outputs[path[0]], path[1:])]
    return None


def _looked_up(inst: Inst, name: str, ds_type: str, walk: _Walk) -> tuple[tuple[Ref, ...], Ref | None]:
    """What names the network of the lookup `data.<ds_type>.<name>` (`IN_NETWORK`), and the resource of this stack it
    picks, if any. Each lookup is followed once per walk, so every path that reaches it finds the same references; a
    lookup that reads itself reads nothing the second time."""
    visit = (id(inst), ds_type, name)
    if visit not in walk.lookups and len(walk.active) < MAX_HOPS:
        walk.lookups[visit] = None
        walk.active.add(visit)
        block = inst.mod.data.get((ds_type, name))
        body = norm_keys(block.body) if block else {}
        walk.lookups[visit] = (tuple(walk.read(inst, list(_selected(body, IN_NETWORK)))), _picked(inst, body, ds_type, walk))
        walk.active.discard(visit)
    return walk.lookups.get(visit) or ((), None)


def _picked(inst: Inst, body: dict, ds_type: str, walk: _Walk) -> Ref | None:
    """The resource of this stack a lookup picks: every `PICKS` selector it sets is one whole reference (`id =
    aws_vpc.main.id`, never `"${aws_vpc.main.tags.Name}-peer"`), they all read the same one resource of the looked-up
    type, and that resource uses the same provider and the same `AGREE` arguments. A tag or a name filter picks
    nothing: a peer or DR network is often found by the tags of a local one."""
    picks = list(_selected(body, PICKS.get(ds_type, ())))
    if not picks or not all(_whole(v, walk.pattern) for v in picks):
        return None
    kind = ds_type.removesuffix("s")
    found = set.intersection(*({r for r in walk.read(inst, v) if not r.remote and r.address.split(".")[-2] == kind}
                               for v in picks))
    if len(found) != 1:
        return None
    ref = found.pop()
    owner, resource = next(((i, i.mod.resources[key]) for i in _root(inst).walk()
                            if (key := tuple(ref.address.removeprefix(i.prefix).split("."))) in i.mod.resources
                            and ref.address.startswith(i.prefix)), (None, None))
    if owner is None:
        return None
    other = norm_keys(resource.body)
    provider = _provider(inst, body, kind)  # key "": the calls of one instance give it different providers
    same = provider[1] != "" and provider == _provider(owner, other, kind) and all(
        _agree(inst, body.get(arg), owner, other.get(arg)) for arg in AGREE.get(ds_type, ()))
    return ref if same else None


def _selected(body: dict, names: tuple[str, ...]) -> Iterator[Any]:
    """The values of the arguments and `filter` blocks of a lookup that `names` names, each list item on its own."""
    found = [body[n] for n in names if n in body]
    found += [f.get("values") for f in blocks(body.get("filter")) if unq(str(f.get("name", ""))) in names]
    for value in found:
        yield from value if isinstance(value, list) else [value]


def _whole(value: Any, pattern: re.Pattern[str]) -> bool:
    """True when `value` is one reference and nothing else: `${aws_vpc.main.id}`, `"${local.vpc_id}"`."""
    expr = bare(value)
    return bool((m := pattern.match(expr)) and re.fullmatch(PATH, expr[m.end():]))


def _root(inst: Inst) -> Inst:
    while inst.parent is not None:
        inst = inst.parent
    return inst


def _provider(inst: Inst, body: dict, kind: str) -> tuple[int | None, str]:
    """The provider a block uses: the instance that declares it and its key there."""
    owner, key = declared_provider(inst, bare(body.get("provider", kind.split("_")[0])))
    return id(owner) if owner else None, key


def _agree(inst: Inst, value: Any, owner: Inst, other: Any) -> bool:
    """True when two arguments, each as it is written (`_written`), give the same literal, or are the same expression
    in one module instance."""
    value, other = _written(inst, value), _written(owner, other)
    literal = inst.value(value)
    if isinstance(literal, str):
        return literal == owner.value(other)
    return inst is owner and value is not None and value == other


def _written(inst: Inst, value: Any) -> Any:
    """What an argument is written as: a whole reference to an argument another resource of the module sets
    (`azurerm_virtual_network.main.resource_group_name`, `azurerm_resource_group.rg.name`) is that argument's value."""
    for _ in range(MAX_HOPS):
        m = RESOURCE_ARG.fullmatch(bare(value))
        resource = inst.mod.resources.get((m[1], m[2])) if m else None
        body = norm_keys(resource.body) if resource else {}
        if not m or m[3] not in body:
            break
        value = body[m[3]]
    return value


def _lookup(inst: Inst, m: re.Match[str], within: tuple[Ref, ...]) -> Ref:
    """What a lookup that selects no resource of its own type in this stack reads: an external network, one for
    each literal index of a `count` or `for_each` lookup, or a subnet `within` the resources its selectors read."""
    index = LITERAL_INDEX.fullmatch(m["ds_index"] or "")
    key = (Key(index[0].strip('"')),) if index else ()
    suffix = f"[{index[0]}]" if index else ""
    return Ref(f"{inst.prefix}{m['lookup']}{suffix}", _render(m["ds"], key), tier=_tier((m["ds"], *key)),
               within=within, looks_up=m["ds_type"])


def _tier(path: tuple[str | None, ...]) -> str | None:
    """The tier the end of a path gives: its last key in brackets when that key names a tier (`subnets["private"]`),
    else its last name (`private_subnet_ids["eu-west-1a"]`). No other key or name sets the tier (`vpcs["private-net"]
    ["subnet_ids"]` gives none); an index and an identifier attribute (`.id`) are skipped."""
    words = [p for p in path if p is not None and not p.isdecimal() and not IDENTIFIER.fullmatch(p)]
    if words and isinstance(words[-1], Key) and (tier := tier_in(words[-1])):
        return tier
    return tier_in(next((p for p in reversed(words) if not isinstance(p, Key)), ""))


def _dig(value: Any, path: tuple[str | None, ...]) -> list[tuple[Any, tuple[str | None, ...]]]:
    """The parts of an object or list literal a path reads, each with the rest of the path where the literal ends. A
    key or index the literal does not have reads nothing; an index that is no literal reads the rest of the path
    from every element (`local.nets[each.key].private_subnet_id`)."""
    for i, attr in enumerate(path):
        if attr is None and isinstance(value, (list, dict)):
            return [part for v in (value if isinstance(value, list) else value.values()) for part in _dig(v, path[i + 1:])]
        if attr is not None and isinstance(value, list) and attr.isdecimal():
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


def place_remote(networks: dict[str, dict], ref: Ref, why: dict[str, list[str]], address: str) -> tuple[str, str, str] | None:
    """(network key, tier, what decided the tier) for a subnet another stack or a lookup gives to the resource at
    `address`. A lookup `within` a network this stack knows is in that network; otherwise `_candidates` rank the
    networks. When no network fits, two fit equally well, or the subnet name gives no tier, the result is None and
    `why` gets the reason for `address`."""
    via = ref.name or ""
    candidates = {k: () for r in ref.within if (k := r.key()) in networks} or _candidates(networks, ref)
    ranked = sorted(candidates, key=candidates.__getitem__, reverse=True)
    if not ranked:
        reason = f"{via} fits no network this stack knows"
    elif len(ranked) > 1 and candidates[ranked[0]] == candidates[ranked[1]]:
        reason = f"{via} fits networks {' and '.join(sorted(networks[k]['address'] for k in ranked[:2]))} equally well"
    elif not ref.tier:
        reason = f"{via} is in {networks[ranked[0]]['address']}, its name gives no subnet tier"
    else:
        return ranked[0], ref.tier, via
    why.setdefault(address, []).append(reason)
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
    words of a part whose other words are all about subnets (`shared-vpc` of `shared-vpc-private-subnet`, `vpc` of
    `vpc-subnets`, but not `blue` of `blue-east` or `blue-vpc` of `blue-vpc-east-private-subnet`)."""
    last = len(network) - 1
    if len(network) > len(subnet) or network[:last] != subnet[:last]:
        return False
    head, part = network[last], subnet[last]
    return part == head or (part.startswith(head + "-") and set(part[len(head) + 1:].split("-")) <= set(SUBNET_WORDS))


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


def unplaced(why: dict[str, list[str]]) -> dict[str, str]:
    """Why each resource has a subnet that could not be placed, every reason once: it is marked, also when another
    of its subnets is placed."""
    return {address: "; ".join(dict.fromkeys(reasons)) for address, reasons in why.items()}


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
    """The tier word nearest the end of a name, outside interpolations: a subnet's own tier follows its network's
    (`private_vpc_public_subnet` is public), and `private-${var.public_zone}` is private."""
    words = TIER_WORD.findall(INTERPOLATION.sub("", name).lower())
    return words[-1] if words else None
