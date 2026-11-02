"""Azure permission edges: role assignments and Key Vault access policies become `iam` edges from the principal that
holds them to the resource they name. A resource group or subscription scope is a cloud-wide service entry."""
from __future__ import annotations

from typing import TYPE_CHECKING

from cartographer.tf_policies import unq
from cartographer.tf_values import attrs, text

if TYPE_CHECKING:
    from cartographer.tf_extract import Extractor
    from cartographer.tf_modules import Res

IDENTITY_KEYS = ("identity_ids", "user_assigned_identity_id")
PERMISSION_KEYS = ("certificate_permissions", "key_permissions", "secret_permissions", "storage_permissions")
WIDE_SCOPES = ("azurerm_resource_group", "azurerm_subscription")


def carriers(ex: Extractor) -> dict[str, set[str]]:
    """User-assigned identity -> the resources that carry it."""
    found: dict[str, set[str]] = {}
    for r in ex.res:
        if r.type != "azurerm_user_assigned_identity":
            for key in IDENTITY_KEYS:
                for identity in ex.leaf_refs(r.inst, r.block.body, key):
                    found.setdefault(identity, set()).add(r.address)
    return found


def holders(ex: Extractor, r: Res, expr: object, by_identity: dict[str, set[str]]) -> list[str]:
    """The resources a `principal_id` or `object_id` expression stands for."""
    return sorted(set().union(*(by_identity.get(p) or {p} for p in ex.refs(r.inst, expr))))


def grant(ex: Extractor, r: Res, who: list[str], scope: object, detail: set[str]) -> None:
    targets = {t for t in ex.refs(r.inst, scope) if ex.types.get(t) not in WIDE_SCOPES}
    wide = any(ex.types.get(t) in WIDE_SCOPES for t in ex.refs(r.inst, scope)) or "azurerm_subscription" in text(scope)
    if wide:
        for role in detail:
            entry = ex.services.setdefault(f"azure:{role}", {"actions": set(), "principals": set()})
            entry["actions"].add(role)
            entry["principals"].update(who)
    elif not targets:
        ex.stats["constructed_arns"] += 1
    for src in who:
        for dst in sorted(targets):
            ex.add(src, dst, "iam", detail, r)


def permission_edges(ex: Extractor) -> None:
    by_identity = carriers(ex)
    for r in ex.res:
        body = attrs(r.block.body)
        if r.type == "azurerm_role_assignment":
            role = ex.value(r.inst, body.get("role_definition_name"))
            detail = {role} if isinstance(role, str) else {"role_definition_id"}
            grant(ex, r, holders(ex, r, body.get("principal_id"), by_identity), body.get("scope"), detail)
        elif r.type == "azurerm_key_vault_access_policy":
            perms = {f"{key.removesuffix('_permissions')}:{unq(p)}" for key in PERMISSION_KEYS
                     for p in (body.get(key) if isinstance(body.get(key), list) else []) if "${" not in text(p)}
            grant(ex, r, holders(ex, r, body.get("object_id"), by_identity), body.get("key_vault_id"), perms)
