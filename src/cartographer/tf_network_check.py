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
    check_boxes(out, networks, groups, placed, notes)


def check_boxes(out: dict, networks: dict[str, dict], groups: dict[str, dict], placed: dict[str, list[dict]],
                notes: list[str]) -> None:
    """A network group stands for the network facts its evidence cites. Put each node where its placements say
    (`_place`), note a group that cites no network and one that cites more than one, then mark `external` the groups
    that stand only for remote networks and still hold a node."""
    stands = {g["id"]: {ev["fact"] for ev in g.get("evidence", []) if ev.get("fact") in networks}
              for g in groups.values() if g["kind"] == "network"}
    notes += [f"group {gid}: cites no network fact, its nodes cannot be checked" for gid, cited in stands.items() if not cited]
    notes += [f"group {gid}: cites {len(cited)} network facts ({', '.join(sorted(cited))}), draw one group per network "
              "unless they are one network" for gid, cited in stands.items() if len(cited) > 1]
    for n in out["nodes"]:
        _place(n, [p for address in n["tf"] for p in placed[address]], groups, stands, networks, notes)
    holding = {box["id"] for n in out["nodes"] if (box := enclosing(groups, n["group"], "network"))}
    for gid, cited in stands.items():
        if cited and gid in holding and all(networks[i]["remote"] for i in cited):
            groups[gid]["external"] = True


def _place(n: dict, runs: list[dict], groups: dict[str, dict], stands: dict[str, set[str]], networks: dict[str, dict],
           notes: list[str]) -> None:
    """Keep node `n` in a network group only when it runs in a network the group stands for, else move it to the one
    group that does, or out of the network when there is not exactly one; keep it in a subnet group only when it runs in
    that tier, else move it to a subnet group of a tier it runs in, or to the network group itself. A placed node
    outside every network group gets a note only; a node without placements is not checked against networks."""
    runs_in = {p["network"] for p in runs}
    names = ", ".join(sorted({networks[i]["name"] for i in runs_in if i in networks}))
    box = enclosing(groups, n["group"], "network")
    subnet = enclosing(groups, n["group"], "subnet")
    if box is None:
        if runs_in:
            notes.append(f"{n['id']}: placed in {names}, drawn outside any network group")
        return
    if runs_in and stands[box["id"]] and not runs_in & stands[box["id"]]:
        homes = [gid for gid, cited in stands.items() if runs_in & cited]
        if len(homes) != 1:
            notes.append(f"{n['id']}: placed in {names}, not in network group {box['id']}; moved out")
            n["group"] = outside_network(groups, box)
            return
        notes.append(f"{n['id']}: placed in {names}, not in network group {box['id']}; moved to network group {homes[0]}")
        box, subnet = groups[homes[0]], None
    elif subnet is None:
        return
    tiers = {p["tier"] for p in runs if not stands[box["id"]] or p["network"] in stands[box["id"]]}
    if subnet and subnet["tier"] in tiers:
        return
    if subnet:
        notes.append(f"{n['id']}: no {subnet['tier']} placement fact, moved out of subnet group {subnet['id']}")
    if not runs:
        n["group"] = outside_network(groups, box)
        return
    fits = sorted(g["id"] for g in groups.values() if g["kind"] == "subnet" and g["parent"] == box["id"] and g["tier"] in tiers)
    n["group"] = fits[0] if fits else box["id"]
