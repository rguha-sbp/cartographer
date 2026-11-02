"""The Cloud object: everything that differs between clouds hangs off an instance of it."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from cartographer.tf_extract import Extractor
    from cartographer.tf_modules import Res

UNRESOLVED = object()  # the attribute exists but is not a literal (reference, local, var without default)
# attribute path such as "sku.tier" -> literal, None (absent) or UNRESOLVED; `present=True` -> whether any block sets it
# to something other than null; `every=True` -> the values of that path in every repeated block
Getter = Callable[..., str | None | bool | object]


def load_json(package_file: str, name: str) -> Any:
    return json.loads(Path(package_file).with_name(name).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Spec:
    """kind edge from refs of `src` (None = the resource itself) to refs of `dst`, optionally only under `leaf`."""

    kind: str
    src: str | None
    dst: str
    leaf: str | None = None


@dataclass(frozen=True)
class Resolution:
    kind: Literal["icon", "fold", "drop", "none"]
    icon: str | None = None  # qualified, e.g. "aws:elastic_load_balancing"
    decided_by: str = ""  # "catalog aws_s3_bucket", 'rule aws_lb load_balancer_type = "network"'
    marked: bool = False
    reason: str | None = None  # set when marked
    scope: Literal["regional", "global"] = "regional"


class Catalog:
    """Terraform type -> row, by the longest key `k` with `tf_type == k` or `tf_type` starting `k_`."""

    def __init__(self, rows: dict[str, dict]) -> None:
        self.rows = rows

    def row(self, tf_type: str) -> tuple[str, dict] | None:
        key = tf_type
        while True:
            if key in self.rows:
                return key, self.rows[key]
            if "_" not in key:
                return None
            key = key.rsplit("_", 1)[0]


Rule = Callable[[Getter], Resolution | None]


class Cloud(ABC):
    def __init__(self, name: str, label: str, providers: tuple[str, ...], icons: dict[str, dict],
                 frame_styles: dict[str, str], managed_label: str, *, provider_types: list[str] | None = None,
                 catalog: Catalog | None = None, rules: dict[str, Rule] | None = None,
                 modules: dict[str, str] | None = None, edge_specs: dict[str, list[Spec]] | None = None,
                 network_attrs: frozenset[str] = frozenset(), data_ref_types: frozenset[str] = frozenset(),
                 param_types: frozenset[str] = frozenset(), deployed_types: frozenset[str] = frozenset()) -> None:
        self.name = name
        self.label = label
        self.providers = providers
        self.icons = icons
        self.frame_styles = frame_styles  # complete draw.io styles, keyed by frame kind
        self.managed_label = managed_label
        self.provider_types = provider_types or []
        self._listed = frozenset(self.provider_types)
        self.catalog = catalog or Catalog({})
        self.rules = rules or {}
        self.modules = modules or {}  # module source prefix -> icon name
        self.edge_specs = edge_specs or {}
        self.network_attrs = network_attrs  # attribute names whose references are `network` edges
        self.data_ref_types = data_ref_types  # data source types whose body the reference scan follows
        self.param_types = param_types  # parameter and secret resources whose `name` is an integration hint
        self.deployed_types = deployed_types  # compute, store and queue types a C4 Deployment view places or omits

    def network_facts(self, ex: Extractor) -> dict:
        """{"networks": [...], "placements": [...]} without ids; a placement names its network by address.
        An optional "unplaced" maps a resource address to the reason it could not be placed; the resource is then marked."""
        return {"networks": [], "placements": []}

    def permission_edges(self, ex: Extractor) -> None:
        """Add permission edges through `ex.add` and `ex.services`."""

    def extra(self, ex: Extractor, res: Res) -> dict:
        """Cloud-specific fields of a resource's facts entry."""
        return {}

    def resolve(self, tf_type: str, get: Getter) -> Resolution:
        found = self.catalog.row(tf_type)
        if found is None:
            return Resolution("none", marked=True, reason="type not in catalog")
        key, row = found
        decided_by = f"catalog {key}"
        if "fold" in row:
            return Resolution("fold", decided_by=decided_by)
        if "drop" in row:
            return Resolution("drop", decided_by=decided_by)
        icon = f"generic:{row['generic']}" if "generic" in row else f"{self.name}:{row['icon']}"
        base = Resolution("icon", icon, decided_by, scope="global" if row.get("global") else "regional")
        if self._listed and key != tf_type and tf_type not in self._listed:
            return replace(base, marked=True, reason="type newer than provider list")
        if "rule" not in row or key != tf_type:
            return base
        unresolved: list[str] = []

        def watched(attr: str, present: bool = False, every: bool = False) -> str | None | bool | list | object:
            if present:
                return get(attr, present=True)
            if every:
                values = get(attr, every=True)
                if UNRESOLVED in values:
                    unresolved.append(attr)
                return values
            value = get(attr)
            if value is UNRESOLVED:
                unresolved.append(attr)
            return value

        ruled = self.rules[row["rule"]](watched)
        if unresolved:
            return replace(base, marked=True, reason=f"{unresolved[0]} is not a literal")
        return ruled or base

    @abstractmethod
    def icon_style(self, name: str) -> str:
        """The complete draw.io style of the icon `name`."""
