"""Check a curated diagram's network claims against the `networks` and `placements` facts."""

import re
from collections import defaultdict
from pathlib import Path

from cartographer.tf_blocks import live_groups
from cartographer.verify_shared import (
    ancestors,
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

    check_claims(out, notes, supported)
    placed = {(p["resource"], p["tier"]) for p in facts.get("placements", [])}
    groups = {g["id"]: g for g in out["groups"]}
    for n in out["nodes"]:
        subnet = enclosing(groups, n["group"], "subnet")
        if subnet and not any((address, subnet["tier"]) in placed for address in n["tf"]):
            notes.append(f"{n['id']}: no {subnet['tier']} placement fact, moved out of subnet group {subnet['id']}")
            n["group"] = outside_network(groups, subnet)
    shared = _shared_networks(out, facts, groups)
    _check_owners(groups, shared, repo_root, notes)
    _home_shared_networks(out, groups, shared, notes)


def _shared_networks(out: dict, facts: dict, groups: dict[str, dict]) -> set[str]:
    """Ids of the network groups this stack runs in but does not create (`remote` network facts): their placed nodes
    all run in remote networks, or with no placed node, their evidence cites a remote network fact."""
    remote = {n["id"] for n in facts.get("networks", []) if n["remote"]}
    networks_of: dict[str, set[str]] = defaultdict(set)
    for p in facts.get("placements", []):
        networks_of[p["resource"]].add(p["network"])
    runs_in_remote: dict[str, set[bool]] = {g["id"]: set() for g in groups.values() if g["kind"] == "network"}
    for n in out["nodes"]:
        if network := enclosing(groups, n["group"], "network"):
            runs_in_remote[network["id"]] |= {fact in remote for address in n["tf"] for fact in networks_of[address]}

    def cites_remote(gid: str) -> bool:
        return any(ev.get("fact") in remote for ev in groups[gid].get("evidence", []))

    return {gid for gid, found in runs_in_remote.items() if found == {True} or not found and cites_remote(gid)}


def _names(owner: str, ev: dict) -> bool:
    """True when the cited text names the owner: its letters and digits, less the word account, appear in it."""
    def squash(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", text.lower())

    name = squash(re.sub(r"(?i)\baccount\b", "", owner))
    return bool(name) and name in squash(ev["contains"])


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


def _home_shared_networks(out: dict, groups: dict[str, dict], shared: set[str], notes: list[str]) -> None:
    """The stack's nodes run in the stack's account even when the network they use belongs to another one. A shared
    network in an account frame that holds none of the stack's other nodes moves to the one account frame of its
    cloud that does; with none or several such frames it stays, with a warning. The frames the move leaves without a
    node go."""

    def in_shared(gid: str | None) -> bool:
        network = enclosing(groups, gid, "network")
        return network is not None and network["id"] in shared

    homes = {account["id"] for n in out["nodes"]
             if not in_shared(n["group"]) and (account := enclosing(groups, n["group"], "account"))}
    left: list[str] = []
    for gid in sorted(shared):
        account = enclosing(groups, gid, "account")
        if account is None or account["id"] in homes:
            continue
        candidates = sorted(a for a in homes if groups[a].get("cloud") == groups[gid].get("cloud"))
        where = f"group {gid}: shared network sat in account {account['id']}, which holds none of the stack's other nodes"
        if len(candidates) != 1:
            notes.append(f"{where}, and no single account of its cloud does, left in place")
            continue
        notes.append(f"{where}, moved to {candidates[0]}")
        groups[gid]["parent"] = candidates[0]
        left.append(account["id"])
    _drop_unused(out, groups, left, notes)


def _drop_unused(out: dict, groups: dict[str, dict], left: list[str], notes: list[str]) -> None:
    """Remove each frame in `left` that holds no node any more, with its highest ancestor that holds none either and
    everything inside that one."""
    live = live_groups(out)
    gone: set[str] = set()
    for gid in left:
        top = None
        for g in ancestors(groups, gid):
            if g["id"] in live:
                break
            top = g["id"]
        if top is not None and top not in gone:
            notes.append(f"group {top}: no node left after the move, removed with the groups inside it")
            gone.add(top)
    out["groups"] = [g for g in out["groups"] if not any(a["id"] in gone for a in ancestors(groups, g["id"]))]
