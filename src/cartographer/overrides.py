"""The repo's icon overrides (`icons.json` beside the diagrams): load them, then apply them to a verified diagram."""

import json
from dataclasses import dataclass
from pathlib import Path

from cartographer import icons

FIELDS = ("cloud", "type", "icon", "reason")


@dataclass(frozen=True)
class Override:
    cloud: str
    type: str
    icon: str
    reason: str
    address: str | None = None


def load(path: Path) -> tuple[list[Override], list[str]]:
    """The valid overrides of the file and a problem line for everything else; a missing file is no overrides."""
    if not path.is_file():
        return [], []
    try:
        entries = json.loads(path.read_text())["overrides"]
        if not isinstance(entries, list):
            raise TypeError("overrides is not a list")
    except (ValueError, KeyError, TypeError) as err:
        return [], [f"{path.name}: unreadable ({err})"]
    found, problems = [], []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not all(isinstance(entry.get(f), str) and entry[f] for f in FIELDS):
            problems.append(f"override {i}: needs non-empty {', '.join(FIELDS)}")
        else:
            found.append(Override(**{f: entry[f] for f in FIELDS}, address=entry.get("address")))
    return found, problems


def _refusal(o: Override, facts: dict | None) -> str | None:
    """A reason to refuse the override itself; None when it is valid, even if this diagram has nothing for it."""
    if not icons.known(f"{o.cloud}:{o.icon}"):
        return f"unknown icon {o.cloud}:{o.icon}"
    if facts is None:
        return "an address needs Terraform facts" if o.address else None
    resources = facts["resources"]
    if o.address and not any(r["address"] == o.address and r["type"] == o.type for r in resources):
        return f"{o.address} is not a {o.type} in the facts"
    return None


def _targets(items: list[dict], o: Override, types: dict[str, str] | None) -> list[dict]:
    if o.address:
        return [i for i in items if o.address in i.get("tf", [])]
    if types is None:
        return [i for i in items if i.get("tf_type") == o.type]
    return [i for i in items if any(types.get(a) == o.type for a in i.get("tf", []))]


def apply(verified: dict, facts: dict | None, overrides: list[Override]) -> list[str]:
    """Set icon, override reason and decided_by on the nodes and externals each override names; an address beats a
    type. Returns one line per override: `refused`, `skipped` (not in this diagram) or `applied`."""
    items = [*verified["nodes"], *verified["externals"]]
    types = {r["address"]: r["type"] for r in facts["resources"]} if facts is not None else None
    lines = []
    ordered = sorted(overrides, key=lambda o: o.address is not None)
    for o in ordered:
        name = f"{o.type} {o.address}" if o.address else o.type
        if problem := _refusal(o, facts):
            lines.append(f"refused {name}: {problem}")
            continue
        hit = _targets(items, o, types)
        if facts is not None and not hit and not any(r["type"] == o.type for r in facts["resources"]):
            lines.append(f"skipped {name}: not in this diagram")
            continue
        for item in hit:
            item.update(icon=f"{o.cloud}:{o.icon}", override=o.reason, decided_by="override")
        lines.append(f"applied {name} -> {o.cloud}:{o.icon} on {', '.join(i['id'] for i in hit) or 'no drawn node'}: "
                     f"{o.reason}")
    return lines
