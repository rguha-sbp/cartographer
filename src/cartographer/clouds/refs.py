"""Reference following shared by the clouds' network facts: which subnets, networks and remote states a value points at.
Only `.tf` text is read: a remote state is compared by what its data block says, never opened."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cartographer.tf_modules import declared_provider
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
    name: str | None = None  # a remote output's name, plus each index or attribute it reads (`vpcs["blue"]`: `vpcs_blue`)
    state: State | str | None = None
    tier: str | None = None  # the subnet tier the last name in the path gives (`vpcs["private-net"].public_subnet_ids`: public)

    @property
    def remote(self) -> bool:
        return self.name is not None

    def key(self) -> str:
        """The key of the network this reference is or reads: a remote output's state and network name, so modules
        that read one network of one state share it; a resource's or lookup's address."""
        return remote_key(self.state, derive(self.name or "")) if self.state is not None else self.address


def remote_key(state: State | str, name: str) -> str:
    return f"{name}@{state!r}"


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
    whole = pattern.fullmatch(unq(text).removeprefix("${").removesuffix("}"))
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
            name = "_".join([m["out"], *(s if s is not None else "any" for s in path)])
            out[Ref(f"{inst.prefix}{m['remote']}", name, state_of(inst, m["kind"], m["state"], m["index"]),
                    _tier((m["out"], *path)))] = None
        elif m["ds"]:
            out |= _looked_up(inst, m["ds_type"], m["ds"], pattern, seen) or {_lookup(inst, m): None}
        elif head == "var" and inst.parent is not None:
            for args in inst.args:
                if second in args:
                    out |= _follow(inst.parent, *_dig(args[second], path), pattern, seen)
        elif head == "local" and second in inst.mod.locals:
            out |= _follow(inst, *_dig(inst.mod.locals[second], path), pattern, seen)
        elif head == "module" and second in inst.children and path and path[0] in inst.children[second].mod.outputs:
            child = inst.children[second]
            out |= _follow(child, *_dig(child.mod.outputs[path[0]], path[1:]), pattern, seen)
        elif (head, second) in inst.mod.resources:
            out[Ref(f"{inst.prefix}{head}.{second}")] = None
    return out


def _looked_up(inst: Inst, ds_type: str, name: str, pattern: re.Pattern[str], seen: set) -> dict[Ref, None]:
    """The resources of type `ds_type` this stack creates that the lookup `data.<ds_type>.<name>` selects through
    its `SELECTORS` (`id = aws_vpc.main.id`): the lookup finds that resource, so it is no external network. Each
    lookup follows its selectors with its own copy of `seen`, so a second read of it finds the same resources."""
    block, visit = inst.mod.data.get((ds_type, name)), (id(inst), ds_type, name)
    if block is None or visit in seen:
        return {}
    selectors = {k: v for k, v in norm_keys(block.body).items() if k in SELECTORS}
    found = _follow(inst, selectors, (), pattern, {*seen, visit})
    return {r: None for r in found if not r.remote and r.address.split(".")[-2] == ds_type}


def _lookup(inst: Inst, m: re.Match[str]) -> Ref:
    """The external network a lookup that selects no resource of this stack stands for: one for each literal index
    of a `count` or `for_each` lookup, named like a remote output that reads that index."""
    index = LITERAL_INDEX.fullmatch(m["ds_index"] or "")
    suffix = f"[{index[0]}]" if index else ""
    key = index[0].strip('"') if index else None
    return Ref(f"{inst.prefix}{m['lookup']}{suffix}", "_".join([m["ds"], key]) if key else m["ds"], tier=_tier((m["ds"], key)))


def _tier(path: tuple[str | None, ...]) -> str | None:
    """The tier the last name of a path gives; a key or object name before it never sets the tier, and a list index
    or a non-literal index is no name."""
    return tier_in(next((p for p in reversed(path) if p is not None and not p.isdigit()), ""))


def _dig(value: Any, path: tuple[str | None, ...]) -> tuple[Any, tuple[str | None, ...]]:
    """The part of an object or list literal a path reads, and the rest of the path where the literal ends. A key or
    index the literal does not have reads nothing; an index that is no literal reads all of the literal."""
    for i, attr in enumerate(path):
        if attr is None:
            return value, ()
        if isinstance(value, list) and attr.isdigit():
            value = value[int(attr)] if int(attr) < len(value) else ""
        elif isinstance(value, dict):
            value = next((v for k, v in value.items() if unq(k) == attr), "")
        else:
            return value, path[i:]
    return value, ()


INSTANCE = re.compile(r"^(?:\[[^\]]*\])+")  # the index of a module call with `count` or `for_each`
MODULE_PREFIX = re.compile(r'(?:module\.[\w-]+(?:\[(?:"[^"]*"|[^\]"]*)\])?\.)*')  # `module.a["k"].module.b.`
SELECTORS = ("id", "name", "filter", "tags")  # the arguments by which a lookup selects its network or subnet
MAX_PATH = 16  # longer attribute paths only come from a local or variable that reads itself
SELECTING = ("backend", "workspace", "organization")
TFE_HOST = "app.terraform.io"  # the `tfe` provider's default hostname
LITERAL_INDEX = re.compile(r'"[^"]*"|\d+')


def state_of(inst: Inst, kind: str, name: str, index: str | None) -> State | str:
    """The `State` the data source `kind`.`name` names, read from its `.tf` block with `Inst.agreed_value`. Its
    full address instead when the block is not found, selects nothing, or any setting or the index is no literal."""
    address = f"{inst.prefix}data.{kind}.{name}" + (f"[{index}]" if index is not None else "")
    body, config = _remote_state(inst, kind, name)
    if config is None:
        return address
    written = [(k, body[k]) for k in SELECTING if k in body] + _leaves("config", config)
    settings = [(path, inst.agreed_value(v)) for path, v in written]
    if kind == "tfe_outputs" and settings:
        settings.append(("hostname", _tfe_host(inst, body)))
    literal = LITERAL_INDEX.fullmatch(index) if index is not None else None
    if not settings or any(not isinstance(v, str) for _, v in settings) or (index is not None and not literal):
        return address
    if kind == "terraform_remote_state":
        settings = [(k, v) for k, v in settings if (k, v) != ("workspace", "default")]
    return State(kind, tuple(sorted(settings)), literal[0].strip('"') if literal else None)  # type: ignore[arg-type]


def _tfe_host(inst: Inst, body: dict) -> str | object:
    """The `hostname` of the `tfe` provider a `tfe_outputs` block uses (its `provider` meta-argument, through the
    module calls' `providers` maps): two hosts can each hold a workspace of one name. UNRESOLVED when no literal."""
    owner, key = declared_provider(inst, unq(body.get("provider", "tfe")).removeprefix("${").removesuffix("}"))
    if owner is None or not key:
        return TFE_HOST if key == "tfe" else UNRESOLVED  # the implicit default provider of the root
    host = owner.agreed_value(owner.mod.providers[key].get("hostname"))
    return TFE_HOST if host is None else host


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
    if isinstance(config, str) and (m := re.fullmatch(r"\$\{local\.([\w-]+)\}", unq(config))):
        config = norm_keys(inst.mod.locals.get(m[1]))
    return body, config if isinstance(config, dict) else None


def network_fact(name: str, cidrs: list[str], ref: Ref, res: Res) -> dict:
    """A network fact for the network `ref` is or reads, cited at `res`."""
    return {"address": ref.address, "name": name, "cidrs": cidrs, "remote": ref.remote, "file": res.block.file,
            "line": res.block.line}


def add_remote(networks: dict[str, dict], ref: Ref, res: Res) -> None:
    """Record the network a remote reference reads, once per `Ref.key`."""
    networks.setdefault(ref.key(), network_fact(derive(ref.name or ""), [], ref, res))


def place_remote(networks: dict[str, dict], ref: Ref) -> tuple[str, str, str] | None:
    """(network key, tier, what decided the tier) for a subnet another stack or a lookup gives, None when either
    is unknown. The network is a remote one whose name prefixes the output name (`shared-vpc` for
    `shared_vpc_private_subnet_ids`). A remote output's subnet goes to a network of its own state or a lookup,
    never to a network of another state; among the
    candidates, a network of its own state wins, then the longest name, then for a lookup one its own module looks
    up, then the key."""
    name, tier = derive(ref.name or ""), ref.tier

    def rank(key: str) -> tuple[bool, int, bool, str]:
        n = networks[key]
        own_state = ref.state is not None and key == remote_key(ref.state, n["name"])
        same_module = ref.state is None and key == n["address"] and _module(key) == _module(ref.address)  # both lookups
        return own_state, len(n["name"]), same_module, key

    named = [key for key, n in networks.items() if n["remote"] and name.startswith(n["name"] + "-")
             and (ref.state is None or key in (n["address"], remote_key(ref.state, n["name"])))]
    return (max(named, key=rank), tier, ref.name or "") if named and tier else None


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


def derive(name: str) -> str:
    """The network name a remote output or data source name implies: `shared_vpc_id` -> `shared-vpc`,
    `hub_vnet_name` -> `hub-vnet`."""
    return re.sub(r"_(ids?|name)$", "", name).replace("_", "-")


def tier_in(name: str) -> str | None:
    return next((t for t in TIERS if t in name.lower()), None)
