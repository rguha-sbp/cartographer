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
    """Keep cidrs and subnet tiers only when a fact or a code citation backs them, keep each node inside a subnet group
    only when it has a placement fact of that tier, then mark the networks other stacks create."""

    def supported(group: dict, evidence: list[dict]) -> tuple[list[dict], list[str]]:
        problems = [(ev, _problem(group, ev, facts_by_id, repo_root)) for ev in evidence]
        return [ev for ev, p in problems if p is None], [p for _, p in problems if p]

    groups = {g["id"]: g for g in out["groups"]}
    check_claims(out, notes, supported)
    placed = {(p["resource"], p["tier"]) for p in facts.get("placements", [])}
    for n in out["nodes"]:
        subnet = enclosing(groups, n["group"], "subnet")
        if subnet and not any((address, subnet["tier"]) in placed for address in n["tf"]):
            notes.append(f"{n['id']}: no {subnet['tier']} placement fact, moved out of subnet group {subnet['id']}")
            n["group"] = outside_network(groups, subnet)
    _mark_shared(out, facts, groups, notes)


STACK_OUTPUT = re.compile(r"data\.(?:tfe_outputs|terraform_remote_state)\.(\w+)\.")


def _stack(network: dict) -> str | None:
    """The stack a network fact is read from (`networking` for `data.tfe_outputs.networking...`); None for a network
    this stack creates or looks up itself."""
    m = STACK_OUTPUT.match(network["address"]) if network["remote"] else None
    return m[1] if m else None


def _mark_shared(out: dict, facts: dict, groups: dict[str, dict], notes: list[str]) -> None:
    """Set `shared_from` on each network group that another stack creates: it holds a placed node, and the networks its
    nodes are placed in all come from other stacks' outputs. Warn when such a group sits in an account frame named
    after that stack: the stack's nodes run in the stack's account."""
    networks = {n["id"]: n for n in facts.get("networks", [])}
    networks_of: dict[str, set[str]] = defaultdict(set)
    for p in facts.get("placements", []):
        networks_of[p["resource"]].add(p["network"])
    placed: dict[str, set[str]] = defaultdict(set)
    for n in out["nodes"]:
        if network := enclosing(groups, n["group"], "network"):
            placed[network["id"]] |= {net for address in n["tf"] for net in networks_of[address]}
    for g in groups.values():
        if g["kind"] != "network":
            continue
        stacks = {_stack(networks[net]) for net in placed[g["id"]]}
        if not stacks or None in stacks:
            continue
        g["shared_from"] = ", ".join(sorted(stacks))
        account = enclosing(groups, g["id"], "account")
        if account and any(_named_after(account["label"], s) for s in stacks):
            notes.append(f"group {g['id']}: shared network sits in account {account['id']} ({account['label']}), "
                         f"named after the stack it comes from; draw it in the account of the stack's nodes")


def _named_after(label: str, stack: str) -> bool:
    """Whether an account label is the stack name, less `account`, `subscription` and account numbers, with each word
    allowed to stem the other: `networking` names `Networking account`, `Network account` and `Networking
    (123456789012)`, not `Shop network account`."""
    label_words, stack_words = _words(label), _words(stack)

    def stems(ws: list[str], others: list[str]) -> bool:
        return all(any(w.startswith(o) or o.startswith(w) for o in others) for w in ws)

    return bool(label_words) and stems(label_words, stack_words) and stems(stack_words, label_words)


def _words(name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in ("account", "subscription") and not w.isdigit()]
