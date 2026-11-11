"""Reference following shared by the clouds' network facts: which subnets, networks and remote stacks a value points at."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cartographer.account_names import ENVIRONMENTS
from cartographer.tf_policies import norm_keys

TIERS = ("isolated", "private", "public")
CIDR = re.compile(r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}")

if TYPE_CHECKING:
    from cartographer.tf_modules import Inst, Res


@dataclass(frozen=True)
class Ref:
    """A local resource (`name` None) or a reference to another stack (`name` is its output or data source name).
    `stack` names the stack whose outputs it reads: the workspace its remote state data source names, else
    that data source's name (`networking` for `data.tfe_outputs.networking...`). A data source lookup has none, and
    its address carries the module that declares it: two modules can look up different networks under one name."""

    address: str
    name: str | None = None
    stack: str | None = None

    @property
    def remote(self) -> bool:
        return self.name is not None

    @property
    def key(self) -> str:
        """The key of the network this reference is or reads: modules that read one output of one stack share it, and
        the same data source name read against two workspaces gives two."""
        return f"{self.address}@{self.stack}" if self.stack else self.address


def token(heads: str, data: str) -> re.Pattern[str]:
    """A reference to a local resource whose type matches `heads`, a data source matching `data`, or a remote output."""
    return re.compile(
        r"(?<![\w.\-])(?:(?P<remote>data\.(?P<kind>tfe_outputs|terraform_remote_state)\.(?P<state>[\w-]+)"
        rf"\.(?:nonsensitive_values|values|outputs)\.(?P<out>\w+)|data\.(?:{data})\.(?P<ds>[\w-]+))"
        rf"|(?P<head>var|local|module|{heads})\.(?P<second>[\w-]+)(?:\[[^\]]*\])?(?:\.(?P<third>[\w-]+))?)"
    )


def sources(inst: Inst, obj: Any, pattern: re.Pattern[str], seen: set | None = None) -> dict[Ref, None]:
    """Resources and remote references `obj` points at, followed through locals and module variables."""
    seen = set() if seen is None else seen
    out: dict[Ref, None] = {}
    for m in pattern.finditer(obj if isinstance(obj, str) else str(obj)):
        if (key := (id(inst), m[0])) in seen:
            continue
        seen.add(key)
        head, second, third = m["head"], m["second"], m["third"]
        if m["kind"]:
            out[Ref(m["remote"], m["out"], stack(inst, m["kind"], m["state"]))] = None
        elif m["ds"]:
            out[Ref(f"{inst.prefix}{m['remote']}", m["ds"])] = None
        elif head == "var" and inst.parent is not None:
            for args in inst.args:
                if second in args:
                    out |= sources(inst.parent, args[second], pattern, seen)
        elif head == "local" and second in inst.mod.locals:
            out |= sources(inst, inst.mod.locals[second], pattern, seen)
        elif head == "module" and second in inst.children and third in inst.children[second].mod.outputs:
            child = inst.children[second]
            out |= sources(child, child.mod.outputs[third], pattern, seen)
        elif (head, second) in inst.mod.resources:
            out[Ref(f"{inst.prefix}{head}.{second}")] = None
    return out


STATE_FILE = re.compile(r"/*(((^|[/._-])terraform)?\.tfstate)?$")  # the file of a state path, and the `/` before it


def stack(inst: Inst, kind: str, name: str) -> str:
    """The workspace or state the remote state data source `kind`.`name` reads, else `name`. Its body names it as a
    literal, directly or through `var.` and `local.`. The first of these that leaves a name with a word that is not an environment counts, less its
    `terraform.tfstate` file or `.tfstate` suffix and any leading `./` or `../`: `config.workspaces.name`, `config.key`,
    `config.workspace_key_prefix`, `config.path`, `config.prefix`, then the `workspace` of `tfe_outputs` (that of
    `terraform_remote_state` is an environment, not a stack)."""
    block = inst.mod.data.get((kind, name))
    body = norm_keys(block.body) if block else {}
    config = body["config"] if isinstance(body.get("config"), dict) else {}
    workspaces = config["workspaces"] if isinstance(config.get("workspaces"), dict) else {}
    named = [workspaces.get("name"), *(config.get(k) for k in ("key", "workspace_key_prefix", "path", "prefix")),
             body.get("workspace") if kind == "tfe_outputs" else None]
    for found in map(inst.value, named):
        state = STATE_FILE.sub("", re.sub(r"^(\.\.?/)+", "", found)) if isinstance(found, str) else ""
        if set(re.findall(r"[a-z0-9]+", state.lower())) - ENVIRONMENTS:  # `prod/terraform.tfstate` names no stack
            return state
    return name


def network_fact(name: str, cidrs: list[str], ref: Ref, res: Res) -> dict:
    """A network fact for the network `ref` is or reads, cited at `res`."""
    return {"address": ref.address, "name": name, "cidrs": cidrs, "remote": ref.remote, "stack": ref.stack,
            "file": res.block.file, "line": res.block.line}


def add_remote(networks: dict[str, dict], ref: Ref, res: Res, suffixes: str = "ids?") -> None:
    """Record the network a remote reference reads, once per `Ref.key`."""
    if ref.key not in networks:
        networks[ref.key] = network_fact(derive(ref.name or "", suffixes), [], ref, res)


def place_remote(networks: dict[str, dict], ref: Ref, suffixes: str = "ids?") -> tuple[str, str, str] | None:
    """(network key, tier, what decided the tier) for a subnet another stack or a lookup gives, None when either
    is unknown. The network is a remote one whose name prefixes the output name (`shared-vpc` for
    `shared_vpc_private_subnet_ids`): one of the reference's own stack before any other, then the longest name, then
    for a lookup a network its own module looks up, then a network of another stack before a lookup."""
    name, tier = derive(ref.name or "", suffixes), tier_in(ref.name or "")

    def rank(key: str) -> tuple[bool, int, bool, bool, str]:
        n = networks[key]
        same_stack = ref.stack is not None and n["stack"] == ref.stack
        same_module = ref.stack is None and n["stack"] is None and _module(key) == _module(ref.address)  # both lookups
        return same_stack, len(n["name"]), same_module, n["stack"] is not None, key

    named = [key for key, n in networks.items() if n["remote"] and name.startswith(n["name"] + "-")]
    return (max(named, key=rank), tier, ref.name or "") if named and tier else None


def _module(address: str) -> str:
    """The module path a data source address starts with: `module.a.` for `module.a.data.aws_vpc.main`."""
    return address.rpartition("data.")[0]


def placement_facts(found: dict[tuple[str, str, str], tuple[str, Res, str | None]]) -> list[dict]:
    """The placement facts of (resource, network, tier) -> (what decided the tier, the resource, the stack of a
    remote subnet output)."""
    return [{"resource": address, "network": network, "tier": tier, "via": via, "stack": stack, "file": r.block.file,
             "line": r.block.line} for (address, network, tier), (via, r, stack) in sorted(found.items())]


def blocks(value: Any) -> list[dict]:
    """The nested blocks of an attribute; one set as an expression (`subnet = var.x`) has none that can be read."""
    return [b for b in (value if isinstance(value, list) else [value]) if isinstance(b, dict)]


def derive(name: str, suffixes: str = "ids?") -> str:
    """The network name a remote output or data source name implies: `shared_vpc_id` -> `shared-vpc`."""
    return re.sub(rf"_({suffixes})$", "", name).replace("_", "-")


def tier_in(name: str) -> str | None:
    return next((t for t in TIERS if t in name.lower()), None)
