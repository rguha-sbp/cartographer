"""Reference following shared by the clouds' network facts: which subnets, networks and remote states a value points at.
Only `.tf` text is read: a remote state is compared by what its data block says, never opened."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cartographer.tf_modules import SINGLE, declared_provider
from cartographer.tf_policies import norm_keys, unq
from cartographer.tf_values import UNRESOLVED

TIERS = ("isolated", "private", "public")
CIDR = re.compile(r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}")

if TYPE_CHECKING:
    from cartographer.tf_modules import Inst, Res


@dataclass(frozen=True)
class State:
    """The state a remote state data source names, as its `.tf` text writes it: never read, only compared. `settings`
    are the literal (path, value) pairs that select it; `index` is the literal index of a `count` or `for_each` one."""

    kind: str
    settings: tuple[tuple[str, str], ...]
    index: str | None


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

    @property
    def remote(self) -> bool:
        return self.name is not None

    def key(self) -> str:
        """The key of the network this reference is or reads: a remote output's state and network name, so modules
        that read one network of one state share it; a resource's or lookup's address."""
        return remote_key(self.state, network_name(self.name or "")) if self.state is not None else self.address


def remote_key(state: State | str, name: str) -> str:
    return f"{name}@{state!r}"


def _render(name: str, path: tuple[str | None, ...]) -> str:
    """A name and the path read after it: a list index in brackets, an index that is no literal as `[*]`, an
    attribute or object key after a dot (`vpcs["blue"].id` -> `vpcs.blue.id`)."""
    return name + "".join("[*]" if p is None else f"[{p}]" if p.isdigit() else f".{p}" for p in path)


PATH = r"(?:\.[\w-]+|\[[^\]]*\])*"  # the attributes and indexes after a reference: `.vpc`, `["blue"]`, `[0]`
SEGMENT = re.compile(r'\.([\w-]+)|\[\s*(?:"([^"]*)"|(\d+)|([^\]]*))\s*\]')


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
    whole = pattern.fullmatch(_bare(text))
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
            same = {r: None for r in found if r.address.split(".")[-2] == m["ds_type"]}
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
    (`id = aws_vpc.main.id`). One of type `ds_type` is what the lookup finds, so it is no external network; another
    one holds what it finds (the VPC of a subnet). Each lookup follows its selectors with its own copy of `seen`, so
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
               within=within)


def _tier(path: tuple[str | None, ...]) -> str | None:
    """The tier the last name of a path gives; a key or object name before it never sets the tier. A list index, a
    non-literal index and an identifier attribute (`.id`) are no name."""
    return tier_in(next((p for p in reversed(path) if p is not None and not p.isdigit() and p not in IDENTIFIERS), ""))


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


INSTANCE = re.compile(r"^(?:\[[^\]]*\])+")  # the index of a module call with `count` or `for_each`
MODULE_PREFIX = re.compile(r'(?:module\.[\w-]+(?:\[(?:"[^"]*"|[^\]"]*)\])?\.)*')  # `module.a["k"].module.b.`
SELECTORS = ("id", "name", "filter", "tags")  # the arguments by which a lookup selects its network or subnet
MAX_PATH = 16  # longer attribute paths only come from a local or variable that reads itself
SELECTING = ("backend", "workspace", "organization")
TFE_HOST = "app.terraform.io"  # the `tfe` provider's default hostname
IDENTIFIERS = ("id", "ids", "arn", "name")  # attributes that read a resource, not a part of it
LITERAL_INDEX = re.compile(r'"[^"]*"|\d+')
INDEX = re.compile(r"\[[^\]]*\]")
PART = re.compile(r"\[[^\]]*\]|[^.\[]+")  # the words and indexes of a `_render`ed name
IDENTIFYING = re.compile(r"(?:^|_)(?:ids?|name|arn)$")  # an attribute that identifies a resource: `vpc_id`, `name`


def _bare(text: Any) -> str:
    """An expression without its quotes and its one `${...}`: `"${aws_vpc.main.id}"` -> `aws_vpc.main.id`."""
    return unq(text if isinstance(text, str) else str(text)).removeprefix("${").removesuffix("}")


def state_of(inst: Inst, kind: str, name: str, index: str | None) -> State | str:
    """The `State` the data source `kind`.`name` names, read from its `.tf` block with `Inst.value(agree=True)`. Its
    full address instead when the block is not found, selects nothing, or any setting or the index is no literal."""
    address = f"{inst.prefix}data.{kind}.{name}" + (f"[{index}]" if index is not None else "")
    body, config = _remote_state(inst, kind, name)
    if config is None:
        return address
    written = [(k, body[k]) for k in SELECTING if k in body] + _leaves("config", config)
    settings = {path: inst.value(v, agree=True) for path, v in written}
    if kind == "tfe_outputs" and settings:
        settings = _tfe_defaults(inst, body) | settings
    literal = LITERAL_INDEX.fullmatch(index) if index is not None else None
    if not settings or any(not isinstance(v, str) for v in settings.values()) or (index is not None and not literal):
        return address
    if kind == "terraform_remote_state":
        kind, settings = _as_workspace(settings)
    return State(kind, tuple(sorted(settings.items())), literal[0].strip('"') if literal else None)


def _tfe_defaults(inst: Inst, body: dict) -> dict[str, Any]:
    """The `hostname` and any `organization` of the `tfe` provider a `tfe_outputs` block uses (its `provider`
    meta-argument, through the module calls' `providers` maps): two hosts or two organizations can each hold a
    workspace of one name. A setting with no literal is UNRESOLVED."""
    owner, key = declared_provider(inst, _bare(body.get("provider", "tfe")))
    if owner is None or not key:
        return {"hostname": TFE_HOST if key == "tfe" else UNRESOLVED}  # the implicit default provider of the root
    provider = owner.mod.providers[key]
    host = owner.value(provider.get("hostname"), agree=True)
    org = {"organization": owner.value(provider["organization"], agree=True)} if "organization" in provider else {}
    return {"hostname": TFE_HOST if host is None else host, **org}


def _as_workspace(settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """A `terraform_remote_state` read: the `remote` backend of one named workspace is the workspace a `tfe_outputs`
    block reads, so both get the same identity. Any other read keeps its settings, without the default workspace."""
    settings = {k: v for k, v in settings.items() if (k, v) != ("workspace", "default")}
    remote = {"backend": "remote", "config.organization": settings.get("config.organization"),
              "config.workspaces.name": settings.get("config.workspaces.name")}
    if remote.items() <= settings.items() and set(settings) <= {*remote, "config.hostname"}:
        return "tfe_outputs", {"hostname": settings.get("config.hostname", TFE_HOST),
                               "organization": settings["config.organization"],
                               "workspace": settings["config.workspaces.name"]}
    return "terraform_remote_state", settings


def _leaves(path: str, value: Any) -> list[tuple[str, Any]]:
    """The (dotted path, expression) of every leaf of a `config` object."""
    if isinstance(value, dict):
        return [leaf for k, v in value.items() for leaf in _leaves(f"{path}.{k}", v)]
    return [(path, value)]


def _remote_state(inst: Inst, kind: str, name: str) -> tuple[dict, dict | None]:
    """The body of the data source `kind`.`name` and its `config` object, written in place or as one `local.`: empty
    when the block has none, None when it has one that is no object literal (`var.x`, `merge(...)`)."""
    block = inst.mod.data.get((kind, name))
    body = norm_keys(block.body) if block else {}
    if "config" not in body:
        return body, {}
    config = body["config"]
    if isinstance(config, str) and (m := SINGLE.fullmatch(unq(config))) and m[1] == "local":
        config = norm_keys(inst.mod.locals.get(m[2]))
    return body, config if isinstance(config, dict) else None


def network_fact(name: str, cidrs: list[str], ref: Ref, res: Res) -> dict:
    """A network fact for the network `ref` is or reads, cited at `res`."""
    return {"address": ref.address, "name": name, "cidrs": cidrs, "remote": ref.remote, "file": res.block.file,
            "line": res.block.line}


def add_remote(networks: dict[str, dict], ref: Ref, res: Res) -> None:
    """Record the network a remote reference reads, once per `Ref.key`."""
    networks.setdefault(ref.key(), network_fact(network_name(ref.name or ""), [], ref, res))


def place_remote(networks: dict[str, dict], ref: Ref) -> tuple[str, str, str] | None:
    """(network key, tier, what decided the tier) for a subnet another stack or a lookup gives, None when either is
    unknown or two networks fit it equally well. A lookup `within` a network of this stack is in that network.
    Otherwise the network is a remote one whose name without indexes is the subnet's or starts it (`shared-vpc`
    for `shared_vpc_private_subnet_ids[0]`), with the subnet's indexes or none. A remote output's subnet goes to a
    network of its own state or a lookup, never to one of another state. Among the candidates, a network of its own
    state wins, then one with the subnet's indexes, then the longest name, then for a lookup one its own module
    looks up."""
    if not ref.tier:
        return None
    via = ref.name or ""
    if ref.within:
        inside = [key for key in ref.within if key in networks]
        return (inside[0], ref.tier, via) if len(inside) == 1 else None
    stem, indexes = _stem(network_name(via))

    def fits(key: str, n: dict) -> bool:
        own, own_indexes = _stem(n["name"])
        return (n["remote"] and (stem == own or stem.startswith(own + "-")) and own_indexes in ((), indexes)
                and (ref.state is None or key in (n["address"], remote_key(ref.state, n["name"]))))

    def rank(key: str) -> tuple[bool, bool, int, bool]:
        n = networks[key]
        own, own_indexes = _stem(n["name"])
        own_state = ref.state is not None and key == remote_key(ref.state, n["name"])
        same_module = ref.state is None and key == n["address"] and _module(key) == _module(ref.address)  # both lookups
        return own_state, own_indexes == indexes, len(own), same_module

    ranked = sorted((key for key, n in networks.items() if fits(key, n)), key=rank, reverse=True)
    if not ranked or (len(ranked) > 1 and rank(ranked[0]) == rank(ranked[1])):
        return None
    return ranked[0], ref.tier, via


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


def blocks(value: Any) -> list[dict]:
    """The nested blocks of an attribute; one set as an expression (`subnet = var.x`) has none that can be read."""
    return [b for b in (value if isinstance(value, list) else [value]) if isinstance(b, dict)]


def network_name(name: str) -> str:
    """The network a remote output or lookup and the path it reads name: each word `derive`d, joined by `-`, each
    index kept in brackets (`shared_vpc_ids[0]` -> `shared-vpc[0]`). A last attribute that identifies what the
    path reads is no part of it (`network.vpc_id` -> `network`, `vpcs.blue.public_subnet_ids` -> `vpcs-blue`)."""
    parts = PART.findall(name)
    if len(parts) > 1 and IDENTIFYING.search(parts[-1]):
        parts = parts[:-1]
    return "".join(p if p.startswith("[") else f"-{derive(p)}" for p in parts).removeprefix("-")


def derive(name: str) -> str:
    """The network name a remote output or data source name implies: `shared_vpc_id` -> `shared-vpc`,
    `hub_vnet_name` -> `hub-vnet`."""
    return re.sub(r"_(ids?|name)$", "", name).replace("_", "-")


def tier_in(name: str) -> str | None:
    return next((t for t in TIERS if t in name.lower()), None)
