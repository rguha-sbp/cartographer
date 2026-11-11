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
    cited = {g["id"]: {ev.get("fact") for ev in g.get("evidence", [])} for g in out["groups"]}  # before claims drop any
    check_claims(out, notes, supported)
    placed: dict[str, list[dict]] = defaultdict(list)  # a resource -> its placements
    for p in facts.get("placements", []):
        placed[p["resource"]].append(p)
    for n in out["nodes"]:
        subnet = enclosing(groups, n["group"], "subnet")
        if subnet and not any(p["tier"] == subnet["tier"] for address in n["tf"] for p in placed[address]):
            notes.append(f"{n['id']}: no {subnet['tier']} placement fact, moved out of subnet group {subnet['id']}")
            n["group"] = outside_network(groups, subnet)
    _mark_shared(out, facts, groups, cited, placed, notes)


ENVIRONMENTS = {"prod", "production", "prd", "dev", "development", "develop", "test", "tst", "acc", "acceptance", "stag",
                "stage", "stg", "preprod", "qa", "uat", "sandbox", "nonprod", "env"}
IGNORED = {"account", "subscription", "terraform", "aws", "azure", "amazon", "microsoft", *ENVIRONMENTS}
REGION = re.compile(r"\b[a-z]{2}(-[a-z]+)?-(north|south|east|west|central)[a-z]*-\d+[a-z]?\b")  # us-east-1, us-gov-west-1


def _mark_shared(out: dict, facts: dict, groups: dict[str, dict], cited: dict[str, set], placed: dict[str, list[dict]],
                 notes: list[str]) -> None:
    """Set `shared_from` on each network group that another stack creates: it holds a placed node, and the networks its
    nodes are placed in and the network facts its evidence cites all come from other stacks' outputs. Evidence alone
    never makes a group shared, but a cited local network keeps it local. Warn when its evidence cites a network of a
    stack none of its nodes is placed in, and when it sits in an account frame named after its stack: the stack's
    nodes run in the stack's account."""
    networks = {n["id"]: n for n in facts.get("networks", [])}
    inside: dict[str, list[dict]] = defaultdict(list)  # a network group -> the placements of its nodes
    for n in out["nodes"]:
        if network := enclosing(groups, n["group"], "network"):
            inside[network["id"]] += [p for address in n["tf"] for p in placed[address]]
    for g in groups.values():
        if g["kind"] != "network":
            continue
        # a resource can sit in several networks: the group stands for the ones it cites, when its nodes are in any
        own = [p for p in inside[g["id"]] if p["network"] in cited[g["id"]]] or inside[g["id"]]
        stacks = {s for p in own for s in _stacks(p, networks)}
        cites_local = any(networks[fact].get("stack") is None for fact in cited[g["id"]] if fact in networks)
        if not stacks or None in stacks or cites_local:
            continue
        g["shared_from"] = ", ".join(sorted(stacks))
        if elsewhere := {networks[fact]["stack"] for fact in cited[g["id"]] if fact in networks} - stacks:
            notes.append(f"group {g['id']}: evidence cites a network of {', '.join(sorted(elsewhere))}, but its nodes are "
                         f"placed in a network of {g['shared_from']}; cite the network the nodes run in")
        account = enclosing(groups, g["id"], "account")
        if account and any(named_after(account["label"], s) for s in stacks):
            notes.append(f"group {g['id']}: shared network sits in account {account['id']} ({account['label']}), "
                         f"named after the stack it comes from; if the stack's nodes run in another account, draw it there")


def _stacks(placement: dict, networks: dict[str, dict]) -> set[str | None]:
    """The stacks a placement's network and subnet come from, None for this one: a remote subnet output names its
    stack, which can differ from the VPC's."""
    return {networks[placement["network"]].get("stack")} | ({placement["stack"]} if placement.get("stack") else set())


def named_after(label: str, stack: str) -> bool:
    """Whether an account label and the stack name have the same words in any order, less IGNORED words, regions and
    account numbers, each word with a trailing `ing` or `s` dropped: `networking`, `networking-prod` and
    `prod/networking` name `Networking account`, `Network account`, `AWS networking us-east-1` and
    `Networking (123456789012)`; none names `Shop network account`, `Prod account` or `Net`."""
    words = _stems(label)
    return bool(words) and words == _stems(stack)


def _stems(name: str) -> list[str]:
    """The words of `name` that are not IGNORED, AWS regions or numbers, each less a trailing `ing` or `s`, sorted."""
    words = re.findall(r"[a-z0-9]+", REGION.sub(" ", name.lower().replace("_", "-")))
    return sorted(s for w in words if not w.isdigit() and (s := _stem(w)) and s not in IGNORED_STEMS)


def _stem(word: str) -> str:
    return re.sub(r"(ing|s)$", "", word)


IGNORED_STEMS = {_stem(w) for w in IGNORED}
