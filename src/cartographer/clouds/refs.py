"""Reference following shared by the clouds' network facts: which subnets, networks and remote stacks a value points at."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

TIERS = ("isolated", "private", "public")
CIDR = re.compile(r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}")
LITERAL = re.compile(r'"[\w./\-]+"')  # a quoted HCL string without interpolation

if TYPE_CHECKING:
    from cartographer.tf_modules import Inst, Res


@dataclass(frozen=True)
class Ref:
    """A local resource (`name` None) or a reference to another stack (`name` is its output or data source name).
    `stack` names the stack whose outputs it reads: the workspace its remote state data source names literally, else
    that data source's name (`networking` for `data.tfe_outputs.networking...`); a data source lookup has none."""

    address: str
    name: str | None = None
    stack: str | None = None

    @property
    def remote(self) -> bool:
        return self.name is not None


def token(heads: str, data: str) -> re.Pattern[str]:
    """A reference to a local resource whose type matches `heads`, a data source matching `data`, or a remote output."""
    return re.compile(
        r"(?<![\w.\-])(?:(?P<remote>data\.(?P<kind>tfe_outputs|terraform_remote_state)\.(?P<state>\w+)"
        rf"\.(?:nonsensitive_values|values|outputs)\.(?P<out>\w+)|data\.(?:{data})\.(?P<ds>\w+))"
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
        if m["remote"]:
            out[Ref(m["remote"], m["out"] or m["ds"], stack(inst, m["kind"], m["state"]) if m["kind"] else None)] = None
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


def stack(inst: Inst, kind: str, name: str) -> str:
    """The workspace or state the remote state data source `kind`.`name` reads when its body names it literally
    (`config.workspaces.name`, then `config.key` less its `terraform.tfstate` file or `.tfstate` suffix, then
    `workspace`), else `name`."""
    block = inst.mod.data.get((kind, name))
    body = block.body if block else {}
    config = body.get("config") if isinstance(body.get("config"), dict) else {}
    workspaces = config.get("workspaces") if isinstance(config.get("workspaces"), dict) else {}
    for named in (workspaces.get("name"), config.get("key"), body.get("workspace")):
        if isinstance(named, str) and LITERAL.fullmatch(named):
            return re.sub(r"[/.]?(terraform)?\.tfstate$", "", named.strip('"')) or name
    return name


def network_fact(name: str, cidrs: list[str], ref: Ref, res: Res) -> dict:
    """A network fact for the network `ref` is or reads, cited at `res`."""
    return {"address": ref.address, "name": name, "cidrs": cidrs, "remote": ref.remote, "stack": ref.stack,
            "file": res.block.file, "line": res.block.line}


def add_remote(networks: dict[str, dict], ref: Ref, res: Res, suffixes: str = "ids?") -> None:
    """Record the network a remote reference reads, once per address: every module that reads the output shares it,
    and the first reader's stack names it."""
    if ref.address not in networks:
        networks[ref.address] = network_fact(derive(ref.name or "", suffixes), [], ref, res)


def place_remote(networks: dict[str, dict], ref: Ref, suffixes: str = "ids?") -> tuple[str, str, str] | None:
    """(network address, tier, what decided the tier) for a subnet another stack or a lookup gives, None when either
    is unknown. The network is a remote one whose name prefixes the output name (`shared-vpc` for
    `shared_vpc_private_subnet_ids`): one of the reference's own stack before any other, then the longest name. A
    lookup has no stack, so the longest name alone decides."""
    name, tier = derive(ref.name or "", suffixes), tier_in(ref.name or "")
    named = [(ref.stack is not None and n["stack"] == ref.stack, len(n["name"]), a) for a, n in networks.items()
             if n["remote"] and name.startswith(n["name"] + "-")]
    return (max(named)[2], tier, ref.name or "") if named and tier else None


def blocks(value: Any) -> list[dict]:
    """The nested blocks of an attribute; one set as an expression (`subnet = var.x`) has none that can be read."""
    return [b for b in (value if isinstance(value, list) else [value]) if isinstance(b, dict)]


def derive(name: str, suffixes: str = "ids?") -> str:
    """The network name a remote output or data source name implies: `shared_vpc_id` -> `shared-vpc`."""
    return re.sub(rf"_({suffixes})$", "", name).replace("_", "-")


def tier_in(name: str) -> str | None:
    return next((t for t in TIERS if t in name.lower()), None)
