from pathlib import Path

import pytest

from cartographer import tf_extract

REPO = Path(__file__).parent / "fixtures" / "network"


def _facts() -> dict:
    return tf_extract.extract(Path("infra"), REPO)


def _vpcs() -> dict[str, dict]:
    return {v["address"]: v for v in _facts()["networks"]}


def _placements() -> dict[str, dict]:
    return {p["resource"]: p for p in _facts()["placements"]}


def test_local_vpc_cidrs_from_locals_associations_and_defaults() -> None:
    vpcs = _vpcs()
    assert vpcs["aws_vpc.main"]["cidrs"] == ["10.30.0.0/16", "10.31.0.0/20"]
    assert vpcs["aws_vpc.main"]["remote"] is False
    assert vpcs["aws_vpc.main"]["name"] == "main"
    assert vpcs["aws_vpc.main"]["file"] == "infra/main.tf"
    assert vpcs["aws_vpc.spare"]["cidrs"] == ["10.99.0.0/16"]


def test_unresolvable_cidr_gives_no_cidrs() -> None:
    assert _vpcs()["aws_vpc.dyn"]["cidrs"] == []


def test_remote_vpc_found_through_module_variable() -> None:
    remote = [v for v in _vpcs().values() if v["remote"]]
    assert len(remote) == 1
    assert remote[0]["address"] == "data.tfe_outputs.networking.nonsensitive_values.shared_vpc_id"
    assert remote[0]["name"] == "shared-vpc"
    assert remote[0]["cidrs"] == []
    assert "stack" not in remote[0]


def test_local_subnet_tiers() -> None:
    placements = _placements()
    assert placements["aws_lb.front"]["tier"] == "public"
    assert "map_public_ip_on_launch" in placements["aws_lb.front"]["via"]
    assert placements["aws_instance.orders"]["tier"] == "private"
    assert placements["aws_db_instance.ledger"]["tier"] == "isolated"
    assert placements["aws_instance.misc"]["tier"] == "private"
    vpcs = {v["id"]: v["address"] for v in _facts()["networks"]}
    assert vpcs[placements["aws_lb.front"]["network"]] == "aws_vpc.main"


def test_interpolated_subnet_names_still_inform_the_tier(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'variable "env" { default = "dev" }\n'
        'resource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_subnet" "a" {\n  vpc_id = aws_vpc.v.id\n  tags = { Name = "${var.env}-public" }\n}\n'
        'resource "aws_instance" "i" { subnet_id = aws_subnet.a.id }\n')
    placed = {p["resource"]: p for p in tf_extract.extract(Path("."), tmp_path)["placements"]}
    assert placed["aws_instance.i"]["tier"] == "public"


def test_remote_tier_from_output_name_through_module_variable() -> None:
    placement = _placements()["module.worker.aws_lambda_function.fn"]
    assert placement["tier"] == "private"
    vpcs = {v["id"]: v["name"] for v in _facts()["networks"]}
    assert vpcs[placement["network"]] == "shared-vpc"
    assert placement["file"] == "infra/modules/worker/main.tf"


def test_undecidable_or_unmatched_placements_are_skipped() -> None:
    placements = _placements()
    assert "aws_instance.lost" not in placements
    assert "aws_instance.outside" not in placements
    assert "aws_route_table_association.front" not in placements
    assert "module.worker.aws_security_group.sg" not in placements


def test_fact_ids_do_not_clash() -> None:
    facts = _facts()
    ids = [f["id"] for key in ("edges", "hints", "networks", "placements") for f in facts[key]]
    assert len(ids) == len(set(ids))


def test_networks_replace_vpcs() -> None:
    facts = _facts()
    assert "vpcs" not in facts and facts["networks"][0]["cloud"] == "aws"
    assert [n["id"] for n in facts["networks"]] == [f"n{i}" for i in range(1, len(facts["networks"]) + 1)]
    assert all(p["cloud"] == "aws" for p in facts["placements"])


def _two_modules(tmp_path: Path, a: str, b: str | None = None, root: str = 'module "a" { source = "./a" }\nmodule "b" { source = "./b" }\n') -> dict:
    """Facts of a root that calls modules `a` and `b`, with bodies `a` and `b` (`a` for both by default)."""
    for name, body in (("a", a), ("b", a if b is None else b)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.tf").write_text(body)
    (tmp_path / "main.tf").write_text(root)
    return tf_extract.extract(Path("."), tmp_path)


def _remote_state(config: str, extra: str = "", name: str = "net", ref: str = "net") -> str:
    return (f'data "terraform_remote_state" "{name}" {{\n  backend = "s3"\n{extra}  config = {config}\n}}\n'
            f'resource "aws_security_group" "sg" {{ vpc_id = data.terraform_remote_state.{ref}.outputs.shared_vpc_id }}\n')


def _tfe(workspace: str, organization: str = "acme", name: str = "net") -> str:
    return (f'data "tfe_outputs" "{name}" {{\n  organization = "{organization}"\n  workspace = "{workspace}"\n}}\n'
            f'resource "aws_security_group" "sg" {{ vpc_id = data.tfe_outputs.{name}.values.shared_vpc_id }}\n')


ONPREM = 'provider "tfe" {\n  alias = "corp"\n  hostname = "tfe.corp.example"\n}\n'
APP = 'provider "tfe" {\n  alias = "app"\n  hostname = "app.terraform.io"\n}\n'
KEY = '{ bucket = "states", key = "networking/terraform.tfstate" }'
INDEXED = ('data "terraform_remote_state" "net" {{\n  count = 2\n  backend = "s3"\n  config = {{ key = "n.tfstate" }}\n}}\n'
           'resource "aws_security_group" "sg" {{ vpc_id = data.terraform_remote_state.net[{index}].outputs.shared_vpc_id }}\n')


@pytest.mark.parametrize(("a", "b", "networks"), [
    (_remote_state(KEY), None, 1),
    (_remote_state('{ key = "a/terraform.tfstate" }'), _remote_state('{ key = "./a/terraform.tfstate" }'), 2),
    (_remote_state(KEY, '  workspace = "default"\n'), _remote_state(KEY), 1),
    (_remote_state(KEY, '  workspace = "prod"\n'), _remote_state(KEY, '  workspace = "dev"\n'), 2),
    (_remote_state('{ bucket = "default", key = "n" }'), _remote_state('{ bucket = "other", key = "n" }'), 2),
    (_remote_state(KEY), _remote_state(KEY, name="other", ref="other"), 1),  # one state under two data source names
    (_remote_state('{ key = "${var.env}/net.tfstate" }'), None, 2),  # not a literal: one per module
    (_remote_state("local.state").replace("data", 'locals {\n  state = { key = "n" }\n}\ndata', 1), None, 1),
    (INDEXED.format(index="0"), INDEXED.format(index="1"), 2),
    (INDEXED.format(index="0"), None, 1),
    (INDEXED.format(index="count.index"), None, 2),  # not a literal index: one per module
    (_tfe("networking"), None, 1),
    (_tfe("networking"), _tfe("networking", organization="other"), 2),
    (_tfe("default"), _tfe("networking"), 2),  # a tfe workspace named default is a workspace like any other
    (_tfe("n").replace("{\n", '{\n  provider = tfe.corp\n', 1) + ONPREM, _tfe("n"), 2),  # two hosts, one workspace name
    (_tfe("n").replace("{\n", '{\n  provider = tfe.app\n', 1) + APP, _tfe("n"), 1),  # the default host, named
    (_tfe("n").replace("{\n", '{\n  provider = tfe.nowhere\n', 1), None, 2),  # an undeclared provider: one per module
    ('resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.net.values.shared_vpc_id }\n', None, 2),  # no block
    (_remote_state("var.cfg"), None, 2),  # a config that cannot be read: one per module, never one by backend alone
    (_remote_state("local.all.net").replace("data", 'locals {\n  all = { net = { key = "n" } }\n}\ndata', 1), None, 2),
    (_remote_state('merge(local.base, { key = "n" })'), None, 2),
])
def test_state_identity(tmp_path: Path, a: str, b: str | None, networks: int) -> None:
    facts = _two_modules(tmp_path, a, b)
    assert len(facts["networks"]) == networks
    assert all(n["remote"] and "stack" not in n for n in facts["networks"])


WORKSPACE_FROM_A_VARIABLE = (
    'variable "ws" {\n  default = "platform"\n}\n'
    'data "tfe_outputs" "net" {\n  organization = "acme"\n  workspace = var.ws\n}\n'
    'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.net.values.shared_vpc_id }\n')


@pytest.mark.parametrize(("root", "networks"), [
    ('module "a" {\n  source = "./a"\n  ws = "networking"\n}\nmodule "b" {\n  source = "./b"\n  ws = "networking"\n}\n', 1),
    ('module "a" {\n  source = "./a"\n  ws = "networking"\n}\nmodule "b" {\n  source = "./b"\n  ws = "platform"\n}\n', 2),
    ('module "a" {\n  source = "./a"\n  ws = "platform"\n}\nmodule "b" {\n  source = "./b"\n}\n', 1),  # the default agrees
])
def test_settings_passed_through_module_variables(tmp_path: Path, root: str, networks: int) -> None:
    assert len(_two_modules(tmp_path, WORKSPACE_FROM_A_VARIABLE, root=root)["networks"]) == networks


@pytest.mark.parametrize("second", ['  ws = "platform"\n', ""])
def test_calls_of_one_module_instance_that_disagree_fall_back_to_its_address(tmp_path: Path, second: str) -> None:
    root = f'module "x" {{\n  source = "./a"\n  ws = "networking"\n}}\nmodule "y" {{\n  source = "./a"\n{second}}}\n'
    facts = _two_modules(tmp_path, WORKSPACE_FROM_A_VARIABLE, root=root)
    assert [n["address"] for n in facts["networks"]] == ["module.a.data.tfe_outputs.net.values.shared_vpc_id"]


@pytest.mark.parametrize("second", ['  providers = { tfe = tfe.us }\n', ""])
def test_calls_of_one_module_instance_that_map_the_tfe_provider_differently_fall_back_to_its_address(
        tmp_path: Path, second: str) -> None:
    root = ('provider "tfe" {\n  alias = "eu"\n  hostname = "tfe.eu.example"\n}\n'
            'provider "tfe" {\n  alias = "us"\n  hostname = "tfe.us.example"\n}\n'
            f'module "x" {{\n  source = "./a"\n  providers = {{ tfe = tfe.eu }}\n}}\nmodule "y" {{\n  source = "./a"\n{second}}}\n'
            + _tfe("n", name="root").replace('"sg"', '"root_sg"'))
    facts = _two_modules(tmp_path, _tfe("n"), root=root)
    assert sorted(n["address"] for n in facts["networks"]) == [
        "data.tfe_outputs.root.values.shared_vpc_id", "module.a.data.tfe_outputs.net.values.shared_vpc_id"]


def test_other_values_read_the_first_call(tmp_path: Path) -> None:
    facts = _two_modules(
        tmp_path, 'variable "cidr" {}\nresource "aws_vpc" "v" { cidr_block = var.cidr }\n',
        root='module "x" {\n  source = "./a"\n  cidr = "10.0.0.0/16"\n}\nmodule "y" {\n  source = "./a"\n  cidr = "10.1.0.0/16"\n}\n')
    assert [n["cidrs"] for n in facts["networks"]] == [["10.0.0.0/16"]]


def _placed(facts: dict, field: str = "address") -> dict[str, str]:
    network = {n["id"]: n[field] for n in facts["networks"]}
    return {p["resource"]: network[p["network"]] for p in facts["placements"]}


def test_a_remote_subnet_goes_to_the_vpc_of_its_own_state_first(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        _tfe("networking", name="networking") + _tfe("platform", name="platform").replace('"sg"', '"sg2"')
        + 'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.networking.values.shared_vpc_private_subnet_ids }\n}\n'
        'resource "aws_lambda_function" "b" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.platform.values.shared_vpc_private_subnet_ids }\n}\n'
        'resource "aws_lambda_function" "c" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.other.values.shared_vpc_private_subnet_ids }\n}\n')
    placed = _placed(tf_extract.extract(Path("."), tmp_path))
    assert placed["aws_lambda_function.a"] == "data.tfe_outputs.networking.values.shared_vpc_id"
    assert placed["aws_lambda_function.b"] == "data.tfe_outputs.platform.values.shared_vpc_id"
    assert "aws_lambda_function.c" not in placed  # no VPC of its own state: never one of another state


def test_modules_that_read_one_state_share_its_network_and_each_state_keeps_its_subnets(tmp_path: Path) -> None:
    body = ('resource "aws_lambda_function" "fn" {\n'
            '  vpc_config { subnet_ids = data.tfe_outputs.net.values.shared_vpc_private_subnet_ids }\n}\n')
    for case in ("same", "apart"):
        (tmp_path / case).mkdir()
    same = _two_modules(tmp_path / "same", _tfe("networking") + body)
    assert len(same["networks"]) == 1 and len(same["placements"]) == 2
    apart = _two_modules(tmp_path / "apart", _tfe("net-a") + body, _tfe("net-b") + body)
    assert len(apart["networks"]) == 2 and len(set(_placed(apart, "id").values())) == 2


def test_a_remote_subnet_falls_back_to_a_looked_up_vpc(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared_vpc.id }\n'
        'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.networking.values.shared_vpc_private_subnet_ids }\n}\n')
    assert _placed(tf_extract.extract(Path("."), tmp_path)) == {"aws_lambda_function.a": "data.aws_vpc.shared_vpc"}


def test_a_subnet_lookup_falls_back_to_a_remote_vpc(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.aws_subnets.shared_vpc_private.ids }\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [(p["resource"], p["tier"]) for p in facts["placements"]] == [("aws_lambda_function.a", "private")]


def test_a_subnet_in_one_module_belongs_to_a_remote_vpc_another_module_reads(tmp_path: Path) -> None:
    facts = _two_modules(
        tmp_path, _tfe("networking", name="networking"),
        _tfe("networking", name="networking").replace('"aws_security_group" "sg"', '"aws_subnet" "private"')
        + 'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = [aws_subnet.private.id] }\n}\n')
    assert [n["address"] for n in facts["networks"]] == ["module.a.data.tfe_outputs.networking.values.shared_vpc_id"]
    assert [p["resource"] for p in facts["placements"]] == ["module.b.aws_lambda_function.fn"]


def test_a_subnet_lookup_goes_to_the_remote_vpc_with_the_longest_name(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "a" { vpc_id = data.aws_vpc.shared.id }\n'
        'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.shared_vpc_private.ids }\n}\n')
    assert _placed(tf_extract.extract(Path("."), tmp_path), "name") == {"aws_lambda_function.fn": "shared-vpc"}


def test_two_modules_that_look_up_a_vpc_under_one_name_give_two_networks(tmp_path: Path) -> None:
    facts = _two_modules(
        tmp_path,
        'variable "name" {}\n'
        'data "aws_vpc" "main" {\n  tags = { Name = var.name }\n}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n',
        root='module "a" {\n  source = "./a"\n  name = "shop"\n}\nmodule "b" {\n  source = "./b"\n  name = "bank"\n}\n')
    assert [n["address"] for n in facts["networks"]] == ["module.a.data.aws_vpc.main", "module.b.data.aws_vpc.main"]


def test_a_subnet_lookup_stays_with_the_vpc_its_own_module_looks_up(tmp_path: Path) -> None:
    facts = _two_modules(
        tmp_path,
        'data "aws_vpc" "main" {}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n'
        'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.main_private.ids }\n}\n')
    assert _placed(facts) == {"module.a.aws_lambda_function.fn": "module.a.data.aws_vpc.main",
                              "module.b.aws_lambda_function.fn": "module.b.data.aws_vpc.main"}


def test_a_remote_subnet_read_in_a_module_goes_to_the_longest_name_not_to_a_root_lookup(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared_vpc.id }\n'
        'resource "aws_lambda_function" "fn" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.net.values.shared_vpc_private_subnet_ids }\n}\n')
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared.id }\nmodule "a" {\n  source = "./a"\n}\n')
    assert list(_placed(tf_extract.extract(Path("."), tmp_path)).values()) == ["module.a.data.aws_vpc.shared_vpc"]


def test_a_module_named_data_keeps_the_lookups_of_its_submodules_apart(tmp_path: Path) -> None:
    for name in ("x", "y"):
        (tmp_path / "data" / name).mkdir(parents=True)
        (tmp_path / "data" / name / "main.tf").write_text(
            'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n'
            'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.main_private.ids }\n}\n')
    (tmp_path / "data" / "main.tf").write_text('module "x" {\n  source = "./x"\n}\nmodule "y" {\n  source = "./y"\n}\n')
    (tmp_path / "main.tf").write_text('module "data" {\n  source = "./data"\n}\n')
    placed = _placed(tf_extract.extract(Path("."), tmp_path))
    assert len(placed) == 2 and all(vpc.startswith(fn.removesuffix("aws_lambda_function.fn")) for fn, vpc in placed.items())


def test_a_root_subnet_lookup_stays_with_the_root_vpc_lookup_of_the_same_name(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "a" { vpc_id = data.aws_vpc.shared_vpc.id }\n'
        'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.shared_vpc_private.ids }\n}\n')
    assert list(_placed(tf_extract.extract(Path("."), tmp_path)).values()) == ["data.aws_vpc.shared_vpc"]


def test_a_remote_state_name_with_a_hyphen_or_an_empty_index_is_a_remote_network(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        _tfe("networking", name="shared-net")
        + 'data "terraform_remote_state" "e" {\n  for_each = toset([""])\n  backend = "s3"\n  config = { key = "n" }\n}\n'
        'resource "aws_security_group" "e" { vpc_id = data.terraform_remote_state.e[""].outputs.hub_vpc_id }\n')
    assert sorted(n["name"] for n in tf_extract.extract(Path("."), tmp_path)["networks"]) == ["hub-vpc", "shared-vpc"]


def test_an_indexed_remote_state_places_its_own_subnets(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'data "terraform_remote_state" "net" {\n  for_each = toset(["prod", "dev"])\n  backend = "s3"\n'
        '  config = { bucket = "states", key = "${each.key}/networking/terraform.tfstate" }\n}\n'
        + "".join(f'resource "aws_security_group" "{env}" {{ vpc_id = data.terraform_remote_state.net["{env}"].outputs.shared_vpc_id }}\n'
                  f'resource "aws_lambda_function" "{env}" {{\n  vpc_config {{ subnet_ids = '
                  f'data.terraform_remote_state.net["{env}"].outputs.shared_vpc_private_subnet_ids }}\n}}\n' for env in ("prod", "dev")))
    facts = tf_extract.extract(Path("."), tmp_path)
    assert len(facts["networks"]) == 2 and len(set(_placed(facts, "id").values())) == 2


def test_an_object_passed_to_a_module_gives_only_the_attribute_read(tmp_path: Path) -> None:
    (tmp_path / "infra" / "lam").mkdir(parents=True)
    (tmp_path / "infra" / "main.tf").write_text(
        'data "aws_vpc" "shared" {}\n'
        'data "tfe_outputs" "dns" {\n  organization = "o"\n  workspace = "dns"\n}\n'
        'module "lam" {\n  source = "./lam"\n  base = {\n'
        '    networking = { vpc_id = data.aws_vpc.shared.id }\n'
        '    zone = data.tfe_outputs.dns.values.route53_zone_id\n  }\n}\n')
    (tmp_path / "infra" / "lam" / "main.tf").write_text(
        'variable "base" {}\n'
        'resource "aws_security_group" "sg" { vpc_id = var.base.networking.vpc_id }\n')
    facts = tf_extract.extract(Path("infra"), tmp_path)
    assert [n["address"] for n in facts["networks"]] == ["data.aws_vpc.shared"]


def test_an_attribute_path_reads_through_a_local_that_holds_the_object(tmp_path: Path) -> None:
    (tmp_path / "infra" / "lam").mkdir(parents=True)
    (tmp_path / "infra" / "main.tf").write_text(
        'data "aws_vpc" "shared" {}\n'
        'data "tfe_outputs" "dns" {\n  organization = "o"\n  workspace = "dns"\n}\n'
        'locals {\n  base = {\n    networking = { vpc_id = data.aws_vpc.shared.id }\n'
        '    zone = data.tfe_outputs.dns.values.route53_zone_id\n  }\n}\n'
        'module "lam" {\n  source = "./lam"\n  base = local.base\n}\n')
    (tmp_path / "infra" / "lam" / "main.tf").write_text(
        'variable "base" {}\n'
        'resource "aws_security_group" "sg" { vpc_id = var.base.networking.vpc_id }\n')
    facts = tf_extract.extract(Path("infra"), tmp_path)
    assert [n["address"] for n in facts["networks"]] == ["data.aws_vpc.shared"]


def test_an_attribute_path_that_leaves_the_object_keeps_every_reference(tmp_path: Path) -> None:
    (tmp_path / "infra" / "lam").mkdir(parents=True)
    (tmp_path / "infra" / "main.tf").write_text(
        'data "aws_vpc" "shared" {}\n'
        'module "lam" {\n  source = "./lam"\n  base = { vpc = data.aws_vpc.shared }\n}\n')
    (tmp_path / "infra" / "lam" / "main.tf").write_text(
        'variable "base" {}\n'
        'resource "aws_security_group" "sg" { vpc_id = var.base.vpc.id }\n')
    facts = tf_extract.extract(Path("infra"), tmp_path)
    assert [n["address"] for n in facts["networks"]] == ["data.aws_vpc.shared"]


def _vpc_networks(tmp_path: Path, tf: str) -> list[tuple[str, bool]]:
    (tmp_path / "main.tf").write_text(tf)
    return [(n["address"], n["remote"]) for n in tf_extract.extract(Path("."), tmp_path)["networks"]]


@pytest.mark.parametrize("selects", ["id = aws_vpc.main.id", 'filter {\n    name = "vpc-id"\n    values = [aws_vpc.main.id]\n  }'])
def test_a_lookup_of_a_vpc_this_stack_creates_is_that_local_vpc(tmp_path: Path, selects: str) -> None:
    tf = ('resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
          f'data "aws_vpc" "main" {{\n  {selects}\n}}\n'
          'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n')
    assert _vpc_networks(tmp_path, tf) == [("aws_vpc.main", False)]


QUOTED_KEYS = ('locals {\n  nets = {\n    "blue" = { vpc = data.tfe_outputs.blue.values.blue_vpc_id }\n'
               '    "green" = { vpc = data.tfe_outputs.green.values.green_vpc_id }\n  }\n'
               '  list = [{ vpc = data.tfe_outputs.blue.values.blue_vpc_id }, { vpc = data.tfe_outputs.green.values.green_vpc_id }]\n}\n'
               'resource "aws_security_group" "sg" { vpc_id = local.PATH.vpc }\n')


@pytest.mark.parametrize(("path", "names"), [
    ("nets.blue", ["blue-vpc"]), ('nets["blue"]', ["blue-vpc"]), ("list[1]", ["green-vpc"]), ("nets.red", []),
    ("list[5]", []), ("nets[each.key]", ["blue-vpc", "green-vpc"])])
def test_an_attribute_path_reads_a_key_or_index_and_a_missing_one_reads_nothing(tmp_path: Path, path: str,
                                                                                names: list[str]) -> None:
    (tmp_path / "main.tf").write_text(QUOTED_KEYS.replace("PATH", path))
    assert sorted(n["name"] for n in tf_extract.extract(Path("."), tmp_path)["networks"]) == names


def test_each_key_or_index_of_a_remote_output_is_its_own_network(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(_tfe("net").replace("shared_vpc_id", 'vpcs["blue"]') + "".join(
        f'resource "aws_security_group" "{n}" {{ vpc_id = data.tfe_outputs.net.values.{ref} }}\n'
        for n, ref in (("g", 'vpcs["green"]'), ("x", "vpc_ids[0]"), ("y", "vpc_ids[1]"))))
    names = sorted(n["name"] for n in tf_extract.extract(Path("."), tmp_path)["networks"])
    assert names == ["vpc[0]", "vpc[1]", "vpcs.blue", "vpcs.green"]


def test_a_remote_subnet_goes_to_its_own_state_before_a_lookup_of_the_same_name(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        _tfe("net").replace("shared_vpc_id", "core_id")
        + 'resource "aws_security_group" "sg2" { vpc_id = data.aws_vpc.core.id }\n'
        'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.net.values.core_private_subnet_ids }\n}\n')
    assert _placed(tf_extract.extract(Path("."), tmp_path)) == {"aws_lambda_function.a": "data.tfe_outputs.net.values.core_id"}


def test_a_local_that_reads_itself_gives_no_network_and_no_crash(tmp_path: Path) -> None:
    tf = 'locals {\n  a = local.a.x\n}\nresource "aws_security_group" "sg" { vpc_id = local.a.x }\n'
    assert _vpc_networks(tmp_path, tf) == []


@pytest.mark.parametrize(("call", "read"), [("count = 1", "[0]"), ('for_each = { a = 1 }', '["a"]')])
def test_an_output_of_an_indexed_module_call_places_its_subnet(tmp_path: Path, call: str, read: str) -> None:
    (tmp_path / "net").mkdir()
    (tmp_path / "net" / "main.tf").write_text(
        'resource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_subnet" "private" {\n  vpc_id = aws_vpc.v.id\n  cidr_block = "10.0.1.0/24"\n}\n'
        'output "private_subnet_id" { value = aws_subnet.private.id }\n')
    (tmp_path / "main.tf").write_text(
        f'module "net" {{\n  source = "./net"\n  {call}\n}}\n'
        f'resource "aws_instance" "i" {{ subnet_id = module.net{read}.private_subnet_id }}\n')
    assert _placed(tf_extract.extract(Path("."), tmp_path)) == {"aws_instance.i": "module.net.aws_vpc.v"}


def test_a_lookup_that_only_depends_on_a_local_vpc_stays_external(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_subnet" "private" {\n  vpc_id = aws_vpc.main.id\n  cidr_block = "10.0.1.0/24"\n}\n'
        'data "aws_vpc" "peer" {\n  id = var.peer_vpc_id\n  depends_on = [aws_vpc.main]\n}\n'
        'data "aws_subnet" "peer_private" {\n  id = var.peer_subnet_id\n  depends_on = [aws_subnet.private]\n}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.peer.id }\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnet.peer_private.id }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [(n["address"], n["remote"]) for n in facts["networks"]] == [("aws_vpc.main", False), ("data.aws_vpc.peer", True)]
    assert _placed(facts) == {"aws_instance.i": "data.aws_vpc.peer"}


def test_a_lookup_read_twice_stays_the_local_vpc_it_selects(tmp_path: Path) -> None:
    tf = ('resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
          'data "aws_vpc" "x" { id = aws_vpc.main.id }\n'
          'locals {\n  vpc = data.aws_vpc.x\n}\n'
          'resource "aws_security_group" "sg" { vpc_id = var.alt ? local.vpc.id : local.vpc.arn }\n')
    assert _vpc_networks(tmp_path, tf) == [("aws_vpc.main", False)]


def test_each_literal_index_of_a_lookup_is_its_own_network(tmp_path: Path) -> None:
    tf = ('data "aws_vpc" "x" {\n  count = 2\n  id = var.ids[count.index]\n}\n'
          'resource "aws_security_group" "a" { vpc_id = data.aws_vpc.x[0].id }\n'
          'resource "aws_security_group" "b" { vpc_id = data.aws_vpc.x[1].id }\n')
    assert _vpc_networks(tmp_path, tf) == [("data.aws_vpc.x[0]", True), ("data.aws_vpc.x[1]", True)]


def test_a_quoted_local_keeps_the_attribute_path(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_vpc" "a" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_vpc" "b" { cidr_block = "10.1.0.0/16" }\n'
        'locals {\n  net = { a = aws_vpc.a.id, b = aws_vpc.b.id }\n  alias = "${local.net}"\n}\n'
        'resource "aws_subnet" "private" {\n  vpc_id = local.alias.b\n  cidr_block = "10.1.1.0/24"\n}\n'
        'resource "aws_instance" "i" { subnet_id = aws_subnet.private.id }\n')
    assert _placed(tf_extract.extract(Path("."), tmp_path)) == {"aws_instance.i": "aws_vpc.b"}


@pytest.mark.parametrize(("vpc", "path", "tier"), [
    ('vpcs["private-net"].id', 'vpcs["private-net"].public_subnet_ids', "public"),
    ("private_vpc.id", "private_vpc.public_subnet_ids", "public"),
    ("vpc_id", 'vpc_subnets["private"]', "private"),
    ("vpc_id", "vpc_private_subnet_ids[0]", "private"),
    ("private_vpc.id", "private_vpc.subnet_ids", None),
    ("shared_vpc_id", "shared_vpc_private_subnet.id", "private"),
    ("shared_vpc_id", 'shared_vpc_subnets["private"].id', "private"),
])
def test_only_the_last_name_of_a_remote_path_sets_the_tier(tmp_path: Path, vpc: str, path: str, tier: str | None) -> None:
    (tmp_path / "main.tf").write_text(
        'data "terraform_remote_state" "n" {\n  backend = "s3"\n  config = { bucket = "b", key = "k" }\n}\n'
        f'resource "aws_security_group" "s" {{ vpc_id = data.terraform_remote_state.n.outputs.{vpc} }}\n'
        f'resource "aws_lb" "l" {{ subnets = data.terraform_remote_state.n.outputs.{path} }}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [p["tier"] for p in facts["placements"]] == ([tier] if tier else [])


@pytest.mark.parametrize(("address", "module"), [
    ("data.aws_vpc.v", ""),
    ("module.a.data.aws_vpc.v", "module.a."),
    ('module.m.data.aws_vpc.v["data.core"]', "module.m."),
    ('module.a["k.data"].module.b.data.aws_vpc.v', 'module.a["k.data"].module.b.'),
])
def test_the_module_of_a_lookup_address_ignores_keys(address: str, module: str) -> None:
    from cartographer.clouds.refs import _module
    assert _module(address) == module


REMOTE_BACKEND = ('data "terraform_remote_state" "net" {{\n  backend = "remote"\n'
                  '  config = {{\n    organization = "acme"\n{host}    workspaces = {{ name = "networking" }}\n  }}\n}}\n'
                  'resource "aws_lambda_function" "a" {{\n'
                  '  vpc_config {{ subnet_ids = data.terraform_remote_state.net.outputs.shared_vpc_private_subnet_ids }}\n}}\n')


@pytest.mark.parametrize(("host", "workspace", "one"), [
    ("", "networking", True),
    ('    hostname = "app.terraform.io"\n', "networking", True),
    ('    hostname = "tfe.corp.example"\n', "networking", False),
    ("", "platform", False),
])
def test_a_remote_backend_read_of_a_workspace_is_the_network_tfe_outputs_reads(
        tmp_path: Path, host: str, workspace: str, one: bool) -> None:
    (tmp_path / "main.tf").write_text(_tfe(workspace) + REMOTE_BACKEND.format(host=host))
    facts = tf_extract.extract(Path("."), tmp_path)
    assert len(facts["networks"]) == 1
    assert bool(facts["placements"]) is one


@pytest.mark.parametrize(("orgs", "networks"), [(("o1", "o2"), 2), (("o1", "o1"), 1)])
def test_the_tfe_provider_organization_identifies_a_tfe_outputs_without_one(
        tmp_path: Path, orgs: tuple[str, str], networks: int) -> None:
    blocks = "".join(
        f'provider "tfe" {{\n  alias = "{a}"\n  organization = "{o}"\n}}\n'
        f'data "tfe_outputs" "{a}" {{\n  provider = tfe.{a}\n  workspace = "network"\n}}\n'
        f'resource "aws_security_group" "{a}" {{ vpc_id = data.tfe_outputs.{a}.values.shared_vpc_id }}\n'
        for a, o in zip(("a", "b"), orgs))
    (tmp_path / "main.tf").write_text(blocks)
    assert len(tf_extract.extract(Path("."), tmp_path)["networks"]) == networks


@pytest.mark.parametrize(("vpcs", "subnets", "network"), [
    (("shared_vpc_ids[0]",), "shared_vpc_private_subnet_ids[0]", "shared-vpc[0]"),
    (("network.vpc_id",), "network_private_subnet_ids", "network"),
    (("network.vpc_id",), "network.private_subnet_ids", "network"),
    (("vpc_ids[0]", "vpc_ids[1]"), "vpc_private_subnet_ids[1]", "vpc[1]"),
    (("vpc_ids[0]", "vpc_ids[1]"), "vpc_private_subnet_ids", None),  # two networks fit equally well
    (('vpcs["blue"].id', 'vpcs["green"].id'), 'vpcs["green"].private_subnet_ids', "vpcs.green"),
])
def test_a_remote_subnet_finds_the_network_its_path_names(tmp_path: Path, vpcs: tuple[str, ...], subnets: str,
                                                          network: str | None) -> None:
    (tmp_path / "main.tf").write_text(
        _tfe("networking").replace("shared_vpc_id", vpcs[0]) + "".join(
            f'resource "aws_security_group" "s{i}" {{ vpc_id = data.tfe_outputs.net.values.{v} }}\n'
            for i, v in enumerate(vpcs[1:]))
        + f'resource "aws_lb" "l" {{ subnets = data.tfe_outputs.net.values.{subnets} }}\n')
    placed = _placed(tf_extract.extract(Path("."), tmp_path), "name")
    assert placed == ({"aws_lb.l": network} if network else {})


def test_a_subnet_lookup_filtered_by_a_local_vpc_is_in_that_vpc(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'data "aws_subnet" "private" {\n  filter {\n    name = "vpc-id"\n    values = [aws_vpc.main.id]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnet.private.id }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert _placed(facts) == {"aws_instance.i": "aws_vpc.main"}
    assert [p["tier"] for p in facts["placements"]] == ["private"]


def test_a_path_after_an_index_that_is_no_literal_reads_each_element(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        _tfe("networking") + 'locals {\n  nets = {\n    a = {\n'
        '      public_subnet_id = data.tfe_outputs.net.values.shared_vpc_public_subnet_ids\n'
        '      private_subnet_id = data.tfe_outputs.net.values.shared_vpc_private_subnet_ids\n    }\n  }\n}\n'
        'resource "aws_instance" "i" {\n  for_each = local.nets\n  subnet_id = local.nets[each.key].private_subnet_id\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [p["tier"] for p in facts["placements"]] == ["private"]


def _extract(tmp_path: Path, tf: str) -> dict:
    (tmp_path / "main.tf").write_text(tf)
    return tf_extract.extract(Path("."), tmp_path)


S3_STATE = ('data "terraform_remote_state" "net" {\n  backend = "s3"\n'
            '  config = {\n    bucket = "tf"\n    key = "network.tfstate"\n  }\n}\n')


def test_two_vpc_outputs_of_one_object_are_two_networks(tmp_path: Path) -> None:
    facts = _extract(tmp_path, S3_STATE +
        'resource "aws_security_group" "app" { vpc_id = data.terraform_remote_state.net.outputs.network.app_vpc_id }\n'
        'resource "aws_security_group" "db" { vpc_id = data.terraform_remote_state.net.outputs.network.db_vpc_id }\n'
        'resource "aws_instance" "app" {\n'
        '  subnet_id = data.terraform_remote_state.net.outputs.network.app_vpc_private_subnet_ids[0]\n}\n'
        'resource "aws_instance" "db" {\n'
        '  subnet_id = data.terraform_remote_state.net.outputs.network.db_vpc_private_subnet_ids[0]\n}\n')
    assert sorted(n["name"] for n in facts["networks"]) == ["network.app-vpc", "network.db-vpc"]
    assert _placed(facts, "name") == {"aws_instance.app": "network.app-vpc", "aws_instance.db": "network.db-vpc"}


def test_a_subnet_that_fits_two_networks_equally_is_marked_with_why(tmp_path: Path) -> None:
    for module in ("a", "b"):
        (tmp_path / "modules" / module).mkdir(parents=True)
        (tmp_path / "modules" / module / "main.tf").write_text(
            'data "aws_vpc" "shared" {\n  tags = { Name = "shared" }\n}\n'
            'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared.id }\n')
    facts = _extract(tmp_path,
        'module "a" { source = "./modules/a" }\nmodule "b" { source = "./modules/b" }\n'
        'data "aws_subnets" "shared_private" {\n  filter {\n    name = "tag:Tier"\n    values = ["private"]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.shared_private.ids[0] }\n')
    assert facts["placements"] == []
    resource = next(r for r in facts["resources"] if r["address"] == "aws_instance.i")
    assert resource["marked"]
    assert resource["reason"] == ("shared_private fits networks module.a.data.aws_vpc.shared and "
                                  "module.b.data.aws_vpc.shared equally well")


def test_a_subnet_lookup_by_the_vpc_id_of_a_local_vpc_is_in_that_vpc(tmp_path: Path) -> None:
    facts = _extract(tmp_path,
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'data "aws_subnet" "private" {\n  vpc_id = aws_vpc.main.id\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnet.private.id }\n')
    assert _placed(facts) == {"aws_instance.i": "aws_vpc.main"}


def test_a_subnets_lookup_by_a_local_subnet_is_in_the_vpc_of_that_subnet(tmp_path: Path) -> None:
    facts = _extract(tmp_path,
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_subnet" "a" {\n  vpc_id = aws_vpc.main.id\n  cidr_block = "10.0.1.0/24"\n}\n'
        'data "aws_subnets" "private" {\n  filter {\n    name = "subnet-id"\n    values = [aws_subnet.a.id]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.private.ids[0] }\n')
    assert _placed(facts) == {"aws_instance.i": "aws_vpc.main"}


def test_the_vpc_id_of_a_subnet_lookup_is_no_network(tmp_path: Path) -> None:
    facts = _extract(tmp_path,
        'data "aws_subnet" "private" {\n  tags = { Tier = "private" }\n}\n'
        'resource "aws_security_group" "s" { vpc_id = data.aws_subnet.private.vpc_id }\n')
    assert facts["networks"] == []


@pytest.mark.parametrize(("vpc", "subnets", "network"), [
    ("shared_vpc_arn", "shared_vpc_private_subnet_ids", "shared-vpc"),
    ("vpc_id", "private_subnet_ids", "vpc"),
])
def test_a_remote_subnet_finds_its_network_by_any_identifier_or_the_only_one(
        tmp_path: Path, vpc: str, subnets: str, network: str) -> None:
    facts = _extract(tmp_path,
        'data "tfe_outputs" "net" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        f'resource "aws_security_group" "s" {{ vpc_id = data.tfe_outputs.net.nonsensitive_values.{vpc} }}\n'
        f'resource "aws_instance" "i" {{ subnet_id = data.tfe_outputs.net.nonsensitive_values.{subnets}[0] }}\n')
    assert [n["name"] for n in facts["networks"]] == [network]
    assert [(p["resource"], p["tier"]) for p in facts["placements"]] == [("aws_instance.i", "private")]


def test_a_key_that_starts_another_key_is_not_its_network(tmp_path: Path) -> None:
    facts = _extract(tmp_path,
        'data "tfe_outputs" "net" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        'resource "aws_security_group" "s" { vpc_id = data.tfe_outputs.net.values.vpcs["blue"].vpc_id }\n'
        'resource "aws_instance" "i" { subnet_id = data.tfe_outputs.net.values.vpcs["blue-east"].private_subnet_ids[0] }\n')
    assert facts["placements"] == []


def test_a_subnet_lookup_filtered_by_a_looked_up_vpc_is_in_that_vpc(tmp_path: Path) -> None:
    facts = _extract(tmp_path,
        'data "aws_vpc" "shared" {\n  tags = { Name = "shared" }\n}\n'
        'data "aws_subnets" "private" {\n  filter {\n    name = "vpc-id"\n    values = [data.aws_vpc.shared.id]\n  }\n}\n'
        'resource "aws_security_group" "s" { vpc_id = data.aws_vpc.shared.id }\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.private.ids[0] }\n')
    assert _placed(facts) == {"aws_instance.i": "data.aws_vpc.shared"}
    assert [p["tier"] for p in facts["placements"]] == ["private"]


LOCAL_VPC = ('resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
             'resource "aws_subnet" "pub" {\n  vpc_id = aws_vpc.main.id\n  map_public_ip_on_launch = true\n}\n')


def test_a_vpc_lookup_through_a_local_subnet_is_the_local_vpc(tmp_path: Path) -> None:
    facts = _extract(tmp_path, LOCAL_VPC +
        'data "aws_vpc" "this" { id = aws_subnet.pub.vpc_id }\n'
        'resource "aws_security_group" "s" { vpc_id = data.aws_vpc.this.id }\n')
    assert [n["address"] for n in facts["networks"]] == ["aws_vpc.main"]


def test_a_subnet_lookup_by_the_vpc_of_a_local_subnet_is_in_that_vpc_with_its_own_tier(tmp_path: Path) -> None:
    facts = _extract(tmp_path, LOCAL_VPC +
        'data "aws_subnets" "private" {\n  filter {\n    name = "vpc-id"\n    values = [aws_subnet.pub.vpc_id]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.private.ids[0] }\n')
    assert _placed(facts) == {"aws_instance.i": "aws_vpc.main"}
    assert [p["tier"] for p in facts["placements"]] == ["private"]


def test_a_subnet_that_names_no_network_finds_the_network_of_its_index(tmp_path: Path) -> None:
    facts = _extract(tmp_path,
        'data "tfe_outputs" "net" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        'resource "aws_security_group" "a" { vpc_id = data.tfe_outputs.net.values.vpc_ids[0] }\n'
        'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.net.values.vpc_ids[1] }\n'
        'resource "aws_instance" "i" { subnet_id = data.tfe_outputs.net.values.private_subnet_ids[0] }\n')
    assert _placed(facts, "name") == {"aws_instance.i": "vpc[0]"}


def test_a_path_after_a_function_reads_each_reference_in_it(tmp_path: Path) -> None:
    facts = _extract(tmp_path,
        'data "tfe_outputs" "net" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        'locals {\n  a = {\n    vpc_id = data.tfe_outputs.net.values.app_vpc_id\n'
        '    peer_vpc_id = data.tfe_outputs.net.values.db_vpc_id\n  }\n  cfg = merge(local.a, {})\n}\n'
        'resource "aws_security_group" "s" { vpc_id = local.cfg.vpc_id }\n')
    assert [n["name"] for n in facts["networks"]] == ["app-vpc"]


PEER_BY_NAME = {
    "aws": ('resource "aws_vpc" "main" {\n  cidr_block = "10.0.0.0/16"\n  tags = { Name = "core" }\n}\n'
            'data "aws_vpc" "peer" {\n  filter {\n    name = "tag:Name"\n'
            '    values = ["${aws_vpc.main.tags.Name}-peer"]\n  }\n}\n'
            'data "aws_subnets" "peer_private" {\n  filter {\n    name = "vpc-id"\n    values = [data.aws_vpc.peer.id]\n  }\n}\n'
            'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.peer_private.ids }\n}\n'),
    "azure": ('resource "azurerm_virtual_network" "hub" {\n  name = "hub"\n  address_space = ["10.0.0.0/16"]\n}\n'
              'data "azurerm_virtual_network" "spoke" { name = "${azurerm_virtual_network.hub.name}-spoke" }\n'
              'data "azurerm_subnet" "spoke_private" {\n  name = "private"\n'
              '  virtual_network_name = data.azurerm_virtual_network.spoke.name\n}\n'
              'resource "azurerm_private_endpoint" "fn" { subnet_id = data.azurerm_subnet.spoke_private.id }\n'),
}


@pytest.mark.parametrize("cloud", sorted(PEER_BY_NAME))
def test_a_lookup_that_builds_its_name_from_a_local_network_is_another_network(tmp_path: Path, cloud: str) -> None:
    facts = _extract(tmp_path, PEER_BY_NAME[cloud])
    placed = _placed(facts)
    assert len(facts["networks"]) == 2
    assert list(placed.values()) in (["data.aws_vpc.peer"], ["data.azurerm_virtual_network.spoke"])


def test_a_lookup_that_many_paths_reach_is_followed_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cartographer.clouds import refs

    levels = 12  # each lookup reads both lookups of the next level: 2**12 paths reach the last one
    tf = 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
    for i in range(levels):
        below = f"[data.aws_subnet.a{i + 1}.id, data.aws_subnet.b{i + 1}.id]" if i < levels - 1 else "[aws_vpc.main.id]"
        tf += "".join(f'data "aws_subnet" "{x}{i}" {{\n  filter {{\n    name = "vpc-id"\n    values = {below}\n  }}\n}}\n'
                      for x in "ab")
    calls = 0
    follow = refs._follow

    def counted(*args: object) -> dict:
        nonlocal calls
        calls += 1
        return follow(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(refs, "_follow", counted)
    _extract(tmp_path, tf + 'resource "aws_instance" "i" { subnet_id = data.aws_subnet.a0.id }\n')
    assert calls < 2000


def test_a_subnet_lookup_in_a_vpc_only_it_names_is_in_that_vpc(tmp_path: Path) -> None:
    facts = _extract(tmp_path,
        'data "aws_vpc" "shared" {\n  tags = { Name = "shared" }\n}\n'
        'data "aws_subnet" "private" { vpc_id = data.aws_vpc.shared.id }\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnet.private.id }\n')
    assert _placed(facts) == {"aws_instance.i": "data.aws_vpc.shared"}


def _reason(facts: dict, address: str) -> str | None:
    return next(r.get("reason") for r in facts["resources"] if r["address"] == address)


def test_a_subnet_lookup_whose_name_gives_no_tier_is_marked(tmp_path: Path) -> None:
    facts = _extract(tmp_path, S3_STATE +
        'data "aws_subnets" "app" {\n  filter {\n    name = "vpc-id"\n'
        '    values = [data.terraform_remote_state.net.outputs.vpc_id]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.app.ids[0] }\n')
    assert facts["placements"] == []
    assert _reason(facts, "aws_instance.i") == "app is in data.terraform_remote_state.net.outputs.vpc_id, its name gives no subnet tier"


def test_a_remote_subnet_that_fits_no_network_is_marked(tmp_path: Path) -> None:
    facts = _extract(tmp_path, S3_STATE +
        'resource "aws_instance" "i" { subnet_id = data.terraform_remote_state.net.outputs.private_subnet_ids[0] }\n')
    assert _reason(facts, "aws_instance.i") == "private_subnet_ids[0] fits no network this stack knows"


LOCAL_VNET = ('resource "azurerm_resource_group" "rg" { name = "rg-app" }\n'
              'resource "azurerm_virtual_network" "main" {\n  name = "vnet-app"\n'
              '  resource_group_name = azurerm_resource_group.rg.name\n  address_space = ["10.0.0.0/16"]\n}\n')
PEER_VPC = ('resource "aws_vpc" "main" {\n  cidr_block = "10.0.0.0/16"\n  tags = { Name = "core" }\n}\n'
            'provider "aws" {\n  alias = "dr"\n}\n')


@pytest.mark.parametrize(("tf", "local"), [
    (PEER_VPC + 'data "aws_vpc" "x" {\n  tags = { PeerOf = aws_vpc.main.id }\n}\n', False),
    (PEER_VPC + 'data "aws_vpc" "x" {\n  tags = { Name = aws_vpc.main.tags.Name }\n}\n', False),
    (PEER_VPC + 'data "aws_vpc" "x" {\n  filter {\n    name = "tag:Name"\n    values = [aws_vpc.main.tags.Name]\n  }\n}\n',
     False),
    (PEER_VPC + 'data "aws_vpc" "x" {\n  provider = aws.dr\n  id = aws_vpc.main.id\n}\n', False),
    (PEER_VPC + 'data "aws_vpc" "x" {\n  id = aws_vpc.main.id\n}\n', True),
    (LOCAL_VNET + 'data "azurerm_virtual_network" "x" {\n  name = azurerm_virtual_network.main.name\n'
     '  resource_group_name = "rg-app-dr"\n}\n', False),
    (LOCAL_VNET + 'data "azurerm_virtual_network" "x" {\n  name = azurerm_virtual_network.main.name\n'
     '  resource_group_name = azurerm_resource_group.rg.name\n}\n', True),
], ids=["tag-value", "tag-name", "name-filter", "other-provider", "id", "azure-other-rg", "azure-same-rg"])
def test_only_a_selector_that_picks_a_local_network_with_its_provider_makes_a_lookup_local(
        tmp_path: Path, tf: str, local: bool) -> None:
    kind = "azurerm_virtual_network" if "azurerm" in tf else "aws_vpc"
    arg = "virtual_network_name = data.azurerm_virtual_network.x.name" if "azurerm" in tf else "vpc_id = data.aws_vpc.x.id"
    facts = _extract(tmp_path, tf + f'resource "{kind}_peering" "p" {{ {arg} }}\n')
    assert [n["remote"] for n in facts["networks"]] == ([False] if local else [False, True])


def test_a_remote_output_that_picks_a_subnet_names_no_network(tmp_path: Path) -> None:
    facts = _extract(tmp_path, S3_STATE +
        'data "aws_subnet" "private" { id = data.terraform_remote_state.net.outputs.app_subnet_id }\n'
        'resource "aws_instance" "web" { subnet_id = data.aws_subnet.private.id }\n')
    assert facts["networks"] == []


def test_a_subnet_lookup_whose_network_selector_names_no_known_network_is_ranked_by_name(tmp_path: Path) -> None:
    facts = _extract(tmp_path,
        'data "aws_vpc" "shared" { tags = { Name = "shared" } }\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared.id }\n'
        'data "aws_subnet" "anchor" { tags = { Name = "anchor" } }\n'
        'data "aws_subnets" "shared_private" {\n  filter {\n    name = "vpc-id"\n'
        '    values = [data.aws_subnet.anchor.vpc_id]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.shared_private.ids[0] }\n')
    assert _placed(facts) == {"aws_instance.i": "data.aws_vpc.shared"}


def test_the_network_argument_of_a_counted_resource_is_followed(tmp_path: Path) -> None:
    facts = _extract(tmp_path,
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_subnet" "a" {\n  count = 2\n  vpc_id = aws_vpc.main.id\n}\n'
        'resource "aws_subnet" "b" {\n  vpc_id = aws_subnet.a[0].vpc_id\n  tags = { Name = "public-b" }\n}\n'
        'resource "aws_instance" "i" { subnet_id = aws_subnet.b.id }\n')
    assert _placed(facts) == {"aws_instance.i": "aws_vpc.main"}


def test_a_resource_with_one_placed_and_one_unplaced_subnet_is_marked(tmp_path: Path) -> None:
    facts = _extract(tmp_path, S3_STATE +
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_subnet" "a" { vpc_id = aws_vpc.main.id }\n'
        'resource "aws_lb" "l" {\n  subnets = [aws_subnet.a.id, data.terraform_remote_state.net.outputs.private_subnet_ids[0]]\n}\n')
    assert _placed(facts) == {"aws_lb.l": "aws_vpc.main"}
    assert "private_subnet_ids[0] fits no network this stack knows" in _reason(facts, "aws_lb.l")
