"""Check a curated diagram's network claims against the `networks` and `placements` facts."""

from collections import defaultdict
from pathlib import Path

from cartographer.verify_shared import (
    check_claims,
    code_hit,
    enclosing,
    names,
    outside_network,
)


def _problem(group: dict, ev: dict, facts_by_id: dict, repo_root: Path) -> str | None:
    if "stated" in ev:
        return "stated evidence is for described diagrams"
    if "file" in ev:
        return "a network's cidrs come from its network fact" if group["kind"] == "network" else code_hit(repo_root, ev)
    fact = facts_by_id.get(ev["fact"])
    if fact is None:
        return f"unknown fact {ev['fact']}"
    if group["kind"] == "network":
        if set(fact.get("cidrs", [])) == set(group["cidrs"]) and fact.get("cidrs"):
            return None
        return f"fact {ev['fact']} is not a network fact with the group's cidrs"
    if fact.get("tier") == group["tier"]:
        return None
    return f"fact {ev['fact']} is not a placement with tier {group['tier']}"


def check_network(out: dict, facts: dict, facts_by_id: dict, repo_root: Path, notes: list[str]) -> None:
    """Keep cidrs only when their network fact backs them and subnet tiers only when a fact or a code citation backs
    them, then keep each node inside a subnet group only when it has a placement fact of that tier. Check the
    shared networks first, on the evidence as curated."""

    def supported(group: dict, evidence: list[dict]) -> tuple[list[dict], list[str]]:
        problems = [(ev, _problem(group, ev, facts_by_id, repo_root)) for ev in evidence]
        return [ev for ev, p in problems if p is None], [p for _, p in problems if p]

    groups = {g["id"]: g for g in out["groups"]}
    remote = {n["id"]: n for n in facts.get("networks", []) if n["remote"]}
    shared = _shared_networks(out, facts, groups, remote)  # on the evidence as curated, before check_claims prunes it
    _check_owners(groups, shared, remote, notes)
    _check_account_frames(groups, shared, remote, notes)
    check_claims(out, notes, supported)
    placed = {(p["resource"], p["tier"]) for p in facts.get("placements", [])}
    for n in out["nodes"]:
        subnet = enclosing(groups, n["group"], "subnet")
        if subnet and not any((address, subnet["tier"]) in placed for address in n["tf"]):
            notes.append(f"{n['id']}: no {subnet['tier']} placement fact, moved out of subnet group {subnet['id']}")
            n["group"] = outside_network(groups, subnet)


def _cited_remote(group: dict, remote: dict[str, dict]) -> list[dict]:
    """The remote network facts a group's evidence cites."""
    return [remote[ev["fact"]] for ev in group.get("evidence", []) if ev.get("fact") in remote]


def _shared_networks(out: dict, facts: dict, groups: dict[str, dict], remote: dict[str, dict]) -> set[str]:
    """Ids of the network groups this stack runs in but does not create (the `remote` network facts): their placed
    nodes all run in remote networks, or with no placed node, their evidence cites a remote network fact."""
    networks_of: dict[str, set[str]] = defaultdict(set)
    for p in facts.get("placements", []):
        networks_of[p["resource"]].add(p["network"])
    runs_in_remote: dict[str, set[bool]] = {g["id"]: set() for g in groups.values() if g["kind"] == "network"}
    for n in out["nodes"]:
        if network := enclosing(groups, n["group"], "network"):
            runs_in_remote[network["id"]] |= {fact in remote for address in n["tf"] for fact in networks_of[address]}
    return {gid for gid, found in runs_in_remote.items() if found == {True} or not found and _cited_remote(groups[gid], remote)}


def _sources(group: dict, remote: dict[str, dict]) -> list[str]:
    """The names of the data blocks the remote network facts a group cites are read from: `networking` in
    `data.tfe_outputs.networking.nonsensitive_values.shared_vpc_id`."""
    return [f["address"].split(".")[2] for f in _cited_remote(group, remote)]


def _check_owners(groups: dict[str, dict], shared: set[str], remote: dict[str, dict], notes: list[str]) -> None:
    """A network names the account that owns it only when it is shared and its evidence cites a remote network fact
    whose source names that account."""
    for g in groups.values():
        owner = g.get("owner")
        if owner and not (g["id"] in shared and any(names(owner, s) for s in _sources(g, remote))):
            notes.append(f"group {g['id']}: owner dropped, it is not a shared network whose cited source names it")
            del g["owner"]


def _check_account_frames(groups: dict[str, dict], shared: set[str], remote: dict[str, dict],
                          notes: list[str]) -> None:
    """The stack's nodes run in the stack's account even when the network they use belongs to another one. Warn when
    a shared network sits in an account frame whose label names the network's source, the owner's account."""
    for gid in sorted(shared):
        account = enclosing(groups, gid, "account")
        if account and any(names(account["label"], s) for s in _sources(groups[gid], remote)):
            notes.append(f"group {gid}: shared network sits in account {account['id']} ({account['label']}), the "
                         f"account that owns it; draw it in the stack's account with `owner` set")
