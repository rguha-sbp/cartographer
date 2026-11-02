# Multi-cloud and Azure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every diagram icon deterministically from a reviewed per-cloud catalog, move AWS behind a cloud contract, and add Azure plus multi-cloud diagrams.

**Architecture:** One icon namespace for the whole tool (`aws:lambda`, `azure:azure_openai`, `generic:users`,
`brand:github`), one `clouds/` package per cloud behind a small base class, and a cloud-neutral core that asks the
cloud owning each resource for its icon, network facts, permission edges and frame styles. The curated file gains
`"format": 2`; older files are upgraded on read.

**Tech Stack:** Python 3.13, python-hcl2, pytest, ruff (line length 120), uv. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-02-multi-cloud-azure-design.md`. Read it before any task.

## Global Constraints

- No new runtime or dev dependency; `uv.lock` changes only if a task says so (none does).
- No file over 1,000 lines. `tf_extract.py` must shrink.
- The core never tests a cloud name (`== "aws"`, `"azure" in`, `startswith("aws_")`): every cloud difference is a
  member of the cloud object. A grep test enforces this (Task 5).
- A single-cloud AWS diagram renders byte-identical `.drawio` to today, except icons the catalog corrects (Task 1
  goldens).
- No full icon list of any cloud in the schema, the prompts or the skill. The schema is a static file.
- Downloaded Azure samples are untrusted: run Python on them with `-I`, never execute anything from them, never
  commit them. Fixtures are synthetic and contain no client or company names.
- Never call a cloud API, `terraform`, state or `.tfvars`. Never download at runtime.
- User-visible text (skill, prompts, README, CLI help): no em or en dashes, no smart quotes.
- Comments only for a non-obvious why. Match the surrounding terse style.
- Commit after each task with a Conventional Commit message ending
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- Run `uv run ruff check` and the task's tests before committing; the whole suite (`uv run pytest -q`) at the end of
  Tasks 3, 5, 7 and 12.

## Review Focus

1. A Terraform repo with a type newer than the vendored provider list (`aws_newthing_x`): extraction must not fail;
   the resource resolves to its family row or to `none` with `marked: true` and reason `type not in catalog`.
   Test in Task 4.
2. An attribute rule whose attribute is `var.x` with no default, a `local`, or a reference: base icon, `marked: true`,
   never a guess and never an exception. Tests per rule in Tasks 4 and 8.
3. A legacy `curated.json` (format absent, `vpc` groups, node `service`, external `service`, bare `icon: "users"`)
   for a described diagram must still build. Test in Task 3.
4. An override file that is malformed JSON, names an unknown icon, or an address not in the facts: build reports it
   and refuses that override with a clear line, never a traceback, and the rest of the build continues. Test in
   Task 6.
5. A repo with both `aws_*` and `azurerm_*` resources plus `random_*`, `kubernetes_*` and a remote module: every
   resource gets the right cloud or none, `random_*` never reaches the facts. Test in Task 10.

---

### Task 1: Parity goldens (before any change)

**Files:**
- Create: `tests/golden/README.md` (two lines: what these are, how to regenerate)
- Create: `tests/golden/<case>.curated.json` and `tests/golden/<case>.drawio` for at least 4 cases
- Create: `tests/test_golden.py`

Cases, all built from curated dicts already used in `tests/test_layout.py`, `tests/test_externals.py`,
`tests/test_nesting.py` and `tests/test_drawio_format.py`: one with cloud/region/account/vpc/subnet frames, one with
an AWS managed-services external (`service` on an external), one with generic and brand icons, one with a node whose
`service` is `other` (plain box). Write each case's curated JSON exactly as today's format (format 1).

- [ ] **Step 1:** On the current code, write a throwaway script in the scratchpad that runs
  `tf_layout.layout(curated)` then `gen_drawio.render(diagram, page_id="golden", page_name="golden")` for each case
  and writes `tests/golden/<case>.drawio`. Do not commit the script.
- [ ] **Step 2: Write `test_golden.py`**

```python
@pytest.mark.parametrize("case", CASES)
def test_layout_and_render_match_the_golden(case):
    curated = load_curated(GOLDEN / f"{case}.curated.json")   # Task 3 makes this upgrade format 1
    diagram = tf_layout.layout(curated)
    assert gen_drawio.render(diagram, page_id="golden", page_name="golden") == (GOLDEN / f"{case}.drawio").read_text()
```

  Until Task 3, `load_curated` is `json.loads(path.read_text())`.
- [ ] **Step 3:** `uv run pytest tests/test_golden.py -q` passes. Commit `test: drawio parity goldens`.

### Task 2: Icon registry and the clouds package skeleton

**Files:**
- Create: `src/cartographer/icons.py`
- Create: `src/cartographer/clouds/__init__.py`, `src/cartographer/clouds/base.py`
- Create: `src/cartographer/clouds/aws/__init__.py`
- Move: `src/cartographer/aws_icons.json` -> `src/cartographer/clouds/aws/icons.json` (new shape below)
- Move: `src/cartographer/vendor_aws_icons.py` -> `src/cartographer/clouds/aws/vendor.py`
- Test: `tests/test_icons.py`

**Interfaces (Produces):**
- `clouds/aws/icons.json`: `{"<resIcon name>": {"fill": "#RRGGBB", "title": "<draw.io title>"}}`. Titles come from
  `Sidebar-AWS4.js` (the same file `vendor.py` reads); `vendor.py` writes both fields.
- `clouds/base.py`:
  - `class Cloud`: plain class, one instance per cloud. Attributes `name: str`, `label: str`,
    `providers: tuple[str, ...]`, `icons: dict[str, dict]` (loaded from its `icons.json`). Method
    `icon_style(name: str) -> str` (AWS: today's `_icon_style` AWS branch, byte-identical). Later tasks add members;
    each is listed in that task.
  - `def load_json(package_file: str, name: str) -> Any`: reads a JSON file next to the given `__file__`.
- `clouds/__init__.py`: `CLOUDS: dict[str, Cloud]` (`{"aws": AWS}` now), `def cloud_of_type(tf_type: str) -> Cloud | None`
  (provider prefix is the text before the first `_`; matched against each cloud's `providers`),
  `IGNORED_PROVIDERS = ("random", "tls", "time", "null", "local", "archive")`.
- `icons.py` (the only place icon names are looked up):
  - `def namespaces() -> tuple[str, ...]`: cloud names plus `"generic"`, `"brand"`.
  - `def known(icon: str | None) -> bool`
  - `def style(icon: str) -> str`: draw.io style. `generic:` and `brand:` use today's `_icon_style` branches,
    byte-identical; cloud icons delegate to `cloud.icon_style(name)`.
  - `def title(icon: str) -> str`: cloud icons from `icons.json`; generic and brand: the name with `_` -> space,
    title-cased.
  - `def cloud_of(icon: str) -> str | None`: the namespace when it is a cloud.
  - `def search(namespace: str, query: str, limit: int = 20) -> list[tuple[str, str]]`: (qualified name, title)
    pairs whose name or title contains every whitespace-separated query word, case-insensitive; exact name match
    first, then by name length, then name.
- `generic_icons.json` and `brand_icons.json` stay where they are; `diagram_model.AWS_ICONS`, `GENERIC_ICONS`,
  `BRAND_ICONS` and `has_icon` are deleted in Task 3, not here.

- [ ] **Step 1: Failing tests**

```python
def test_style_of_an_aws_icon_is_todays_style():
    assert icons.style("aws:lambda") == TODAY_LAMBDA_STYLE   # copy the string gen_drawio produces today
def test_generic_and_brand_styles_unchanged():
    assert icons.style("generic:users") == TODAY_USERS_STYLE and icons.style("brand:github") == BRAND_ICONS["github"]
def test_unknown_and_unqualified_names_are_not_known():
    assert not icons.known("lambda") and not icons.known("aws:nope") and not icons.known(None)
def test_title_uses_drawio_title():
    assert icons.title("aws:elasticsearch_service") == "OpenSearch Service"
def test_search_is_capped_and_ranked():
    hits = icons.search("aws", "s")
    assert len(hits) == 20
    assert icons.search("aws", "opensearch")[0] == ("aws:elasticsearch_service", "OpenSearch Service")
def test_cloud_of_type():
    assert clouds.cloud_of_type("aws_lambda_function").name == "aws" and clouds.cloud_of_type("random_id") is None
```

- [ ] **Step 2:** run, see them fail. **Step 3:** implement. **Step 4:** `uv run pytest tests/test_icons.py -q`
  passes and the full suite still passes (nothing consumes the registry yet). **Step 5:** commit
  `refactor: icon registry and clouds package`.

### Task 3: Curated format 2, qualified icons through layout and render

**Files:**
- Create: `src/cartographer/curated_format.py`
- Rename: `src/cartographer/tf_aws_externals.py` -> `src/cartographer/tf_externals.py`
- Modify: `curated.schema.json`, `tfdiagram.py`, `diagram_model.py`, `gen_drawio.py`, `tf_blocks.py`, `tf_lanes.py`,
  `tf_colors.py`, `tf_order.py`, `verify_shared.py`, `tf_network_check.py`, `tf_verify.py`, `verify_description.py`,
  `build.py`, `tf_layout.py`
- Modify tests that build curated dicts inline so they use format 2 (or pass through `upgrade`).
- Test: `tests/test_curated_format.py`, `tests/test_golden.py`

**Interfaces:**
- Curated format 2 (schema changes):
  - top-level `"format": {"const": 2}`, required.
  - group `kind` enum: `cloud`, `region`, `account`, `network`, `subnet`, null. Groups of those five kinds carry
    `cloud` (string, required by verify for those kinds, not by the schema). `cidrs` belongs to `network`.
  - node: `service` removed. `icon` optional, pattern `^[a-z]+:[a-z0-9_]+$`, description says: set only when the
    node's Terraform resources resolve to no icon (a non-cloud provider) or for a described node with no fitting
    `tf_type`; find names with `cartographer icons`.
  - node and external: optional `tf_type` (string) and `attributes` (object of strings), description says: a
    Terraform resource type the catalog resolves the icon from, for described nodes and managed-service externals.
  - external: `service` removed; `icon` optional (same pattern) or `"none"`.
  - no enum is injected anywhere; `tfdiagram.schema_text()` returns the file's JSON re-dumped with
    `indent=2, sort_keys=True`.
- `curated_format.upgrade(curated: dict) -> dict`: returns format 2. For a dict without `format`: `vpc` -> `network`;
  each group of a frame or network kind gets `cloud: "aws"`; node `service` X (not `other`) -> `icon: "aws:X"`, node
  `icon` Y -> `generic:Y` or `brand:Y` by which table has it, `none` removed; external `service` X ->
  `icon: "aws:X"`, external `icon` likewise. Format 2 input is returned unchanged. Build and `tf_verify.main` call it
  on every curated file they read.
- `diagram_model`: `Kind` uses `network`; `Group` gains `cloud: str | None = None`; `Icon.service` renamed
  `Icon.icon`; `AWS_ICONS`, `GENERIC_ICONS`, `BRAND_ICONS`, `has_icon` deleted (use `icons.known`).
- `Cloud` gains `frame_styles: dict[str, str]` keyed `cloud`, `region`, `account`, `network`, `subnet-public`,
  `subnet-private`, `subnet-isolated`, each the complete draw.io style. AWS values are exactly what `_group_style`
  builds today (the `vpc` entry becomes `network`). `gen_drawio._group_style` looks up
  `CLOUDS[g.cloud].frame_styles[key]` for a frame or network group; plain groups unchanged.
- `Cloud` gains `managed_label: str` (AWS: `"AWS managed services"`). `tf_externals.adopt(curated)`: externals whose
  `icon` belongs to a cloud are grouped per cloud into a block `g_<cloud>_managed` (AWS: `g_aws_managed`, unchanged)
  labelled `managed_label`, parent the first `region` group with that `cloud`; when that cloud has no region group,
  a new frame group `g_<cloud>_cloud` (kind `cloud`, label `cloud.label`, `cloud` set, parent None, column None)
  holds the block. Node dicts it creates carry `icon`, not `service`.
- `tf_colors.FRAMES` stays `("cloud", "region", "account")`; `CONTAINERS` uses `network`.
- `verify_shared.shape_warnings(item)`: warns when `icon` is set and not `icons.known(icon)`.
- In this task, a Terraform node's icon is still whatever the curated node says (`upgrade` filled it); Task 5
  replaces that with resolution from the facts.

- [ ] **Step 1: Failing tests**

```python
def test_upgrade_converts_a_format_1_file():
    old = {"view": "l7", "source": "description", "system": "S",
           "groups": [{"id": "v", "label": "VPC", "kind": "vpc", "parent": None, "column": 0}],
           "nodes": [{"id": "fn", "label": "fn", "service": "lambda", "group": "v", "tf": [], "multi": False},
                     {"id": "box", "label": "box", "service": "other", "icon": "users", "group": None, "tf": [], "multi": False}],
           "externals": [{"id": "ddb", "label": "t", "icon": "none", "service": "dynamodb", "evidence": []},
                         {"id": "gh", "label": "gh", "icon": "github", "evidence": []}],
           "edges": []}
    new = upgrade(old)
    assert new["format"] == 2 and new["groups"][0] | {} == {**old["groups"][0], "kind": "network", "cloud": "aws"}
    assert [n.get("icon") for n in new["nodes"]] == ["aws:lambda", "generic:users"]
    assert [x.get("icon") for x in new["externals"]] == ["aws:dynamodb", "brand:github"]
    assert "service" not in json.dumps(new)
def test_upgrade_leaves_format_2_alone():
    assert upgrade(F2) is F2 or upgrade(F2) == F2
def test_schema_has_no_injected_enum():
    assert "lambda" not in tfdiagram.schema_text()
def test_managed_external_of_a_cloud_without_region_gets_its_own_cloud_frame():
    ...  # azure icon external, only AWS frames present -> g_azure_cloud frame + g_azure_managed block
```

  (`azure` exists only from Task 8; use a stub cloud registered in the test via `monkeypatch.setitem(CLOUDS, ...)`.)
- [ ] **Step 2:** run, see them fail. **Step 3:** implement; switch `test_golden.load_curated` to
  `upgrade(json.loads(...))`. **Step 4:** `tests/test_golden.py` passes byte-identical, then the full suite.
  **Step 5:** commit `refactor: curated format 2 with qualified icons`.

### Task 4: Catalog, resolution and the AWS catalog

**Files:**
- Modify: `src/cartographer/clouds/base.py`
- Create: `src/cartographer/clouds/aws/catalog.json`, `provider_types.json`, `modules.json`, `rules.py`
- Modify: `src/cartographer/clouds/aws/vendor.py` (adds `--draft-catalog`: prints candidate rows for types with no
  row, never writes the catalog)
- Test: `tests/test_catalog.py`, `tests/test_aws_rules.py`

**Interfaces (Produces):**
- `base.py`:

```python
UNRESOLVED = object()   # the attribute exists but is not a literal (reference, local, var without default)
Getter = Callable[[str], str | None | object]   # attribute path such as "sku.tier" -> literal, None (absent) or UNRESOLVED

@dataclass(frozen=True)
class Resolution:
    kind: Literal["icon", "fold", "drop", "none"]
    icon: str | None = None        # qualified, e.g. "aws:elastic_load_balancing"
    decided_by: str = ""           # "catalog aws_s3_bucket", "rule aws_lb load_balancer_type = \"network\""
    marked: bool = False
    reason: str | None = None      # set when marked
    scope: Literal["regional", "global"] = "regional"
```

  `Catalog(rows: dict[str, dict])` with `row(tf_type) -> tuple[str, dict] | None`: longest key `k` with
  `tf_type == k or tf_type.startswith(k + "_")`. Row kinds: `{"icon": n, "rule": r?, "global": true?}`,
  `{"fold": "owner"}`, `{"drop": true}`, `{"generic": n, "why": text}` (icon `generic:n`).
  `Cloud` gains `catalog: Catalog`, `rules: dict[str, Callable[[Getter], Resolution | None]]` (None = rule does not
  apply, keep the row's icon), `modules: dict[str, str]` (source prefix -> icon name), and
  `def resolve(self, tf_type: str, get: Getter) -> Resolution`. No row: `Resolution("none", marked=True,
  reason="type not in catalog")`. A rule that reads `UNRESOLVED` returns the row's icon with `marked=True` and
  `reason=f"{attr} is not a literal"`.
  `def resolve_module(source: str) -> Resolution | None` at registry level in `clouds/__init__.py`: tries each
  cloud's `modules` by longest prefix; an unknown source is `Resolution("none", marked=True,
  reason="unknown module", decided_by="curator, unknown module")`.
- `provider_types.json`: sorted list of every resource type of `hashicorp/aws` 6.71.0, from the scratchpad
  `coverage/aws-resources.txt` (1,740 lines). Record the version in `vendor.py`'s docstring.
- `catalog.json`: a row for every type family. The folds are exactly today's `SUPPORT` regex in `tf_extract.py`
  (expanded to keys), nothing more. Draft with `--draft-catalog` and the scratchpad `coverage/aws-match.json`, then
  read every row: an icon must be the service's own icon (OpenSearch -> `elasticsearch_service`, AppConfig ->
  `app_config`, Managed Prometheus -> `managed_service_for_prometheus`, ELB classic `aws_elb` ->
  `elastic_load_balancing`). Billing, account and admin families with no icon get `generic` with `why`.
  `aws_cloudfront`, `aws_route53` (public zones), `aws_globalaccelerator` rows carry `"global": true`.
- `rules.py`: `aws_lb` and `aws_alb` (`load_balancer_type`: absent or `application` -> application LB icon,
  `network`, `gateway`), `aws_ecs_service` (`launch_type` FARGATE or a `capacity_provider_strategy` naming FARGATE ->
  `fargate`, else `elastic_container_service`), `aws_db_instance` and `aws_rds_cluster` (`engine` starting `aurora`
  -> `aurora`, else `rds`). Use icon names that exist in `icons.json`; check each with `icons.known`.
- `modules.json`: `terraform-aws-modules/<name>/aws` for at least `vpc`, `eks`, `rds`, `rds-aurora`, `lambda`,
  `s3-bucket`, `alb`, `sqs`, `sns`, `dynamodb-table`, `ecs`, `cloudfront`, `apigateway-v2`.

- [ ] **Step 1: Failing tests**

```python
def test_every_aws_provider_type_has_a_row():
    missing = [t for t in AWS.provider_types if AWS.catalog.row(t) is None]
    assert missing == []
def test_every_catalog_icon_exists():   # also modules.json
    assert [i for i in catalog_icons(AWS) if not icons.known(i)] == []
def test_longest_prefix_wins():
    assert AWS.resolve("aws_s3_bucket_policy", no_attrs).kind == "fold"
    assert AWS.resolve("aws_s3_bucket", no_attrs).icon == "aws:simple_storage_service"
def test_type_newer_than_the_list_resolves_to_family_or_none():
    assert AWS.resolve("aws_lambda_brand_new_thing", no_attrs).icon == "aws:lambda"
    r = AWS.resolve("aws_zzz_unknown", no_attrs)
    assert (r.kind, r.marked, r.reason) == ("none", True, "type not in catalog")
@pytest.mark.parametrize(("value", "icon"), [(None, APP_LB), ('application', APP_LB), ('network', NET_LB), ('gateway', GW_LB)])
def test_aws_lb_rule(value, icon): ...
def test_rule_with_unresolved_attribute_marks_and_keeps_base_icon():
    r = AWS.resolve("aws_lb", lambda a: UNRESOLVED)
    assert r.marked and r.icon == APP_LB and r.reason == "load_balancer_type is not a literal"
def test_module_sources():
    assert clouds.resolve_module("terraform-aws-modules/eks/aws").icon == "aws:elastic_kubernetes_service"
    assert clouds.resolve_module("git::https://example.com/x.git").decided_by == "curator, unknown module"
```

  plus one test each for the ECS and RDS rules, including their unresolved case.
- [ ] Steps 2 to 5 as usual. Commit `feat: reviewed AWS catalog with attribute rules`.

### Task 5: Cloud-neutral extraction, icons on facts, verify resolves node icons, `cartographer icons`

**Files:**
- Create: `src/cartographer/clouds/aws/network.py` (from `tf_network.py`), `src/cartographer/clouds/aws/permissions.py`
  (the IAM half of `tf_extract.py`: `principals`, `statements`, `iam`, `DATA_DOC`, `ROLE_KEYS`, `POLICY_TYPES`)
- Move: `tf_policies.py` stays core (policy JSON parsing is generic HCL work) but `unq`, `OPTS` keep their home.
- Delete: `src/cartographer/tf_network.py` once empty (shared helpers `_find`, `literal` go to `tf_extract` or a new
  `tf_values.py`).
- Modify: `tf_extract.py`, `tf_hints.py`, `tf_verify.py`, `tf_network_check.py`, `cli.py`
- Test: `tests/test_extract.py`, `tests/test_network.py`, `tests/test_network_verify.py`, `tests/test_cli.py`,
  `tests/test_core_has_no_cloud_checks.py`

**Interfaces:**
- `Spec` moves to `clouds/base.py`. `Cloud` gains `edge_specs: dict[str, list[Spec]]`, `network_attrs: frozenset[str]`,
  `data_ref_types: frozenset[str]` (AWS: `aws_iam_policy_document`, whose body `Extractor.refs` follows),
  `param_types: frozenset[str]` (moved from `tf_hints.PARAM_TYPES`), `def network_facts(self, ex) -> dict` returning
  `{"networks": [...], "placements": [...]}` without ids, `def permission_edges(self, ex) -> None` (adds through
  `ex.add` and `ex.services`), `def extra(self, ex, res) -> dict` (AWS: `{}`).
- `Extractor`:
  - `def value(self, inst, expr) -> str | None | object`: the literal an expression is, through `local.`, module
    arguments and `variable` defaults (today's `Network.literal` without the CIDR check), `UNRESOLVED` otherwise.
  - `def getter(self, res) -> Getter`: dotted paths into the resource body, first list element for blocks.
  - Resolves every resource once: `self.resolution: dict[str, Resolution]`; `drop` resources are removed from
    `self.res` before edges are made; resources of `IGNORED_PROVIDERS` are dropped the same way; `module`
    resources use `resolve_module(source)`; other providers get `Resolution("none")` unmarked.
  - Fold replaces `SUPPORT`: a `uses` edge is skipped when either end resolved to `fold`.
  - Merges `edge_specs`, `network_attrs`, `data_ref_types` of the clouds present.
  - `run()` emits per resource: `cloud` (name or omitted), `icon` or `fold: "owner"`, `marked`, `reason`,
    `decided_by`, `global` when true, plus `cloud.extra(...)`. `networks` and `placements` are the concatenation
    over clouds, ids `n1..` and `p1..`, each item carrying `cloud`; a placement names `network` (an id), not `vpc`.
- `tf_verify.verify`: `facts_by_id` over `edges`, `networks`, `placements`. For each kept node, the icon is the
  first `tf` address (in listed order) whose facts resource has `icon`; then the node's own `icon` when no address
  resolves; record `decided_by`, `marked` on the verified node. Warning when a curator `icon` is set on a node whose
  resources resolve (`resolved icon wins`), and when every `tf` address is a fold (`built only from folded
  resources`). Frame and network groups without `cloud` are demoted with a note; a node whose icon's cloud differs
  from its enclosing frame's `cloud` is a warning.
- `clouds/__init__.py`: `def resolve_declared(tf_type: str, attributes: dict[str, str]) -> Resolution`: the owning
  cloud's `resolve` with a getter over `attributes` (`none`, marked, when no cloud owns the type). Both
  `tf_verify` (externals) and `verify_description` (nodes and externals) set `icon`, `decided_by` and `marked`
  from it when an item names `tf_type`; an item naming a cloud `icon` directly gets `marked: true`,
  `decided_by: "curator"`. This happens before `tf_externals.adopt`, which therefore only reads `icon`.
- `cli.py`: `cartographer icons --cloud <namespace> --search <words>` prints `name<TAB>title` lines from
  `icons.search`, at most 20; exit 0 with no output when nothing matches. Unnamed command (no `--name`).
- `tests/test_core_has_no_cloud_checks.py`: every `src/cartographer/*.py` (not `clouds/`) is free of the patterns
  `"aws_`, `'aws_`, `"azurerm`, `"azapi`, `== "aws"`, `== "azure"`; allowlist only `curated_format.py` (format 1 is
  AWS by definition).

- [ ] **Step 1: Failing tests** (keep every existing extract and network test; update their expected facts keys)

```python
def test_resources_carry_cloud_and_icon(mini_facts):
    fn = by_address(mini_facts, "aws_lambda_function.x")
    assert (fn["cloud"], fn["icon"], fn["marked"]) == ("aws", "aws:lambda", False)
def test_random_resources_never_reach_the_facts(): ...
def test_uses_edges_skip_folded_types(): ...       # same edges as today's SUPPORT behaviour on tests/fixtures/mini
def test_networks_replace_vpcs(network_facts):
    assert "vpcs" not in network_facts and network_facts["networks"][0]["cloud"] == "aws"
def test_verify_takes_the_icon_from_the_first_resolved_address(): ...
def test_verify_warns_on_a_node_built_only_from_folds(): ...
def test_icons_command_prints_at_most_20(capsys): ...
def test_core_has_no_cloud_checks(): ...
```

- [ ] Steps 2 to 4; the full suite passes; `wc -l src/cartographer/tf_extract.py` is under 300. Commit
  `refactor: cloud-neutral extraction with resolved icons`.

### Task 6: Overrides, build report, review sheet and tile map

**Files:**
- Create: `src/cartographer/overrides.py`, `src/cartographer/review_sheet.py`
- Modify: `build.py`, `snapshot.py`, `src/cartographer/REVIEW.md`
- Test: `tests/test_overrides.py`, `tests/test_review_sheet.py`, `tests/test_snapshot.py`

**Interfaces:**
- Override file: `<out>/icons.json` (default `docs/architecture/diagrams/icons.json`), shape in the spec.
- `overrides.py`:
  - `@dataclass(frozen=True) class Override: cloud: str; type: str; icon: str; reason: str; address: str | None`
  - `def load(path: Path) -> tuple[list[Override], list[str]]`: missing file -> `([], [])`; bad JSON, a missing
    field, an empty `reason` -> that entry skipped with a problem line naming its index.
  - `def apply(verified: dict, facts: dict | None, overrides: list[Override]) -> list[str]`: icon must satisfy
    `icons.known(f"{cloud}:{icon}")`; `address` must be a facts address of that `type`; type-wide overrides need the
    type in the facts. Address beats type. Sets the node's `icon`, `override` (the reason) and
    `decided_by = "override"`. Returns problem and applied lines. Described diagrams (`facts` None) accept
    type-wide overrides matched on node `tf_type`.
- `build.py` order: verify -> overrides -> layout -> render -> write. The report printed after the first line gains
  sections `Marked icons`, `Overrides`, `Icon changes` (cell id: old -> new, comparing `resIcon=`, `shape=` and
  `image=` values of the previous `.drawio` with the new one; nothing when there was no previous file).
  Overrides are not in `inputs_sha256`.
- `review_sheet.write(cache: Path, verified: dict, facts: dict | None, diagram: Diagram) -> Path` writes
  `cache/review.json` with `view`, `view_name` (from `tfdiagram.VIEW_NAMES`, value `"Layer 7: services and how they
  call each other"`), `clouds`, and one entry per node and external drawn as an icon: `id`, `label`, `cloud`,
  `icon`, `icon_title`, `tf` (address, type, file, line from the facts), `decided_by`, `marked`, `override`,
  `frame` (`" > "` joined labels of the enclosing groups, outermost first), `tiles` (empty until snapshot).
- `snapshot.snapshot(...)` also writes `<out_dir>/tiles.json`: `{"<tile png name>": [cell ids whose icon rect
  intersects the tile]}`, from the `.drawio` geometry already parsed by `window_size`. When
  `cache_dir(<drawio stem>)/review.json` exists, fill each entry's `tiles`.
- `REVIEW.md`: a `## View l7` heading over today's rules; a top paragraph: read `review.json` first, apply only the
  section of its `view`, review `marked` entries first, judge each icon against its `tf` types and `icon_title`; an
  icon fix is `cartographer icons` then an override with a reason, then `build` (never re-curate for an icon).
  Rule 2 and 7 lose `aws_icons.json` and `service` wording.

- [ ] **Step 1: Failing tests**

```python
def test_bad_override_file_is_reported_not_raised(tmp_path): ...   # Review Focus 4: bad JSON, unknown icon, unknown address
def test_address_override_beats_type_override(): ...
def test_overrides_do_not_change_the_cache_key(): ...
def test_review_sheet_has_one_entry_per_drawn_icon(): ...           # every Icon id in the Diagram appears once
def test_tiles_json_maps_icons_to_tiles(): ...                      # pure function on a small mxfile, no Chrome
```

- [ ] Steps 2 to 5. Commit `feat: icon overrides, review sheet and tile map`.

### Task 7: Several frame trees in one layout

**Files:**
- Modify: `src/cartographer/tf_blocks.py` (replace `_frame_chain`/`place_frames` with a recursive frame placement)
- Test: `tests/test_nesting.py`, `tests/test_golden.py`, new `tests/test_multi_frame.py`

**Interfaces:**
- `Blocks.place_frames(x, y) -> Size` keeps its signature. Frames form a forest. A frame's content is its child
  frames side by side (left to right in id order of first appearance in `curated["groups"]`, `BLOCK_GAP` apart)
  followed, to their right, by its own blocks and loose nodes laid out by `_columns`. A frame with exactly one child
  frame and no blocks parented to it directly passes its blocks down, and blocks or nodes parented to an ancestor in
  a single-child chain go to the innermost frame of that chain: this keeps one chain byte-identical to today.
  Blocks and nodes with no frame ancestor go to the first top-level tree. Top-level trees are placed side by side.
  Padding and sizing per frame are today's `FRAME_PAD_X`, `FRAME_PAD_TOP`.

- [ ] **Step 1: Failing tests**

```python
def test_two_clouds_side_by_side_do_not_overlap(): ...     # AWS cloud+region and Azure cloud+region, a block each
def test_two_regions_in_one_cloud(): ...
def test_cross_cloud_edge_has_no_rule_violations():
    diagram = tf_layout.layout(TWO_CLOUDS)   # one edge from an AWS node to an Azure node
    assert measure(gen_drawio.render(diagram, page_id="p", page_name="p")).violations() == 0  # use tf_check's API
```

- [ ] Steps 2 to 4; goldens still byte-identical; full suite passes. Commit `feat: several frame trees in one layout`.

### Task 8: Azure icons, catalog, ARM types, modules and rules

**Files:**
- Create: `src/cartographer/clouds/azure/__init__.py`, `icons.json`, `provider_types.json`, `catalog.json`,
  `arm_types.json`, `modules.json`, `rules.py`, `vendor.py`
- Modify: `src/cartographer/clouds/__init__.py` (register `azure`)
- Test: `tests/test_azure_catalog.py`, `tests/test_azure_rules.py`

**Interfaces:**
- `AZURE.name = "azure"`, `label = "Azure"`, `providers = ("azurerm", "azapi")`, `managed_label = "Azure managed
  services"`. `azuread` is not a provider of any cloud for icons.
- `icons.json`: `{"<name>": {"path": "<category>/<File>.svg", "title": "<File with _ as spaces>"}}` from
  draw.io 32.5.5 `img/lib/azure2/` (scratchpad `coverage/azure_icons.json` and `azure-icon-paths.txt` are a draft;
  `vendor.py` regenerates from the bundled draw.io folder). Confirm the bundled draw.io serves
  `img/lib/azure2/...`; if it does not, stop and report.
- `icon_style(name)`: `image;aspect=fixed;html=1;points=[];align=center;fontSize=12;image=img/lib/azure2/<path>;`
  plus `verticalLabelPosition=bottom;verticalAlign=top;` so labels sit below like AWS icons.
- `frame_styles`: plain rounded or dashed rectangles with Azure colours (`#0078D4` cloud and network, region
  dashed), the Azure icon at the frame title where draw.io has a group style; labels: Azure, Region, Subscription,
  Virtual network, subnet tiers.
- `provider_types.json`: `hashicorp/azurerm` 5.12.0 from `coverage/azurerm-resources.txt` (1,107), plus
  `azapi_resource`, `azapi_update_resource`, `azapi_data_plane_resource`.
- `catalog.json`: type-family rows reviewed one by one (Azure registry groups are too coarse to map, see spec).
  Folds from the spec's Fold list; `azurerm_frontdoor`, `azurerm_cdn_frontdoor`, `azurerm_traffic_manager`,
  `azurerm_dns` rows `"global": true`. `azurerm_resource_group` is `generic` with why "resource groups are not drawn".
- `rules.py`: the spec's Attribute rules table rows for `azurerm_lb`, `azurerm_application_gateway`,
  `azurerm_cognitive_account`, `azurerm_storage_account`, `azurerm_cosmosdb_account`, `azapi_resource` (`type` with
  `@version` stripped, looked up in `arm_types.json`; unknown ARM type -> `none`, marked).
- `arm_types.json`: ARM type -> icon name for the ARM types behind every catalog icon row, at least those of the
  35 `azapi_resource` types seen in the samples.
- `modules.json`: `Azure/avm-res-<provider>-<resource>/azurerm` resolves through `arm_types.json`; `Azure/avm-ptn-`
  prefixes resolve to unknown.

- [ ] **Step 1: Failing tests**: completeness and icon-existence tests as in Task 4 for Azure (catalog, arm types,
  modules); one test per rule including its unresolved case; `azurerm_virtual_machine` and
  `azurerm_virtual_network` resolve to different rows; `azapi_resource` with
  `type = "Microsoft.App/containerApps@2024-03-01"` resolves to the Container Apps icon; an AVM pattern module is
  unknown and marked.
- [ ] Steps 2 to 5. Commit `feat: Azure icons and reviewed catalog`.

### Task 9: Azure network facts

**Files:**
- Create: `src/cartographer/clouds/azure/network.py`
- Test: `tests/test_azure_network.py`, fixtures `tests/fixtures/azure/<case>/main.tf` (synthetic)

**Interfaces:** `AZURE.network_facts(ex)` returns `networks` (local `azurerm_virtual_network`, remote ones via
`data.azurerm_virtual_network`, peering `remote_virtual_network_id`, `tfe_outputs`/`terraform_remote_state`
outputs), `cidrs` from literal `address_space`, and `placements` with `tier` and `via` exactly per the spec's
"Subnet tiers" and "Placement edge cases". VNet integration (`virtual_network_subnet_id`) is never a placement; it
emits an edge fact kind `network`, detail `virtual_network_subnet_id`, app -> subnet resource. Private endpoints
are placed in their subnet. Tier decisions record `via` (`"<subnet address> nat gateway"`, `"... reserved name
GatewaySubnet"`, `"... default_outbound_access_enabled = false"`, `"... name"`, `"... default"`).

- [ ] **Step 1: Failing tests**, one fixture each: public by NIC public IP; public by reserved subnet names (three);
  private by NAT association, by LB outbound rule, by UDR `0.0.0.0/0` to `VirtualAppliance`; isolated by
  `default_outbound_access_enabled = false`; fallback by name and default; inline and separate subnets; VM via NIC;
  scale set; private endpoint placed, its service not placed; Web App with VNet integration not placed and has the
  `network` edge; Flexible Server with `delegated_subnet_id` placed; two peered VNets as two networks; the
  `default_outbound_access_enabled` attribute absent is never read as isolated.
- [ ] Steps 2 to 5. Commit `feat: Azure network facts`.

### Task 10: Azure permissions, triggers, routes, location and subscription

**Files:**
- Create: `src/cartographer/clouds/azure/permissions.py`, `src/cartographer/clouds/azure/specs.py`
- Test: `tests/test_azure_extract.py`, fixture `tests/fixtures/azure/mixed/` (AWS and Azure resources, `random_*`,
  a `kubernetes_*` resource, a remote AVM module)

**Interfaces:**
- `AZURE.permission_edges(ex)`: role assignments and Key Vault access policies per the spec's Permissions section;
  edge kind `iam` (the existing kind, so verify and RULES treat both clouds alike), detail the role name; a scope
  that is a subscription or resource group adds to `ex.services` under service `"azure:<role>"`.
- `AZURE.edge_specs`: the spec's minimum trigger and route specs.
- `AZURE.extra(ex, res)`: `location` (literal, or the referenced resource group's literal location) and
  `subscription` (the `subscription_id` literal of the resource's provider block, by alias; `null` when not a
  literal). `parse_module` must also read `provider` blocks: `Module.providers: dict[str, dict]` keyed
  `azurerm` / `azurerm.<alias>`.

- [ ] **Step 1: Failing tests**: role assignment from a system identity and from a user-assigned identity; scope a
  resource group -> services entry; Event Grid subscription trigger; Front Door origin route; location through the
  resource group; aliased provider subscription; and Review Focus 5 on the mixed fixture (clouds, drops, none).
- [ ] Steps 2 to 5; full suite passes. Commit `feat: Azure permissions, triggers and routes`.

### Task 11: Prompts, rules, skill and docs

**Files:** `src/cartographer/curate_prompt.md`, `describe_prompt.md`, `INTERVIEW.md`, `RULES.md`, `REVIEW.md`,
`skills/cartographer/SKILL.md`, `DESIGN.md`, `README.md`, `.claude-plugin/plugin.json` description.

- Curation: icons come from the facts; set node `icon` only for unresolved resources, found with
  `cartographer icons`; managed-service externals name `tf_type` (and `attributes`); frames carry `cloud`; one
  top-level frame per cloud; Azure placement rules (VNet integration outside subnets, private endpoints in subnets,
  global services outside regions, resource groups never drawn).
- Describe: the interview asks which cloud or clouds; Azure tier defaults recorded in `assumptions`.
- Skill: the review loop reads `review.json` first, then tiles; the fix step for icons is override + `build`;
  curation fixes stay as today. The skill and plugin description say AWS and Azure.
- `DESIGN.md`: the per-cloud structure and the catalog; README: Azure support, the override file, `cartographer icons`.
- No em or en dashes in any of these files' changed lines. `tests/test_plugin.py` keeps passing.
- [ ] Commit `docs: multi-cloud and Azure in prompts, skill and docs`.

### Task 12: Smoke and finish

- [ ] Run extraction over every sample folder in the scratchpad `azure-samples/terraform/quickstart/*` with
  `python -I` from a script in the scratchpad (not the samples folder). Expected: no exception; a non-empty
  `networks` for every sample that declares `azurerm_virtual_network`; count of `marked` resources reported.
  Fix catalog gaps found; do not commit the script or samples.
- [ ] `uv run ruff check`, `uv run pytest -q`: both clean. `find src -name '*.py' | xargs wc -l | sort -n | tail -3`:
  nothing over 1,000.
- [ ] Commit any fixes `fix: catalog gaps from the Azure samples smoke run`.
