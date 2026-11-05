"""Check a curated diagram's network claims against the `networks` and `placements` facts."""

from collections import Counter, defaultdict
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

    check_claims(out, notes, supported)
    placed = {(p["resource"], p["tier"]) for p in facts.get("placements", [])}
    groups = {g["id"]: g for g in out["groups"]}
    for n in out["nodes"]:
        subnet = enclosing(groups, n["group"], "subnet")
        if subnet and not any((address, subnet["tier"]) in placed for address in n["tf"]):
            notes.append(f"{n['id']}: no {subnet['tier']} placement fact, moved out of subnet group {subnet['id']}")
            n["group"] = outside_network(groups, subnet)
    shared = _shared_networks(out, facts, groups)
    _check_owners(groups, shared, notes)
    _home_shared_networks(out, groups, shared, notes)


def _shared_networks(out: dict, facts: dict, groups: dict[str, dict]) -> set[str]:
    """Ids of the network groups whose every node runs only in networks this stack does not create (`remote`)."""
    remote = {n["id"] for n in facts.get("networks", []) if n["remote"]}
    networks_of: dict[str, set[str]] = defaultdict(set)
    for p in facts.get("placements", []):
        networks_of[p["resource"]].add(p["network"])
    remote_nodes: dict[str, list[bool]] = defaultdict(list)
    for n in out["nodes"]:
        if network := enclosing(groups, n["group"], "network"):
            runs_in = set().union(*(networks_of[address] for address in n["tf"]))
            remote_nodes[network["id"]].append(bool(runs_in) and runs_in <= remote)
    return {gid for gid, flags in remote_nodes.items() if all(flags)}


def _check_owners(groups: dict[str, dict], shared: set[str], notes: list[str]) -> None:
    """Only a shared network names the account that owns it."""
    for g in groups.values():
        if g.get("owner") and g["id"] not in shared:
            notes.append(f"group {g['id']}: owner dropped, its nodes do not run in a shared network")
            del g["owner"]


def _home_shared_networks(out: dict, groups: dict[str, dict], shared: set[str], notes: list[str]) -> None:
    """The stack's nodes run in the stack's account even when the network they use belongs to another one. A shared
    network in an account frame that holds none of the stack's other nodes moves to the account of its cloud that holds
    the most."""

    def in_shared(gid: str | None) -> bool:
        network = enclosing(groups, gid, "network")
        return network is not None and network["id"] in shared

    homes = Counter(account["id"] for n in out["nodes"]
                    if not in_shared(n["group"]) and (account := enclosing(groups, n["group"], "account")))
    for gid in sorted(shared):
        account = enclosing(groups, gid, "account")
        if account is None or account["id"] in homes:
            continue
        cloud = groups[gid].get("cloud")
        home = next((a for a, _ in homes.most_common() if groups[a].get("cloud") == cloud), None)
        if home is None:
            continue
        notes.append(f"group {gid}: shared network sat in account {account['id']}, "
                     f"which holds none of the stack's other nodes, moved to {home}")
        groups[gid]["parent"] = home
        _drop_empty(out, groups, account["id"], notes)


def _drop_empty(out: dict, groups: dict[str, dict], gid: str | None, notes: list[str]) -> None:
    """Remove `gid` and then each ancestor while it holds no group and no node."""
    while gid in groups and not any(g["parent"] == gid for g in groups.values()) \
            and not any(n["group"] == gid for n in out["nodes"]):
        notes.append(f"group {gid}: empty after the move, removed")
        gid = groups.pop(gid)["parent"]
    out["groups"] = [g for g in out["groups"] if g["id"] in groups]
