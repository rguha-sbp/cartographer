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
    them, then keep each node inside a subnet group only when it has a placement fact of that tier. Last, check the
    shared networks."""

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
    remote = {n["id"]: n for n in facts.get("networks", []) if n["remote"]}
    _check_owners(groups, remote, notes)
    _check_homes(out, groups, _shared_networks(out, facts, groups, remote), notes)


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


def _source_name(address: str) -> str:
    """The name of the block a remote network comes from: `networking` in
    `data.tfe_outputs.networking.nonsensitive_values.shared_vpc_id`."""
    parts = address.split(".")
    return parts[2] if parts[0] == "data" and len(parts) > 2 else parts[min(1, len(parts) - 1)]


def _names(owner: str, source: str) -> bool:
    """True when a remote network's source name names the owner, less the words account and subscription, as whole
    words: `Networking account` matches `networking` and `shared_networking`, but `Network account` does not."""
    words = re.findall(r"[a-z0-9]+", re.sub(r"(?i)\b(account|subscription)\b", "", owner).lower())
    pattern = r"(?<![a-z0-9])" + r"[_\s-]*".join(words) + r"(?![a-z0-9])"
    return bool(words) and re.search(pattern, source.lower()) is not None


def _check_owners(groups: dict[str, dict], remote: dict[str, dict], notes: list[str]) -> None:
    """A network names the account that owns it only when its evidence cites a remote network fact whose source
    (the data block it is read from) names that account."""
    for g in groups.values():
        owner = g.get("owner")
        if owner and not any(_names(owner, _source_name(f["address"])) for f in _cited_remote(g, remote)):
            notes.append(f"group {g['id']}: owner dropped, it cites no remote network fact whose source names it")
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
        others = sorted(a for a in homes if groups[a].get("cloud") == account.get("cloud"))
        if others:
            notes.append(f"group {gid}: shared network sits in account {account['id']}, which holds none of the "
                         f"stack's other nodes; draw it in the stack's account ({', '.join(others)}) with `owner` set")
