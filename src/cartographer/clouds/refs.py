"""Reference following shared by the clouds' network facts: which subnets, networks and remote stacks a value points at."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

TIERS = ("isolated", "private", "public")
CIDR = re.compile(r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}")

if TYPE_CHECKING:
    from cartographer.tf_modules import Inst


@dataclass(frozen=True)
class Ref:
    """A local resource (`name` None) or a reference to another stack (`name` is its output or data source name)."""

    address: str
    name: str | None = None

    @property
    def remote(self) -> bool:
        return self.name is not None


def token(heads: str, data: str) -> re.Pattern[str]:
    """A reference to a local resource whose type matches `heads`, a data source matching `data`, or a remote output."""
    return re.compile(
        r"(?<![\w.\-])(?:(?P<remote>data\.(?:tfe_outputs|terraform_remote_state)\.\w+"
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
            out[Ref(m["remote"], m["out"] or m["ds"])] = None
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


def derive(name: str) -> str:
    """The network name a remote output or data source name implies: `shared_vpc_id` -> `shared-vpc`."""
    return re.sub(r"_ids?$", "", name).replace("_", "-")


def tier_in(name: str) -> str | None:
    return next((t for t in TIERS if t in name.lower()), None)
