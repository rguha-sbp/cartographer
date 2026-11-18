"""Where a remote subnet or a subnet lookup is placed, its tier, and why one is marked."""
from pathlib import Path

import pytest
from network_tf import S3_STATE, extract_tf, mark_reason, placed_in, tfe_state, two_modules

from cartographer import tf_extract


def test_a_remote_subnet_goes_to_the_vpc_of_its_own_state_first(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        tfe_state("networking", name="networking") + tfe_state("platform", name="platform").replace('"sg"', '"sg2"')
        + 'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.networking.values.shared_vpc_private_subnet_ids }\n}\n'
        'resource "aws_lambda_function" "b" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.platform.values.shared_vpc_private_subnet_ids }\n}\n'
        'resource "aws_lambda_function" "c" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.other.values.shared_vpc_private_subnet_ids }\n}\n')
    placed = placed_in(tf_extract.extract(Path("."), tmp_path))
    assert placed["aws_lambda_function.a"] == "data.tfe_outputs.networking.values.shared_vpc_id"
    assert placed["aws_lambda_function.b"] == "data.tfe_outputs.platform.values.shared_vpc_id"
    assert "aws_lambda_function.c" not in placed  # no VPC of its own state: never one of another state


def test_a_remote_subnet_falls_back_to_a_looked_up_vpc(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared_vpc.id }\n'
        'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.networking.values.shared_vpc_private_subnet_ids }\n}\n')
    assert placed_in(tf_extract.extract(Path("."), tmp_path)) == {"aws_lambda_function.a": "data.aws_vpc.shared_vpc"}


def test_a_subnet_in_one_module_belongs_to_a_remote_vpc_another_module_reads(tmp_path: Path) -> None:
    facts = two_modules(
        tmp_path, tfe_state("networking", name="networking"),
        tfe_state("networking", name="networking").replace('"aws_security_group" "sg"', '"aws_subnet" "private"')
        + 'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = [aws_subnet.private.id] }\n}\n')
    assert [n["address"] for n in facts["networks"]] == ["module.a.data.tfe_outputs.networking.values.shared_vpc_id"]
    assert [p["resource"] for p in facts["placements"]] == ["module.b.aws_lambda_function.fn"]


def test_two_modules_that_look_up_a_vpc_under_one_name_give_two_networks(tmp_path: Path) -> None:
    facts = two_modules(
        tmp_path,
        'variable "name" {}\n'
        'data "aws_vpc" "main" {\n  tags = { Name = var.name }\n}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n',
        root='module "a" {\n  source = "./a"\n  name = "shop"\n}\nmodule "b" {\n  source = "./b"\n  name = "bank"\n}\n')
    assert [n["address"] for n in facts["networks"]] == ["module.a.data.aws_vpc.main", "module.b.data.aws_vpc.main"]


@pytest.mark.parametrize(("vpc", "path", "tier"), [
    ('vpcs["private-net"].id', 'vpcs["private-net"].public_subnet_ids', "public"),
    ("private_vpc.id", "private_vpc.public_subnet_ids", "public"),
    ("vpc_id", 'vpc_subnets["private"]', "private"),
    ("vpc_id", "vpc_private_subnet_ids[0]", "private"),
    ("private_vpc.id", "private_vpc.subnet_ids", None),
    ("shared_vpc_id", "shared_vpc_private_subnet.id", "private"),
    ("shared_vpc_id", 'shared_vpc_subnets["private"].id', "private"),
    ('vpcs["private-net"].vpc_id', 'vpcs["private-net"]["subnet_ids"][0]', None),
    ('vpcs["private-net"].vpc_id', 'vpcs["private-net"].subnet_ids["eu-west-1a"]', None),
    ("private_vpc_id", "private_vpc_public_subnet_ids[0]", "public"),
    ("private_net_id", "private_net_isolated_subnet_ids", "isolated"),
])
def test_only_the_last_name_of_a_remote_path_sets_the_tier(tmp_path: Path, vpc: str, path: str, tier: str | None) -> None:
    (tmp_path / "main.tf").write_text(
        'data "terraform_remote_state" "n" {\n  backend = "s3"\n  config = { bucket = "b", key = "k" }\n}\n'
        f'resource "aws_security_group" "s" {{ vpc_id = data.terraform_remote_state.n.outputs.{vpc} }}\n'
        f'resource "aws_lb" "l" {{ subnets = data.terraform_remote_state.n.outputs.{path} }}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [p["tier"] for p in facts["placements"]] == ([tier] if tier else [])


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
        tfe_state("networking").replace("shared_vpc_id", vpcs[0]) + "".join(
            f'resource "aws_security_group" "s{i}" {{ vpc_id = data.tfe_outputs.net.values.{v} }}\n'
            for i, v in enumerate(vpcs[1:]))
        + f'resource "aws_lb" "l" {{ subnets = data.tfe_outputs.net.values.{subnets} }}\n')
    placed = placed_in(tf_extract.extract(Path("."), tmp_path), "name")
    assert placed == ({"aws_lb.l": network} if network else {})


def test_a_subnet_that_fits_two_networks_equally_is_marked_with_why(tmp_path: Path) -> None:
    for module in ("a", "b"):
        (tmp_path / "modules" / module).mkdir(parents=True)
        (tmp_path / "modules" / module / "main.tf").write_text(
            'data "aws_vpc" "shared" {\n  tags = { Name = "shared" }\n}\n'
            'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared.id }\n')
    facts = extract_tf(tmp_path,
        'module "a" { source = "./modules/a" }\nmodule "b" { source = "./modules/b" }\n'
        'data "aws_subnets" "shared_private" {\n  filter {\n    name = "tag:Tier"\n    values = ["private"]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.shared_private.ids[0] }\n')
    assert facts["placements"] == []
    resource = next(r for r in facts["resources"] if r["address"] == "aws_instance.i")
    assert resource["marked"]
    assert resource["reason"] == ("shared_private fits networks module.a.data.aws_vpc.shared and "
                                  "module.b.data.aws_vpc.shared equally well")


@pytest.mark.parametrize(("vpc", "subnets", "network"), [
    ("shared_vpc_arn", "shared_vpc_private_subnet_ids", "shared-vpc"),
    ("vpc_id", "private_subnet_ids", "vpc"),
])
def test_a_remote_subnet_finds_its_network_by_any_identifier_or_the_only_one(
        tmp_path: Path, vpc: str, subnets: str, network: str) -> None:
    facts = extract_tf(tmp_path,
        'data "tfe_outputs" "net" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        f'resource "aws_security_group" "s" {{ vpc_id = data.tfe_outputs.net.nonsensitive_values.{vpc} }}\n'
        f'resource "aws_instance" "i" {{ subnet_id = data.tfe_outputs.net.nonsensitive_values.{subnets}[0] }}\n')
    assert [n["name"] for n in facts["networks"]] == [network]
    assert [(p["resource"], p["tier"]) for p in facts["placements"]] == [("aws_instance.i", "private")]


def test_a_key_that_starts_another_key_is_not_its_network(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'data "tfe_outputs" "net" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        'resource "aws_security_group" "s" { vpc_id = data.tfe_outputs.net.values.vpcs["blue"].vpc_id }\n'
        'resource "aws_instance" "i" { subnet_id = data.tfe_outputs.net.values.vpcs["blue-east"].private_subnet_ids[0] }\n')
    assert facts["placements"] == []


def test_a_subnet_that_names_no_network_finds_the_network_of_its_index(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'data "tfe_outputs" "net" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        'resource "aws_security_group" "a" { vpc_id = data.tfe_outputs.net.values.vpc_ids[0] }\n'
        'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.net.values.vpc_ids[1] }\n'
        'resource "aws_instance" "i" { subnet_id = data.tfe_outputs.net.values.private_subnet_ids[0] }\n')
    assert placed_in(facts, "name") == {"aws_instance.i": "vpc[0]"}


def test_a_remote_subnet_that_fits_no_network_is_marked(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, S3_STATE +
        'resource "aws_instance" "i" { subnet_id = data.terraform_remote_state.net.outputs.private_subnet_ids[0] }\n')
    assert mark_reason(facts, "aws_instance.i") == "private_subnet_ids[0] fits no network this stack knows"


def test_a_resource_with_one_placed_and_one_unplaced_subnet_is_marked(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, S3_STATE +
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_subnet" "a" { vpc_id = aws_vpc.main.id }\n'
        'resource "aws_lb" "l" {\n  subnets = [aws_subnet.a.id, data.terraform_remote_state.net.outputs.private_subnet_ids[0]]\n}\n')
    assert placed_in(facts) == {"aws_lb.l": "aws_vpc.main"}
    assert "private_subnet_ids[0] fits no network this stack knows" in mark_reason(facts, "aws_lb.l")


def test_a_subnet_name_with_a_word_beyond_the_network_name_fits_no_network(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, tfe_state("net") +
        'resource "aws_security_group" "s" { vpc_id = data.tfe_outputs.net.values.blue_vpc_id }\n'
        'resource "aws_lambda_function" "f" {\n  vpc_config {\n'
        '    subnet_ids = data.tfe_outputs.net.values.blue_vpc_east_private_subnet_ids\n  }\n}\n')
    assert placed_in(facts) == {}
    assert "fits no network this stack knows" in mark_reason(facts, "aws_lambda_function.f")


@pytest.mark.parametrize(("vpc", "subnet", "via"), [
    ("shared_vpc_id", 'shared_vpc_private_subnet_ids["eu-west-1a"]', "shared_vpc_private_subnet_ids.eu-west-1a"),
    ('vpcs["public-net"].vpc_id', 'vpcs["public-net"].private_subnet_ids["a"]', "vpcs.public-net.private_subnet_ids.a"),
])
def test_a_literal_key_after_a_remote_subnet_output_keeps_the_tier_of_its_name(tmp_path: Path, vpc: str, subnet: str, via: str) -> None:
    facts = extract_tf(tmp_path, tfe_state("network").replace("shared_vpc_id", vpc)
                     + f'resource "aws_instance" "a" {{ subnet_id = data.tfe_outputs.net.values.{subnet} }}\n')
    assert [(p["tier"], p["via"]) for p in facts["placements"]] == [("private", via)]


@pytest.mark.parametrize(("name", "tier"), [
    ('"private-${var.public_zone}"', "private"),
    ('"${var.private_prefix}-public"', "public"),
    ('var.is_private ? "private" : "public"', "private"),  # no literal name: the default
    ('"app-isolated-republic"', "isolated"),
    ('format("%s-public-%s", var.p, "a")', "public"),
    ('join("-", [var.p, "public"])', "public"),
    ('"private-${lookup({ a = "x" }, var.public)}"', "private"),
])
def test_a_local_subnet_tier_comes_from_the_literal_words_of_its_name(tmp_path: Path, name: str, tier: str) -> None:
    facts = extract_tf(tmp_path, 'variable "p" {}\nvariable "public" {}\n'
        'resource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }\n'
        f'resource "aws_subnet" "a" {{\n  vpc_id = aws_vpc.v.id\n  tags = {{ Name = {name} }}\n}}\n'
        'resource "aws_instance" "i" { subnet_id = aws_subnet.a.id }\n')
    assert [p["tier"] for p in facts["placements"]] == [tier]


@pytest.mark.parametrize("tags", ['merge(var.tags, { Name = "app-public-a" })',
                                  'merge({ Team = "private" }, { Name = "app-public-a" })'])  # only the Name key counts
def test_a_local_subnet_tier_comes_from_a_name_tag_inside_a_function(tmp_path: Path, tags: str) -> None:
    facts = extract_tf(tmp_path, 'variable "tags" {}\nresource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }\n'
        f'resource "aws_subnet" "a" {{\n  vpc_id = aws_vpc.v.id\n  tags = {tags}\n}}\n'
        'resource "aws_instance" "i" { subnet_id = aws_subnet.a.id }\n')
    assert [p["tier"] for p in facts["placements"]] == ["public"]


def test_a_local_subnet_whose_vpc_id_reads_two_networks_is_marked(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, 'variable "create_vpc" { default = false }\n'
        'resource "aws_vpc" "this" {\n  count = var.create_vpc ? 1 : 0\n  cidr_block = "10.0.0.0/16"\n}\n'
        'data "tfe_outputs" "n" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        'resource "aws_subnet" "app" {\n'
        '  vpc_id = var.create_vpc ? aws_vpc.this[0].id : data.tfe_outputs.n.values.vpc_id\n'
        '  tags = { Name = "app-private" }\n}\n'
        'resource "aws_instance" "app" { subnet_id = aws_subnet.app.id }\n')
    assert facts["placements"] == []
    assert mark_reason(facts, "aws_instance.app") == (
        "aws_subnet.app is in network aws_vpc.this or data.tfe_outputs.n.values.vpc_id, it does not single out one")
