"""Which remote state a remote output reads: backends, workspaces, organizations and module settings."""
from pathlib import Path

import pytest
from network_tf import count_calls, placed_in, tfe_state, two_modules

from cartographer import tf_extract


def _remote_state(config: str, extra: str = "", name: str = "net", ref: str = "net") -> str:
    return (f'data "terraform_remote_state" "{name}" {{\n  backend = "s3"\n{extra}  config = {config}\n}}\n'
            f'resource "aws_security_group" "sg" {{ vpc_id = data.terraform_remote_state.{ref}.outputs.shared_vpc_id }}\n')


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
    (tfe_state("networking"), None, 1),
    (tfe_state("networking"), tfe_state("networking", organization="other"), 2),
    (tfe_state("default"), tfe_state("networking"), 2),  # a tfe workspace named default is a workspace like any other
    (tfe_state("n").replace("{\n", '{\n  provider = tfe.corp\n', 1) + ONPREM, tfe_state("n"), 2),  # two hosts, one workspace name
    (tfe_state("n").replace("{\n", '{\n  provider = tfe.app\n', 1) + APP, tfe_state("n"), 1),  # the default host, named
    (tfe_state("n").replace("{\n", '{\n  provider = tfe.nowhere\n', 1), None, 2),  # an undeclared provider: one per module
    ('resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.net.values.shared_vpc_id }\n', None, 2),  # no block
    (_remote_state("var.cfg"), None, 2),  # a config that cannot be read: one per module, never one by backend alone
    (_remote_state("local.all.net").replace("data", 'locals {\n  all = { net = { key = "n" } }\n}\ndata', 1), None, 2),
    (_remote_state('merge(local.base, { key = "n" })'), None, 2),
])
def test_state_identity(tmp_path: Path, a: str, b: str | None, networks: int) -> None:
    facts = two_modules(tmp_path, a, b)
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
    assert len(two_modules(tmp_path, WORKSPACE_FROM_A_VARIABLE, root=root)["networks"]) == networks


@pytest.mark.parametrize("second", ['  ws = "platform"\n', ""])
def test_calls_of_one_module_instance_that_disagree_fall_back_to_its_address(tmp_path: Path, second: str) -> None:
    root = f'module "x" {{\n  source = "./a"\n  ws = "networking"\n}}\nmodule "y" {{\n  source = "./a"\n{second}}}\n'
    facts = two_modules(tmp_path, WORKSPACE_FROM_A_VARIABLE, root=root)
    assert [n["address"] for n in facts["networks"]] == ["module.a.data.tfe_outputs.net.values.shared_vpc_id"]


@pytest.mark.parametrize("second", ['  providers = { tfe = tfe.us }\n', ""])
def test_calls_of_one_module_instance_that_map_the_tfe_provider_differently_fall_back_to_its_address(
        tmp_path: Path, second: str) -> None:
    root = ('provider "tfe" {\n  alias = "eu"\n  hostname = "tfe.eu.example"\n}\n'
            'provider "tfe" {\n  alias = "us"\n  hostname = "tfe.us.example"\n}\n'
            f'module "x" {{\n  source = "./a"\n  providers = {{ tfe = tfe.eu }}\n}}\nmodule "y" {{\n  source = "./a"\n{second}}}\n'
            + tfe_state("n", name="root").replace('"sg"', '"root_sg"'))
    facts = two_modules(tmp_path, tfe_state("n"), root=root)
    assert sorted(n["address"] for n in facts["networks"]) == [
        "data.tfe_outputs.root.values.shared_vpc_id", "module.a.data.tfe_outputs.net.values.shared_vpc_id"]


def test_other_values_read_the_first_call(tmp_path: Path) -> None:
    facts = two_modules(
        tmp_path, 'variable "cidr" {}\nresource "aws_vpc" "v" { cidr_block = var.cidr }\n',
        root='module "x" {\n  source = "./a"\n  cidr = "10.0.0.0/16"\n}\nmodule "y" {\n  source = "./a"\n  cidr = "10.1.0.0/16"\n}\n')
    assert [n["cidrs"] for n in facts["networks"]] == [["10.0.0.0/16"]]


def test_modules_that_read_one_state_share_its_network_and_each_state_keeps_its_subnets(tmp_path: Path) -> None:
    body = ('resource "aws_lambda_function" "fn" {\n'
            '  vpc_config { subnet_ids = data.tfe_outputs.net.values.shared_vpc_private_subnet_ids }\n}\n')
    for case in ("same", "apart"):
        (tmp_path / case).mkdir()
    same = two_modules(tmp_path / "same", tfe_state("networking") + body)
    assert len(same["networks"]) == 1 and len(same["placements"]) == 2
    apart = two_modules(tmp_path / "apart", tfe_state("net-a") + body, tfe_state("net-b") + body)
    assert len(apart["networks"]) == 2 and len(set(placed_in(apart, "id").values())) == 2


def test_a_remote_state_name_with_a_hyphen_or_an_empty_index_is_a_remote_network(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        tfe_state("networking", name="shared-net")
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
    assert len(facts["networks"]) == 2 and len(set(placed_in(facts, "id").values())) == 2


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
    (tmp_path / "main.tf").write_text(tfe_state(workspace) + REMOTE_BACKEND.format(host=host))
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


def test_settings_that_many_module_calls_agree_on_are_read_once_per_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cartographer import tf_modules
    calls = "".join(f'module "c{i}" {{\n  source = "./m"\n  ws = var.ws\n}}\n' for i in range(6))
    path = tmp_path
    for _ in range(5):
        (path / "main.tf").write_text('variable "ws" {}\n' + calls)
        path = path / "m"
        path.mkdir()
    (path / "main.tf").write_text(
        'variable "ws" {}\ndata "tfe_outputs" "net" {\n  organization = "o"\n  workspace = var.ws\n}\n'
        'resource "aws_security_group" "s" { vpc_id = data.tfe_outputs.net.values.vpc_id }\n')
    (tmp_path / "main.tf").write_text(calls.replace("var.ws", '"net"'))
    count_calls(monkeypatch, tf_modules.Inst, "value", 1000)
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [(n["name"], n["remote"]) for n in facts["networks"]] == [("vpc", True)]
