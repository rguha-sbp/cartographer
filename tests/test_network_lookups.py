"""Data source lookups: which network a VPC or subnet lookup is, local or external."""
from pathlib import Path

import pytest
from network_tf import S3_STATE, TRS, extract_tf, mark_reason, placed_in, tfe_state, two_modules, vpc_networks

from cartographer import tf_extract


def test_a_subnet_lookup_falls_back_to_a_remote_vpc(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.aws_subnets.shared_vpc_private.ids }\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [(p["resource"], p["tier"]) for p in facts["placements"]] == [("aws_lambda_function.a", "private")]


def test_a_subnet_lookup_goes_to_the_remote_vpc_with_the_longest_name(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "a" { vpc_id = data.aws_vpc.shared.id }\n'
        'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.shared_vpc_private.ids }\n}\n')
    assert placed_in(tf_extract.extract(Path("."), tmp_path), "name") == {"aws_lambda_function.fn": "shared-vpc"}


def test_a_subnet_lookup_stays_with_the_vpc_its_own_module_looks_up(tmp_path: Path) -> None:
    facts = two_modules(
        tmp_path,
        'data "aws_vpc" "main" {}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n'
        'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.main_private.ids }\n}\n')
    assert placed_in(facts) == {"module.a.aws_lambda_function.fn": "module.a.data.aws_vpc.main",
                              "module.b.aws_lambda_function.fn": "module.b.data.aws_vpc.main"}


def test_a_remote_subnet_read_in_a_module_goes_to_the_longest_name_not_to_a_root_lookup(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared_vpc.id }\n'
        'resource "aws_lambda_function" "fn" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.net.values.shared_vpc_private_subnet_ids }\n}\n')
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared.id }\nmodule "a" {\n  source = "./a"\n}\n')
    assert list(placed_in(tf_extract.extract(Path("."), tmp_path)).values()) == ["module.a.data.aws_vpc.shared_vpc"]


def test_a_module_named_data_keeps_the_lookups_of_its_submodules_apart(tmp_path: Path) -> None:
    for name in ("x", "y"):
        (tmp_path / "data" / name).mkdir(parents=True)
        (tmp_path / "data" / name / "main.tf").write_text(
            'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n'
            'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.main_private.ids }\n}\n')
    (tmp_path / "data" / "main.tf").write_text('module "x" {\n  source = "./x"\n}\nmodule "y" {\n  source = "./y"\n}\n')
    (tmp_path / "main.tf").write_text('module "data" {\n  source = "./data"\n}\n')
    placed = placed_in(tf_extract.extract(Path("."), tmp_path))
    assert len(placed) == 2 and all(vpc.startswith(fn.removesuffix("aws_lambda_function.fn")) for fn, vpc in placed.items())


def test_a_root_subnet_lookup_stays_with_the_root_vpc_lookup_of_the_same_name(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_security_group" "a" { vpc_id = data.aws_vpc.shared_vpc.id }\n'
        'resource "aws_security_group" "b" { vpc_id = data.tfe_outputs.networking.values.shared_vpc_id }\n'
        'resource "aws_lambda_function" "fn" {\n  vpc_config { subnet_ids = data.aws_subnets.shared_vpc_private.ids }\n}\n')
    assert list(placed_in(tf_extract.extract(Path("."), tmp_path)).values()) == ["data.aws_vpc.shared_vpc"]


@pytest.mark.parametrize("selects", ["id = aws_vpc.main.id", 'filter {\n    name = "vpc-id"\n    values = [aws_vpc.main.id]\n  }'])
def test_a_lookup_of_a_vpc_this_stack_creates_is_that_local_vpc(tmp_path: Path, selects: str) -> None:
    tf = ('resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
          f'data "aws_vpc" "main" {{\n  {selects}\n}}\n'
          'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.main.id }\n')
    assert vpc_networks(tmp_path, tf) == [("aws_vpc.main", False)]


def test_a_remote_subnet_goes_to_its_own_state_before_a_lookup_of_the_same_name(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        tfe_state("net").replace("shared_vpc_id", "core_id")
        + 'resource "aws_security_group" "sg2" { vpc_id = data.aws_vpc.core.id }\n'
        'resource "aws_lambda_function" "a" {\n'
        '  vpc_config { subnet_ids = data.tfe_outputs.net.values.core_private_subnet_ids }\n}\n')
    assert placed_in(tf_extract.extract(Path("."), tmp_path)) == {"aws_lambda_function.a": "data.tfe_outputs.net.values.core_id"}


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
    assert placed_in(facts) == {"aws_instance.i": "data.aws_vpc.peer"}


def test_a_lookup_read_twice_stays_the_local_vpc_it_selects(tmp_path: Path) -> None:
    tf = ('resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
          'data "aws_vpc" "x" { id = aws_vpc.main.id }\n'
          'locals {\n  vpc = data.aws_vpc.x\n}\n'
          'resource "aws_security_group" "sg" { vpc_id = var.alt ? local.vpc.id : local.vpc.arn }\n')
    assert vpc_networks(tmp_path, tf) == [("aws_vpc.main", False)]


def test_each_literal_index_of_a_lookup_is_its_own_network(tmp_path: Path) -> None:
    tf = ('data "aws_vpc" "x" {\n  count = 2\n  id = var.ids[count.index]\n}\n'
          'resource "aws_security_group" "a" { vpc_id = data.aws_vpc.x[0].id }\n'
          'resource "aws_security_group" "b" { vpc_id = data.aws_vpc.x[1].id }\n')
    assert vpc_networks(tmp_path, tf) == [("data.aws_vpc.x[0]", True), ("data.aws_vpc.x[1]", True)]


@pytest.mark.parametrize(("address", "module"), [
    ("data.aws_vpc.v", ""),
    ("module.a.data.aws_vpc.v", "module.a."),
    ('module.m.data.aws_vpc.v["data.core"]', "module.m."),
    ('module.a["k.data"].module.b.data.aws_vpc.v', 'module.a["k.data"].module.b.'),
])
def test_the_module_of_a_lookup_address_ignores_keys(address: str, module: str) -> None:
    from cartographer.clouds.refs import _module
    assert _module(address) == module


def test_a_subnet_lookup_filtered_by_a_local_vpc_is_in_that_vpc(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'data "aws_subnet" "private" {\n  filter {\n    name = "vpc-id"\n    values = [aws_vpc.main.id]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnet.private.id }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert placed_in(facts) == {"aws_instance.i": "aws_vpc.main"}
    assert [p["tier"] for p in facts["placements"]] == ["private"]


def test_a_subnet_lookup_by_the_vpc_id_of_a_local_vpc_is_in_that_vpc(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'data "aws_subnet" "private" {\n  vpc_id = aws_vpc.main.id\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnet.private.id }\n')
    assert placed_in(facts) == {"aws_instance.i": "aws_vpc.main"}


def test_a_subnets_lookup_by_a_local_subnet_is_in_the_vpc_of_that_subnet(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_subnet" "a" {\n  vpc_id = aws_vpc.main.id\n  cidr_block = "10.0.1.0/24"\n}\n'
        'data "aws_subnets" "private" {\n  filter {\n    name = "subnet-id"\n    values = [aws_subnet.a.id]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.private.ids[0] }\n')
    assert placed_in(facts) == {"aws_instance.i": "aws_vpc.main"}


def test_the_vpc_id_of_a_subnet_lookup_is_no_network(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'data "aws_subnet" "private" {\n  tags = { Tier = "private" }\n}\n'
        'resource "aws_security_group" "s" { vpc_id = data.aws_subnet.private.vpc_id }\n')
    assert facts["networks"] == []


def test_a_subnet_lookup_filtered_by_a_looked_up_vpc_is_in_that_vpc(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'data "aws_vpc" "shared" {\n  tags = { Name = "shared" }\n}\n'
        'data "aws_subnets" "private" {\n  filter {\n    name = "vpc-id"\n    values = [data.aws_vpc.shared.id]\n  }\n}\n'
        'resource "aws_security_group" "s" { vpc_id = data.aws_vpc.shared.id }\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.private.ids[0] }\n')
    assert placed_in(facts) == {"aws_instance.i": "data.aws_vpc.shared"}
    assert [p["tier"] for p in facts["placements"]] == ["private"]


LOCAL_VPC = ('resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
             'resource "aws_subnet" "pub" {\n  vpc_id = aws_vpc.main.id\n  map_public_ip_on_launch = true\n}\n')


def test_a_vpc_lookup_through_a_local_subnet_is_the_local_vpc(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, LOCAL_VPC +
        'data "aws_vpc" "this" { id = aws_subnet.pub.vpc_id }\n'
        'resource "aws_security_group" "s" { vpc_id = data.aws_vpc.this.id }\n')
    assert [n["address"] for n in facts["networks"]] == ["aws_vpc.main"]


def test_a_subnet_lookup_by_the_vpc_of_a_local_subnet_is_in_that_vpc_with_its_own_tier(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, LOCAL_VPC +
        'data "aws_subnets" "private" {\n  filter {\n    name = "vpc-id"\n    values = [aws_subnet.pub.vpc_id]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.private.ids[0] }\n')
    assert placed_in(facts) == {"aws_instance.i": "aws_vpc.main"}
    assert [p["tier"] for p in facts["placements"]] == ["private"]


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
    facts = extract_tf(tmp_path, PEER_BY_NAME[cloud])
    placed = placed_in(facts)
    assert len(facts["networks"]) == 2
    assert list(placed.values()) in (["data.aws_vpc.peer"], ["data.azurerm_virtual_network.spoke"])


def test_a_subnet_lookup_in_a_vpc_only_it_names_is_in_that_vpc(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'data "aws_vpc" "shared" {\n  tags = { Name = "shared" }\n}\n'
        'data "aws_subnet" "private" { vpc_id = data.aws_vpc.shared.id }\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnet.private.id }\n')
    assert placed_in(facts) == {"aws_instance.i": "data.aws_vpc.shared"}


def test_a_subnet_lookup_whose_name_gives_no_tier_is_marked(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, S3_STATE +
        'data "aws_subnets" "app" {\n  filter {\n    name = "vpc-id"\n'
        '    values = [data.terraform_remote_state.net.outputs.vpc_id]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.app.ids[0] }\n')
    assert facts["placements"] == []
    assert mark_reason(facts, "aws_instance.i") == "app is in data.terraform_remote_state.net.outputs.vpc_id, its name gives no subnet tier"


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
    facts = extract_tf(tmp_path, tf + f'resource "{kind}_peering" "p" {{ {arg} }}\n')
    assert [n["remote"] for n in facts["networks"]] == ([False] if local else [False, True])


def test_a_remote_output_that_picks_a_subnet_names_no_network(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, S3_STATE +
        'data "aws_subnet" "private" { id = data.terraform_remote_state.net.outputs.app_subnet_id }\n'
        'resource "aws_instance" "web" { subnet_id = data.aws_subnet.private.id }\n')
    assert facts["networks"] == []


def test_a_subnet_lookup_whose_network_selector_names_no_known_network_is_ranked_by_name(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'data "aws_vpc" "shared" { tags = { Name = "shared" } }\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared.id }\n'
        'data "aws_subnet" "anchor" { tags = { Name = "anchor" } }\n'
        'data "aws_subnets" "shared_private" {\n  filter {\n    name = "vpc-id"\n'
        '    values = [data.aws_subnet.anchor.vpc_id]\n  }\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnets.shared_private.ids[0] }\n')
    assert placed_in(facts) == {"aws_instance.i": "data.aws_vpc.shared"}


def test_a_lookup_by_a_tag_of_a_local_network_is_external(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'resource "aws_vpc" "main" {\n  cidr_block = "10.0.0.0/16"\n  tags = { peer_vpc_id = "vpc-0123" }\n}\n'
        'data "aws_vpc" "peer" { id = aws_vpc.main.tags.peer_vpc_id }\n'
        'data "aws_subnets" "peer_private" {\n  filter {\n    name = "vpc-id"\n    values = [data.aws_vpc.peer.id]\n  }\n}\n'
        'resource "aws_lambda_function" "f" {\n  vpc_config {\n    subnet_ids = data.aws_subnets.peer_private.ids\n  }\n}\n')
    assert [(n["address"], n["remote"]) for n in facts["networks"]] == [("aws_vpc.main", False), ("data.aws_vpc.peer", True)]
    assert placed_in(facts) == {"aws_lambda_function.f": "data.aws_vpc.peer"}


def test_a_lookup_by_one_tag_reads_only_that_tag(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'resource "aws_vpc" "spoke" { cidr_block = "10.1.0.0/16" }\n'
        'resource "aws_vpc" "hub" {\n  cidr_block = "10.0.0.0/16"\n'
        '  tags = { Name = "hub", spoke_id = aws_vpc.spoke.id, peer_id = "vpc-0abc" }\n}\n'
        'data "aws_vpc" "peer" { id = aws_vpc.hub.tags.peer_id }\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.peer.id }\n'
        'data "aws_subnet" "peer_private" { vpc_id = aws_vpc.hub.tags.peer_id }\n'
        'resource "aws_lambda_function" "f" {\n  vpc_config {\n    subnet_ids = [data.aws_subnet.peer_private.id]\n  }\n}\n')
    assert placed_in(facts) == {"aws_lambda_function.f": "data.aws_vpc.peer"}


def test_a_tag_of_a_lookup_names_no_network(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'data "aws_vpc" "hub" {\n  tags = { Name = "hub" }\n}\n'
        'data "aws_subnet" "peer_private" { vpc_id = data.aws_vpc.hub.tags.peer_vpc_id }\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.hub.id }\n'
        'resource "aws_lambda_function" "f" {\n  vpc_config {\n    subnet_ids = [data.aws_subnet.peer_private.id]\n  }\n}\n')
    assert placed_in(facts) == {}
    assert "fits no network this stack knows" in mark_reason(facts, "aws_lambda_function.f")


NET_MODULE = ('variable "subnet_ids" { default = [] }\nvariable "vpc" { default = null }\n'
              'resource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }\n'
              'output "vpc_id" { value = aws_vpc.v.id }\noutput "app_subnet_ids" { value = var.subnet_ids }\n'
              'output "app_vpc" { value = var.vpc }\n')


def test_a_subnet_lookup_reached_through_one_module_output_reads_another(tmp_path: Path) -> None:
    (tmp_path / "net").mkdir()
    (tmp_path / "net" / "main.tf").write_text(NET_MODULE)
    facts = extract_tf(tmp_path,
        'module "net" {\n  source = "./net"\n  subnet_ids = [data.aws_subnet.shared_private.id]\n}\n'
        'data "aws_vpc" "shared" {\n  tags = { Name = "shared" }\n}\n'
        'resource "aws_security_group" "sg" { vpc_id = data.aws_vpc.shared.id }\n'
        'data "aws_subnet" "shared_private" { vpc_id = module.net.vpc_id }\n'
        'resource "aws_instance" "direct" { subnet_id = data.aws_subnet.shared_private.id }\n'
        'resource "aws_instance" "via_module" { subnet_id = module.net.app_subnet_ids[0] }\n')
    assert placed_in(facts) == {"aws_instance.direct": "module.net.aws_vpc.v", "aws_instance.via_module": "module.net.aws_vpc.v"}


def test_a_lookup_reached_through_one_module_output_picks_a_vpc_of_another(tmp_path: Path) -> None:
    (tmp_path / "net").mkdir()
    (tmp_path / "net" / "main.tf").write_text(NET_MODULE)
    facts = extract_tf(tmp_path,
        'module "net" {\n  source = "./net"\n  vpc = data.aws_vpc.self.id\n}\n'
        'data "aws_vpc" "self" { id = module.net.vpc_id }\n'
        'resource "aws_security_group" "sg" { vpc_id = module.net.app_vpc }\n')
    assert [n["address"] for n in facts["networks"]] == ["module.net.aws_vpc.v"]


def test_a_subnet_lookup_with_a_literal_key_takes_its_tier_from_its_name(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'resource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }\n'
        'data "aws_subnet" "private" {\n  for_each = toset(["a"])\n  vpc_id = aws_vpc.v.id\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.aws_subnet.private["a"].id }\n')
    assert [(p["tier"], p["via"]) for p in facts["placements"]] == [("private", "private.a")]


def test_a_subnet_lookup_takes_the_tier_word_nearest_the_end_of_its_name(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'data "aws_vpc" "isolated_vpc" {\n  tags = { Name = "isolated" }\n}\n'
        'data "aws_subnet" "isolated_vpc_public" { vpc_id = data.aws_vpc.isolated_vpc.id }\n'
        'resource "aws_instance" "lb" { subnet_id = data.aws_subnet.isolated_vpc_public.id }\n')
    assert [(p["tier"], p["via"]) for p in facts["placements"]] == [("public", "isolated_vpc_public")]


def test_a_peer_lookup_whose_name_starts_a_subnet_output_never_takes_it_from_its_state(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, TRS.format("net") +
        'data "aws_vpc" "private" { tags = { Name = "private-peer" } }\n'
        'resource "aws_security_group" "g" { vpc_id = data.terraform_remote_state.net.outputs.vpc_id }\n'
        'resource "aws_vpc_peering_connection" "p" {\n  vpc_id = data.terraform_remote_state.net.outputs.vpc_id\n'
        '  peer_vpc_id = data.aws_vpc.private.id\n}\n'
        'resource "aws_instance" "i" { subnet_id = data.terraform_remote_state.net.outputs.private_subnet_ids[0] }\n')
    assert placed_in(facts, "name") == {"aws_instance.i": "vpc"}


TFE = 'data "tfe_outputs" "n" {\n  organization = "acme"\n  workspace = "network"\n}\n'
CREATE_VPC = ('variable "create_vpc" { default = false }\n'
              'resource "aws_vpc" "this" {\n  count = var.create_vpc ? 1 : 0\n  cidr_block = "10.0.0.0/16"\n}\n' + TFE)


def test_a_lookup_whose_selector_reads_a_local_and_a_remote_network_picks_neither(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, CREATE_VPC +
        'locals {\n  vpc_id = var.create_vpc ? aws_vpc.this[0].id : data.tfe_outputs.n.values.vpc_id\n}\n'
        'data "aws_vpc" "selected" { id = local.vpc_id }\n'
        'data "aws_subnets" "private" {\n  filter {\n    name = "vpc-id"\n    values = [data.aws_vpc.selected.id]\n  }\n}\n'
        'resource "aws_instance" "app" { subnet_id = data.aws_subnets.private.ids[0] }\n')
    assert placed_in(facts) == {"aws_instance.app": "data.aws_vpc.selected"}  # never in aws_vpc.this, which count 0 skips


def test_a_lookup_by_a_remote_network_output_is_that_network(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, TFE +
        'data "aws_vpc" "shared" { id = data.tfe_outputs.n.values.vpc_id }\n'
        'resource "aws_security_group" "sg" { vpc_id = data.tfe_outputs.n.values.vpc_id }\n'
        'resource "aws_instance" "app" { subnet_id = data.tfe_outputs.n.values.private_subnet_ids[0] }\n'
        'resource "aws_security_group" "db" { vpc_id = data.aws_vpc.shared.id }\n'
        'data "aws_subnets" "private" {\n  filter {\n    name = "vpc-id"\n    values = [data.aws_vpc.shared.id]\n  }\n}\n'
        'resource "aws_db_subnet_group" "db" { subnet_ids = data.aws_subnets.private.ids }\n')
    assert [n["address"] for n in facts["networks"]] == ["data.tfe_outputs.n.values.vpc_id"]
    assert set(placed_in(facts)) == {"aws_instance.app", "aws_db_subnet_group.db"}


def test_a_subnet_lookup_in_a_network_read_beside_a_subnet_output_is_in_that_network(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, TFE +
        'locals {\n  net = {\n    vpc_id = data.tfe_outputs.n.values.vpc_id\n'
        '    subnet_ids = data.tfe_outputs.n.values.private_subnet_ids\n  }\n}\n'
        'data "aws_subnet" "private" {\n  vpc_id = lookup(local.net, "vpc_id", null)\n'
        '  filter {\n    name = "tag:Tier"\n    values = ["private"]\n  }\n}\n'
        'resource "aws_instance" "app" { subnet_id = data.aws_subnet.private.id }\n')
    assert placed_in(facts, "name") == {"aws_instance.app": "vpc"}
    assert [n["name"] for n in facts["networks"]] == ["vpc"] and mark_reason(facts, "aws_instance.app") is None
