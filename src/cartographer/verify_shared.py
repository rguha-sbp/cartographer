"""What the Terraform and the description verification share: structure checks, code citations and the report."""

from pathlib import Path

from cartographer.diagram_model import AWS_ICONS, BRAND_ICONS, GENERIC_ICONS
from cartographer.secret_patterns import contains_secret
from cartographer.tf_blocks import empty_blocks

CODE_WINDOW = 3
SECRET_REASON = "looks like a secret"
SHAPES = (*GENERIC_ICONS, *BRAND_ICONS, "none")
UNKNOWN_TARGET = "unknown node, external or edge"


def code_hit(repo_root: Path, ev: dict) -> str | None:
    """None when the citation checks out, else the reason it does not."""
    path = repo_root / ev["file"]
    if not path.is_file():
        return f"file not found: {ev['file']}"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = max(ev["line"] - 1 - CODE_WINDOW, 0), ev["line"] + CODE_WINDOW
    if any(ev["contains"] in line for line in lines[lo:hi]):
        return None
    return f"{ev['file']}:{ev['line']} does not contain {ev['contains']!r}"


def claim_id(seen: set[str], item_id: str) -> str | None:
    """Reserve an id for a node or external; the reason when it is taken."""
    if item_id in seen:
        return "duplicate id"
    seen.add(item_id)
    return None


def shape_warnings(item: dict) -> list[str]:
    out = []
    if item.get("service", "other") not in (*AWS_ICONS, "other"):
        out.append(f"{item['id']}: service {item['service']!r} is not a draw.io AWS icon, renders as a box")
    if item.get("icon", "none") not in SHAPES:
        out.append(f"{item['id']}: icon {item['icon']!r} is not a draw.io generic or brand shape, renders as a box")
    return out


def edge_name(edge: dict) -> str:
    return f"{edge['src']}->{edge['dst']}"


def check_assumptions(curated: dict, node_ids: set[str], edges: list[dict]) -> tuple[list[dict], list[str]]:
    """Keep the assumptions that name a kept node, external or edge and hold no secret."""
    targets = node_ids | {edge_name(e) for e in edges}
    kept, dropped = [], []
    for a in curated.get("assumptions", []):
        if contains_secret(a):
            dropped.append(f"{a['about']}: {SECRET_REASON}")
        elif a["about"] not in targets:
            dropped.append(f"{a['about']}: {UNKNOWN_TARGET}")
        else:
            kept.append(a)
    return kept, dropped


def fix_groups(curated: dict, notes: list[str]) -> None:
    ids = {g["id"] for g in curated["groups"]}
    for g in curated["groups"]:
        if g["parent"] is not None and g["parent"] not in ids:
            notes.append(f"group {g['id']}: unknown parent {g['parent']}, moved to top level")
            g["parent"] = None
    for item in curated["nodes"]:
        if item["group"] is not None and item["group"] not in ids:
            notes.append(f"{item['id']}: unknown group {item['group']}, ungrouped")
            item["group"] = None
    notes += [f"group {gid}: no nodes, the layout drops it" for gid in empty_blocks(curated)]


def isolated_ids(diagram: dict) -> list[str]:
    linked = {end for e in diagram["edges"] for end in (e["src"], e["dst"])}
    return sorted(i["id"] for i in (*diagram["nodes"], *diagram["externals"]) if i["id"] not in linked)


def needs_attention(curated: dict, verified: dict) -> bool:
    """True when verify dropped a node, external, edge or assumption, or left a node without a line."""
    dropped = sum(len(curated.get(k, [])) - len(verified.get(k, [])) for k in ("nodes", "externals", "edges", "assumptions"))
    return bool(dropped or isolated_ids(verified))


def render_report(summary: str, sections: list[tuple[str, list[str]]]) -> str:
    lines = [summary]
    for title, items in sections:
        lines += ["", f"{title} ({len(items)})"] + [f"  {i}" for i in sorted(items)]
    return "\n".join(lines) + "\n"
