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
    assert remote[0]["stack"] == "networking"
    assert remote[0]["cidrs"] == []
    assert _vpcs()["aws_vpc.main"]["stack"] is None


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


def test_a_remote_subnet_goes_to_the_vpc_of_its_own_stack_first(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "a" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.platform.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.networking.values.shared_vpc_private_subnet_ids }\n}\n'
        'resource "aws_lambda_function" "b" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.platform.values.shared_vpc_private_subnet_ids }\n}\n'
        'resource "aws_lambda_function" "c" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.other.values.shared_vpc_private_subnet_ids }\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    stack = {n["id"]: n["stack"] for n in facts["networks"]}
    placed = {p["resource"]: stack[p["network"]] for p in facts["placements"]}
    assert placed["aws_lambda_function.a"] == "networking"
    assert placed["aws_lambda_function.b"] == "platform"
    assert "aws_lambda_function.c" in placed  # no VPC of its own stack: it still gets one, as before stacks


def test_modules_that_read_one_workspace_share_its_network(tmp_path: Path) -> None:
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.tf").write_text(
            'data "tfe_outputs" "networking" {\n  workspace = "networking"\n}\n'
            'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
            'resource "aws_lambda_function" "fn" {\n'
            '  vpc_config { subnet_ids = data.tfe_outputs.networking.values.shared_vpc_private_subnet_ids }\n}\n')
    (tmp_path / "main.tf").write_text('module "a" { source = "./a" }\nmodule "b" { source = "./b" }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [n["stack"] for n in facts["networks"]] == ["networking"]
    assert {p["network"] for p in facts["placements"]} == {facts["networks"][0]["id"]}
    assert len(facts["placements"]) == 2


def test_one_data_source_name_read_against_two_workspaces_gives_two_networks(tmp_path: Path) -> None:
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.tf").write_text(
            f'data "tfe_outputs" "networking" {{\n  workspace = "networking-{name}"\n}}\n'
            'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
            'resource "aws_lambda_function" "fn" {\n'
            '  vpc_config { subnet_ids = data.tfe_outputs.networking.values.shared_vpc_private_subnet_ids }\n}\n')
    (tmp_path / "main.tf").write_text('module "a" { source = "./a" }\nmodule "b" { source = "./b" }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    stack = {n["id"]: n["stack"] for n in facts["networks"]}
    placed = sorted((p["resource"], stack[p["network"]]) for p in facts["placements"])
    assert placed == [("module.a.aws_lambda_function.fn", "networking-a"), ("module.b.aws_lambda_function.fn", "networking-b")]


def test_a_remote_subnet_falls_back_to_a_looked_up_vpc(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared_vpc.id }\n'
        'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.networking.values.shared_vpc_private_subnet_ids }\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    ids = {n["address"]: n["id"] for n in facts["networks"]}
    placed = [(p["resource"], p["network"]) for p in facts["placements"]]
    assert placed == [("aws_lambda_function.a", ids["data.aws_vpc.shared_vpc"])]


def test_the_stack_is_the_workspace_a_remote_state_names_literally(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'data "tfe_outputs" "this" {\n  workspace = "networking-prod"\n}\n'
        'data "tfe_outputs" "other" {\n  workspace = var.workspace\n}\n'
        'data "terraform_remote_state" "net" {\n  backend = "remote"\n  config = { workspaces = { name = "hub" } }\n}\n'
        'data "terraform_remote_state" "s3" {\n  backend = "s3"\n  config = { key = "core/terraform.tfstate" }\n}\n'
        'data "terraform_remote_state" "az" {\n  backend = "azurerm"\n  config = { key = "edge.terraform.tfstate" }\n}\n'
        'data "terraform_remote_state" "gcs" {\n  backend = "s3"\n  config = { key = "spoke-terraform.tfstate" }\n}\n'
        'data "terraform_remote_state" "env" {\n  backend = "local"\n  workspace = "prod"\n}\n'
        'resource "aws_security_group" "a" { vpc_id = data.tfe_outputs.this.values.a_vpc_id }\n'
        'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.other.values.b_vpc_id }\n'
        'resource "aws_security_group" "c" { vpc_id = data.terraform_remote_state.net.outputs.c_vpc_id }\n'
        'resource "aws_security_group" "d" { vpc_id = data.terraform_remote_state.s3.outputs.d_vpc_id }\n'
        'resource "aws_security_group" "e" { vpc_id = data.terraform_remote_state.az.outputs.e_vpc_id }\n'
        'resource "aws_security_group" "f" { vpc_id = data.terraform_remote_state.gcs.outputs.f_vpc_id }\n'
        'resource "aws_security_group" "g" { vpc_id = data.terraform_remote_state.env.outputs.g_vpc_id }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    stacks = sorted((n["name"], n["stack"]) for n in facts["networks"])
    assert stacks == [("a-vpc", "networking-prod"), ("b-vpc", "other"), ("c-vpc", "hub"), ("d-vpc", "core"), ("e-vpc", "edge"),
                      ("f-vpc", "spoke"), ("g-vpc", "env")]  # a remote state's workspace is an environment


def test_a_subnet_lookup_falls_back_to_a_vpc_of_another_stack(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.aws_subnets.shared_vpc_private.ids }\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [(p["resource"], p["tier"]) for p in facts["placements"]] == [("aws_lambda_function.a", "private")]


def test_a_subnet_in_one_module_belongs_to_a_remote_vpc_another_module_reads(tmp_path: Path) -> None:
    for name, body in (("a", 'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'),
                       ("b", ('resource "aws_subnet" "private" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
                             'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = [aws_subnet.private.id] }\n}\n'))):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.tf").write_text(body)
    (tmp_path / "main.tf").write_text('module "a" { source = "./a" }\nmodule "b" { source = "./b" }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [n["address"] for n in facts["networks"]] == ["data.tfe_outputs.networking.values.shared_vpc_id"]
    assert [p["resource"] for p in facts["placements"]] == ["module.b.aws_lambda_function.fn"]


def test_a_subnet_lookup_goes_to_the_remote_vpc_with_the_longest_name(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "a" { vpc_id = data.aws_vpc.shared.id }\n'
        'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.shared_vpc_private.ids }\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    stack = {n["id"]: n["stack"] for n in facts["networks"]}
    assert [stack[p["network"]] for p in facts["placements"]] == ["networking"]


def _two_modules(tmp_path: Path, body: str, root: str) -> dict:
    """Facts of a root that calls modules `a` and `b`, each with `body`."""
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.tf").write_text(body)
    (tmp_path / "main.tf").write_text(root)
    return tf_extract.extract(Path("."), tmp_path)


WORKSPACE_FROM_A_VARIABLE = (
    'variable "net_ws" {}\n'
    'data "tfe_outputs" "this" {\n  workspace = var.net_ws\n}\n'
    'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.this.values.shared_vpc_id }\n')


def test_the_stack_follows_a_workspace_passed_as_a_module_variable(tmp_path: Path) -> None:
    facts = _two_modules(
        tmp_path, WORKSPACE_FROM_A_VARIABLE,
        'module "a" {\n  source = "./a"\n  net_ws = "networking-prod"\n}\n'
        'module "b" {\n  source = "./b"\n  net_ws = "platform-prod"\n}\n')
    assert sorted(n["stack"] for n in facts["networks"]) == ["networking-prod", "platform-prod"]


def test_calls_of_one_module_that_pass_different_workspaces_name_no_workspace(tmp_path: Path) -> None:
    facts = _two_modules(
        tmp_path, WORKSPACE_FROM_A_VARIABLE,
        'module "x" {\n  source = "./a"\n  net_ws = "networking-prod"\n}\n'
        'module "y" {\n  source = "./a"\n  net_ws = "platform-prod"\n}\n')
    assert [n["stack"] for n in facts["networks"]] == ["this"]  # one instance stands for both calls


def test_the_stack_is_a_state_key_with_any_characters(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'data "terraform_remote_state" "n" {\n  backend = "s3"\n  config = { key = "env:/prod/networking.tfstate" }\n}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.terraform_remote_state.n.outputs.shared_vpc_id }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [n["stack"] for n in facts["networks"]] == ["env:/prod/networking"]


def test_a_placement_names_the_stack_its_subnet_output_comes_from(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_subnet" "own" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "far" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.other.values.shared_vpc_private_subnet_ids }\n}\n'
        'resource "aws_lambda_function" "near" {\n  vpc_config { subnet_ids = [aws_subnet.own.id] }\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [n["stack"] for n in facts["networks"]] == ["networking"]
    assert {p["resource"]: p["stack"] for p in facts["placements"]} == {
        "aws_lambda_function.far": "other", "aws_lambda_function.near": None}


def test_two_modules_that_look_up_a_vpc_under_one_name_give_two_networks(tmp_path: Path) -> None:
    facts = _two_modules(
        tmp_path,
        'variable "name" {}\n'
        'data "aws_vpc" "main" {\n  tags = { Name = var.name }\n}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n',
        'module "a" {\n  source = "./a"\n  name = "shop"\n}\nmodule "b" {\n  source = "./b"\n  name = "bank"\n}\n')
    assert [n["address"] for n in facts["networks"]] == ["module.a.data.aws_vpc.main", "module.b.data.aws_vpc.main"]


def test_a_subnet_lookup_stays_with_the_vpc_its_own_module_looks_up(tmp_path: Path) -> None:
    facts = _two_modules(
        tmp_path,
        'data "aws_vpc" "main" {}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n'
        'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.main_private.ids }\n}\n',
        'module "a" {\n  source = "./a"\n}\nmodule "b" {\n  source = "./b"\n}\n')
    address = {n["id"]: n["address"] for n in facts["networks"]}
    assert {p["resource"]: address[p["network"]] for p in facts["placements"]} == {
        "module.a.aws_lambda_function.fn": "module.a.data.aws_vpc.main",
        "module.b.aws_lambda_function.fn": "module.b.data.aws_vpc.main"}


@pytest.mark.parametrize(("passed", "stack"), [("networking-prod", "this"), ("platform-prod", "platform-prod")])
def test_a_call_without_the_workspace_reads_the_default(tmp_path: Path, passed: str, stack: str) -> None:
    facts = _two_modules(
        tmp_path, WORKSPACE_FROM_A_VARIABLE.replace('"net_ws" {}', '"net_ws" {\n  default = "platform-prod"\n}'),
        f'module "x" {{\n  source = "./a"\n  net_ws = "{passed}"\n}}\nmodule "y" {{\n  source = "./a"\n}}\n')
    assert [n["stack"] for n in facts["networks"]] == [stack]


def test_a_remote_subnet_read_in_a_module_goes_to_the_longest_name_not_to_a_root_lookup(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared_vpc.id }\n'
        'resource "aws_lambda_function" "fn" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.net.values.shared_vpc_private_subnet_ids }\n}\n')
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared.id }\nmodule "a" {\n  source = "./a"\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    address = {n["id"]: n["address"] for n in facts["networks"]}
    assert [address[p["network"]] for p in facts["placements"]] == ["module.a.data.aws_vpc.shared_vpc"]


def test_a_module_named_data_keeps_the_lookups_of_its_submodules_apart(tmp_path: Path) -> None:
    for name in ("x", "y"):
        (tmp_path / "data" / name).mkdir(parents=True)
        (tmp_path / "data" / name / "main.tf").write_text(
            'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n'
            'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.main_private.ids }\n}\n')
    (tmp_path / "data" / "main.tf").write_text('module "x" {\n  source = "./x"\n}\nmodule "y" {\n  source = "./y"\n}\n')
    (tmp_path / "main.tf").write_text('module "data" {\n  source = "./data"\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    address = {n["id"]: n["address"] for n in facts["networks"]}
    assert all(address[p["network"]].startswith(p["resource"].removesuffix("aws_lambda_function.fn"))
               for p in facts["placements"]) and len(facts["placements"]) == 2


def test_a_root_subnet_lookup_stays_with_the_root_vpc_lookup_of_the_same_name(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "a" { vpc_id = data.aws_vpc.shared_vpc.id }\n'
        'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.shared_vpc_private.ids }\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    address = {n["id"]: n["address"] for n in facts["networks"]}
    assert [address[p["network"]] for p in facts["placements"]] == ["data.aws_vpc.shared_vpc"]


TIED_NAMES = (
    'resource "aws_security_group" "a" { vpc_id = data.aws_vpc.shared_vpc.id }\n'
    'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
    'resource "aws_lambda_function" "fn" {\n'
    '  vpc_config { subnet_ids = data.tfe_outputs.other.values.shared_vpc_private_subnet_ids }\n}\n')


@pytest.mark.parametrize("root", [TIED_NAMES, 'module "m" {\n  source = "./a"\n}\n'])
def test_a_remote_subnet_goes_to_a_remote_vpc_before_a_lookup_of_the_same_name_in_any_module(tmp_path: Path, root: str) -> None:
    facts = _two_modules(tmp_path, TIED_NAMES, root)
    stack = {n["id"]: n["stack"] for n in facts["networks"]}
    assert [stack[p["network"]] for p in facts["placements"]] == ["networking"]


@pytest.mark.parametrize(("config", "stack"), [
    ('{ "key" = "networking/terraform.tfstate" }', "networking"),
    ('{ "workspaces" = { "name" = "networking" } }', "networking"),
    ('{ key = "infraterraform.tfstate" }', "infraterraform"),
    ('{ key = "terraform.tfstate" }', "n"),
    ('{ key = "terraform.tfstate", workspace_key_prefix = "networking" }', "networking"),
    ('{ path = "../networking/terraform.tfstate" }', "networking"),
    ('{ prefix = "networking/" }', "networking"),
    ('{ path = "../.terraform/terraform.tfstate" }', ".terraform"),
    ('{ path = "./terraform.tfstate" }', "n"),
    ('{ key = "prod.terraform.tfstate" }', "n"),
    ('{ key = "prod/terraform.tfstate", workspace_key_prefix = "networking" }', "networking"),
    ('{ key = "prod/networking.tfstate" }', "prod/networking"),
])
def test_the_stack_reads_quoted_config_keys_and_cuts_only_a_whole_terraform_word(tmp_path: Path, config: str, stack: str) -> None:
    (tmp_path / "main.tf").write_text(
        f'data "terraform_remote_state" "n" {{\n  backend = "s3"\n  config = {config}\n}}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.terraform_remote_state.n.outputs.shared_vpc_id }\n')
    assert [n["stack"] for n in tf_extract.extract(Path("."), tmp_path)["networks"]] == [stack]


def test_a_remote_state_name_with_a_hyphen_is_a_remote_network(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'data "tfe_outputs" "shared-net" {\n  workspace = "networking"\n}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.shared-net.values.shared_vpc_id }\n')
    assert [n["stack"] for n in tf_extract.extract(Path("."), tmp_path)["networks"]] == ["networking"]
