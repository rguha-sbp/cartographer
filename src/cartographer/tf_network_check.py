"""Check a curated diagram's network claims against the `networks` and `placements` facts."""

import re
from collections import defaultdict
from pathlib import Path

from cartographer.verify_shared import (
    check_claims,
    code_hit,
    enclosing,
    outside_network,
)


def _problem(group: dict, ev: dict, facts_by_id: dict, repo_root: Path) -> str | None:
    if "stated" in ev:
        return "stated evidence is for described diagrams"
    if "file" in ev:
        return code_hit(repo_root, ev)
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
    """Keep cidrs and subnet tiers only when a fact or a code citation backs them, then keep each node inside a
    subnet group only when it has a placement fact of that tier. Last, check the shared networks."""

    def supported(group: dict, evidence: list[dict]) -> tuple[list[dict], list[str]]:
        problems = [(ev, _problem(group, ev, facts_by_id, repo_root)) for ev in evidence]
        return [ev for ev, p in problems if p is None], [p for _, p in problems if p]

    remote = {n["id"] for n in facts.get("networks", []) if n["remote"]}
    cites_remote = {g["id"] for g in out["groups"] if any(ev.get("fact") in remote for ev in g.get("evidence", []))}
    check_claims(out, notes, supported)
    placed = {(p["resource"], p["tier"]) for p in facts.get("placements", [])}
    groups = {g["id"]: g for g in out["groups"]}
    for n in out["nodes"]:
        subnet = enclosing(groups, n["group"], "subnet")
        if subnet and not any((address, subnet["tier"]) in placed for address in n["tf"]):
            notes.append(f"{n['id']}: no {subnet['tier']} placement fact, moved out of subnet group {subnet['id']}")
            n["group"] = outside_network(groups, subnet)
    shared = _shared_networks(out, facts, groups, remote, cites_remote)
    _check_owners(groups, shared, repo_root, notes)
    _check_homes(out, groups, shared, notes)


def _shared_networks(out: dict, facts: dict, groups: dict[str, dict], remote: set[str],
                     cites_remote: set[str]) -> set[str]:
    """Ids of the network groups this stack runs in but does not create (the `remote` network facts): their placed
    nodes all run in remote networks, or with no placed node, their curated evidence cited a remote network fact."""
    networks_of: dict[str, set[str]] = defaultdict(set)
    for p in facts.get("placements", []):
        networks_of[p["resource"]].add(p["network"])
    runs_in_remote: dict[str, set[bool]] = {g["id"]: set() for g in groups.values() if g["kind"] == "network"}
    for n in out["nodes"]:
        if network := enclosing(groups, n["group"], "network"):
            runs_in_remote[network["id"]] |= {fact in remote for address in n["tf"] for fact in networks_of[address]}
    return {gid for gid, found in runs_in_remote.items() if found == {True} or not found and gid in cites_remote}


def _names(owner: str, ev: dict) -> bool:
    """True when the cited text names the owner, less the word account, as whole words: `Networking account` matches
    `tfe_outputs.networking` and `networking_vpc_id`, but `Network account` does not. Underscores, dashes and spaces
    between the owner's words all match."""
    words = re.findall(r"[a-z0-9]+", re.sub(r"(?i)\baccount\b", "", owner).lower())
    pattern = r"(?<![a-z0-9])" + r"[_\s-]*".join(words) + r"(?![a-z0-9])"
    return bool(words) and re.search(pattern, ev["contains"].lower()) is not None


def _check_owners(groups: dict[str, dict], shared: set[str], repo_root: Path, notes: list[str]) -> None:
    """Only a shared network names the account that owns it, and a code citation in its evidence names it too."""
    for g in groups.values():
        if not (owner := g.get("owner")):
            continue
        if g["id"] not in shared:
            reason = "its nodes do not run in a shared network"
        elif not any("file" in ev and _names(owner, ev) and code_hit(repo_root, ev) is None
                     for ev in g.get("evidence", [])):
            reason = "no code citation names the owning account"
        else:
            continue
        notes.append(f"group {g['id']}: owner dropped, {reason}")
        del g["owner"]


def _check_homes(out: dict, groups: dict[str, dict], shared: set[str], notes: list[str]) -> None:
    """The stack's nodes run in the stack's account even when the network they use belongs to another one. Warn when
    a shared network sits in an account frame that holds none of the stack's other nodes while another account frame
    of its cloud does. The diagram cannot tell an owner's frame from a second account of the stack, so it moves
    nothing."""

    def in_shared(gid: str | None) -> bool:
        network = enclosing(groups, gid, "network")
        return network is not None and network["id"] in shared

    homes = {account["id"] for n in out["nodes"]
             if not in_shared(n["group"]) and (account := enclosing(groups, n["group"], "account"))}
    for gid in sorted(shared):
        account = enclosing(groups, gid, "account")
        if account is None or account["id"] in homes:
            continue
        others = sorted(a for a in homes if groups[a].get("cloud") == groups[gid].get("cloud"))
        if others:
            notes.append(f"group {gid}: shared network sits in account {account['id']}, which holds none of the "
                         f"stack's other nodes; draw it in the stack's account ({', '.join(others)}) with `owner` set")
