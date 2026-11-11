"""Check a curated diagram's network claims against the `networks` and `placements` facts."""

from collections import defaultdict
from pathlib import Path

from cartographer.verify_shared import (
    check_claims,
    code_hit,
    enclosing,
    outside_network,
)


def _problem(group: dict, ev: dict, facts_by_id: dict, networks: dict[str, dict], repo_root: Path) -> str | None:
    """Why `ev` is no evidence for `group`: a network group cites network facts, a subnet group placements of its tier."""
    if "stated" in ev:
        return "stated evidence is for described diagrams"
    if "file" in ev:
        return code_hit(repo_root, ev)
    fact = facts_by_id.get(ev["fact"])
    if fact is None:
        return f"unknown fact {ev['fact']}"
    if group["kind"] == "network":
        return None if ev["fact"] in networks else f"fact {ev['fact']} is not a network fact"
    if fact.get("tier") == group["tier"]:
        return None
    return f"fact {ev['fact']} is not a placement with tier {group['tier']}"


def _backs_cidrs(group: dict, good: list[dict], networks: dict[str, dict]) -> bool:
    """A code citation, or a cited network fact with exactly the group's cidrs."""
    return any("file" in ev or (cidrs := networks[ev["fact"]]["cidrs"]) and set(cidrs) == set(group["cidrs"])
               for ev in good)


def check_network(out: dict, facts: dict, facts_by_id: dict, repo_root: Path, notes: list[str]) -> None:
    """Keep cidrs and subnet tiers only when a fact or a code citation backs them, keep each node inside a subnet group
    only when it has a placement fact of that tier, and inside a network group only when it runs in a network the group
    cites; then mark the network groups that stand only for external networks."""

    networks = {n["id"]: n for n in facts.get("networks", [])}

    def supported(group: dict, evidence: list[dict]) -> tuple[list[dict], list[str]]:
        problems = [(ev, _problem(group, ev, facts_by_id, networks, repo_root)) for ev in evidence]
        return [ev for ev, p in problems if p is None], [p for _, p in problems if p]

    groups = {g["id"]: g for g in out["groups"]}
    check_claims(out, notes, supported, lambda group, good: _backs_cidrs(group, good, networks))
    placed: dict[str, list[dict]] = defaultdict(list)  # a resource -> its placements
    for p in facts.get("placements", []):
        placed[p["resource"]].append(p)
    for n in out["nodes"]:
        subnet = enclosing(groups, n["group"], "subnet")
        if subnet and not any(p["tier"] == subnet["tier"] for address in n["tf"] for p in placed[address]):
            notes.append(f"{n['id']}: no {subnet['tier']} placement fact, moved out of subnet group {subnet['id']}")
            n["group"] = outside_network(groups, subnet)
    check_boxes(out, networks, groups, placed, notes)


def check_boxes(out: dict, networks: dict[str, dict], groups: dict[str, dict], placed: dict[str, list[dict]],
                notes: list[str]) -> None:
    """A network group stands for the network facts its evidence cites. Move each placed node out of a network group
    that stands for none of the networks it runs in, note a placed node outside every network group and a group that
    cites no network, then mark `external` the groups that stand only for remote networks and still hold a node."""
    stands = {g["id"]: {ev["fact"] for ev in g.get("evidence", []) if ev.get("fact") in networks}
              for g in groups.values() if g["kind"] == "network"}
    notes += [f"group {gid}: cites no network fact, its nodes cannot be checked" for gid, cited in stands.items() if not cited]
    for n in out["nodes"]:
        runs_in = {p["network"] for address in n["tf"] for p in placed[address]}
        if not runs_in:
            continue
        names = ", ".join(sorted({networks[i]["name"] for i in runs_in if i in networks}))
        box = enclosing(groups, n["group"], "network")
        if box is None:
            notes.append(f"{n['id']}: placed in {names}, drawn outside any network group")
        elif stands[box["id"]] and not runs_in & stands[box["id"]]:
            notes.append(f"{n['id']}: placed in {names}, not in network group {box['id']}; moved out")
            n["group"] = outside_network(groups, box)
    holding = {box["id"] for n in out["nodes"] if (box := enclosing(groups, n["group"], "network"))}
    for gid, cited in stands.items():
        if cited and gid in holding and all(networks[i]["remote"] for i in cited):
            groups[gid]["external"] = True
