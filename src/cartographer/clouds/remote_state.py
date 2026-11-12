"""The identity of the state a remote state data source reads, from its `.tf` text only: the state is never opened,
only compared, so two data sources that name one state share its networks."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cartographer.tf_modules import SINGLE, bare, declared_provider
from cartographer.tf_policies import norm_keys, unq
from cartographer.tf_values import UNRESOLVED

if TYPE_CHECKING:
    from cartographer.tf_modules import Inst

SELECTING = ("backend", "workspace", "organization")
TFE_HOST = "app.terraform.io"  # the `tfe` provider's default hostname
LITERAL_INDEX = re.compile(r'"[^"]*"|\d+')


@dataclass(frozen=True)
class State:
    """The state a remote state data source names, as its `.tf` text writes it: never read, only compared. `settings`
    are the literal (path, value) pairs that select it; `index` is the literal index of a `count` or `for_each` one."""

    kind: str
    settings: tuple[tuple[str, str], ...]
    index: str | None


def remote_key(state: State | str, name: str) -> str:
    """The key of the network `name` in `state`."""
    return f"{name}@{state!r}"


def state_of(inst: Inst, kind: str, name: str, index: str | None) -> State | str:
    """The `State` the data source `kind`.`name` names, read from its `.tf` block with `Inst.value(agree=True)`. Its
    full address instead when the block is not found, selects nothing, or any setting or the index is no literal."""
    address = f"{inst.prefix}data.{kind}.{name}" + (f"[{index}]" if index is not None else "")
    body, config = _remote_state(inst, kind, name)
    if config is None:
        return address
    written = [(k, body[k]) for k in SELECTING if k in body] + _leaves("config", config)
    settings = {path: inst.value(v, agree=True) for path, v in written}
    if kind == "tfe_outputs" and settings:
        settings = _tfe_defaults(inst, body) | settings
    literal = LITERAL_INDEX.fullmatch(index) if index is not None else None
    if not settings or any(not isinstance(v, str) for v in settings.values()) or (index is not None and not literal):
        return address
    if kind == "terraform_remote_state":
        kind, settings = _as_workspace(settings)
    return State(kind, tuple(sorted(settings.items())), literal[0].strip('"') if literal else None)


def _tfe_defaults(inst: Inst, body: dict) -> dict[str, Any]:
    """The `hostname` and any `organization` of the `tfe` provider a `tfe_outputs` block uses (its `provider`
    meta-argument, through the module calls' `providers` maps): two hosts or two organizations can each hold a
    workspace of one name. A setting with no literal is UNRESOLVED."""
    owner, key = declared_provider(inst, bare(body.get("provider", "tfe")))
    if owner is None or not key:
        return {"hostname": TFE_HOST if key == "tfe" else UNRESOLVED}  # the implicit default provider of the root
    provider = owner.mod.providers[key]
    host = owner.value(provider.get("hostname"), agree=True)
    org = {"organization": owner.value(provider["organization"], agree=True)} if "organization" in provider else {}
    return {"hostname": TFE_HOST if host is None else host, **org}


def _as_workspace(settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """A `terraform_remote_state` read: the `remote` backend of one named workspace is the workspace a `tfe_outputs`
    block reads, so both get the same identity. Any other read keeps its settings, without the default workspace."""
    settings = {k: v for k, v in settings.items() if (k, v) != ("workspace", "default")}
    remote = {"backend": "remote", "config.organization": settings.get("config.organization"),
              "config.workspaces.name": settings.get("config.workspaces.name")}
    if remote.items() <= settings.items() and set(settings) <= {*remote, "config.hostname"}:
        return "tfe_outputs", {"hostname": settings.get("config.hostname", TFE_HOST),
                               "organization": settings["config.organization"],
                               "workspace": settings["config.workspaces.name"]}
    return "terraform_remote_state", settings


def _leaves(path: str, value: Any) -> list[tuple[str, Any]]:
    """The (dotted path, expression) of every leaf of a `config` object."""
    if isinstance(value, dict):
        return [leaf for k, v in value.items() for leaf in _leaves(f"{path}.{k}", v)]
    return [(path, value)]


def _remote_state(inst: Inst, kind: str, name: str) -> tuple[dict, dict | None]:
    """The body of the data source `kind`.`name` and its `config` object, written in place or as one `local.`: empty
    when the block has none, None when it has one that is no object literal (`var.x`, `merge(...)`)."""
    block = inst.mod.data.get((kind, name))
    body = norm_keys(block.body) if block else {}
    if "config" not in body:
        return body, {}
    config = body["config"]
    if isinstance(config, str) and (m := SINGLE.fullmatch(unq(config))) and m[1] == "local":
        config = norm_keys(inst.mod.locals.get(m[2]))
    return body, config if isinstance(config, dict) else None
