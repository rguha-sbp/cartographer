"""How a reference is followed: attribute paths, object members, indexes, hops and the read budget."""
import time
from pathlib import Path

import pytest
from network_tf import S3_STATE, TRS, count_calls, extract_tf, placed_in, tfe_state, vpc_networks

from cartographer import tf_extract


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
    (tmp_path / "main.tf").write_text(tfe_state("net").replace("shared_vpc_id", 'vpcs["blue"]') + "".join(
        f'resource "aws_security_group" "{n}" {{ vpc_id = data.tfe_outputs.net.values.{ref} }}\n'
        for n, ref in (("g", 'vpcs["green"]'), ("x", "vpc_ids[0]"), ("y", "vpc_ids[1]"))))
    names = sorted(n["name"] for n in tf_extract.extract(Path("."), tmp_path)["networks"])
    assert names == ["vpc[0]", "vpc[1]", "vpcs.blue", "vpcs.green"]


def test_a_local_that_reads_itself_gives_no_network_and_no_crash(tmp_path: Path) -> None:
    tf = 'locals {\n  a = local.a.x\n}\nresource "aws_security_group" "sg" { vpc_id = local.a.x }\n'
    assert vpc_networks(tmp_path, tf) == []


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
    assert placed_in(tf_extract.extract(Path("."), tmp_path)) == {"aws_instance.i": "module.net.aws_vpc.v"}


def test_a_quoted_local_keeps_the_attribute_path(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_vpc" "a" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_vpc" "b" { cidr_block = "10.1.0.0/16" }\n'
        'locals {\n  net = { a = aws_vpc.a.id, b = aws_vpc.b.id }\n  alias = "${local.net}"\n}\n'
        'resource "aws_subnet" "private" {\n  vpc_id = local.alias.b\n  cidr_block = "10.1.1.0/24"\n}\n'
        'resource "aws_instance" "i" { subnet_id = aws_subnet.private.id }\n')
    assert placed_in(tf_extract.extract(Path("."), tmp_path)) == {"aws_instance.i": "aws_vpc.b"}


def test_a_path_after_an_index_that_is_no_literal_reads_each_element(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        tfe_state("networking") + 'locals {\n  nets = {\n    a = {\n'
        '      public_subnet_id = data.tfe_outputs.net.values.shared_vpc_public_subnet_ids\n'
        '      private_subnet_id = data.tfe_outputs.net.values.shared_vpc_private_subnet_ids\n    }\n  }\n}\n'
        'resource "aws_instance" "i" {\n  for_each = local.nets\n  subnet_id = local.nets[each.key].private_subnet_id\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [p["tier"] for p in facts["placements"]] == ["private"]


def test_two_vpc_outputs_of_one_object_are_two_networks(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, S3_STATE +
        'resource "aws_security_group" "app" { vpc_id = data.terraform_remote_state.net.outputs.network.app_vpc_id }\n'
        'resource "aws_security_group" "db" { vpc_id = data.terraform_remote_state.net.outputs.network.db_vpc_id }\n'
        'resource "aws_instance" "app" {\n'
        '  subnet_id = data.terraform_remote_state.net.outputs.network.app_vpc_private_subnet_ids[0]\n}\n'
        'resource "aws_instance" "db" {\n'
        '  subnet_id = data.terraform_remote_state.net.outputs.network.db_vpc_private_subnet_ids[0]\n}\n')
    assert sorted(n["name"] for n in facts["networks"]) == ["network.app-vpc", "network.db-vpc"]
    assert placed_in(facts, "name") == {"aws_instance.app": "network.app-vpc", "aws_instance.db": "network.db-vpc"}


def test_a_path_after_a_function_reads_each_reference_in_it(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'data "tfe_outputs" "net" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        'locals {\n  a = {\n    vpc_id = data.tfe_outputs.net.values.app_vpc_id\n'
        '    peer_vpc_id = data.tfe_outputs.net.values.db_vpc_id\n  }\n  cfg = merge(local.a, {})\n}\n'
        'resource "aws_security_group" "s" { vpc_id = local.cfg.vpc_id }\n')
    assert [n["name"] for n in facts["networks"]] == ["app-vpc"]


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
    extract_tf(tmp_path, tf + 'resource "aws_instance" "i" { subnet_id = data.aws_subnet.a0.id }\n')
    assert calls < 2000


def test_the_network_argument_of_a_counted_resource_is_followed(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path,
        'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
        'resource "aws_subnet" "a" {\n  count = 2\n  vpc_id = aws_vpc.main.id\n}\n'
        'resource "aws_subnet" "b" {\n  vpc_id = aws_subnet.a[0].vpc_id\n  tags = { Name = "public-b" }\n}\n'
        'resource "aws_instance" "i" { subnet_id = aws_subnet.b.id }\n')
    assert placed_in(facts) == {"aws_instance.i": "aws_vpc.main"}


def test_a_local_that_reads_itself_several_times_takes_linear_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cartographer.clouds import refs
    count_calls(monkeypatch, refs, "_follow", 1000)
    facts = extract_tf(tmp_path,
        'locals {\n  a = "${local.a.x}-${local.a.y}-${local.a.z}"\n}\n'
        'resource "aws_lambda_function" "f" {\n  vpc_config {\n    subnet_ids = [local.a]\n  }\n}\n')
    assert placed_in(facts) == {}


@pytest.mark.parametrize(("length", "names"), [(90, ["vpc"]), (500, [])])
def test_a_chain_of_locals_is_followed_up_to_the_hop_limit(tmp_path: Path, length: int, names: list[str]) -> None:
    chain = "".join(f"  a{i} = local.a{i + 1}\n" for i in range(length))
    facts = extract_tf(tmp_path, S3_STATE + f"locals {{\n{chain}  a{length} = data.terraform_remote_state.net.outputs.vpc_id\n}}\n"
                     'resource "aws_security_group" "s" { vpc_id = local.a0 }\n')
    assert [n["name"] for n in facts["networks"]] == names


def test_a_long_chain_of_lookups_does_not_crash(tmp_path: Path) -> None:
    chain = "".join(f'data "aws_vpc" "v{i}" {{ id = data.aws_vpc.v{i - 1}.id }}\n' for i in range(1, 300))
    facts = extract_tf(tmp_path, 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
                     'data "aws_vpc" "v0" { id = aws_vpc.main.id }\n' + chain +
                     'resource "aws_security_group" "s" { vpc_id = data.aws_vpc.v299.id }\n')
    assert next(n["address"] for n in facts["networks"]) == "aws_vpc.main"


def test_a_quoted_key_of_non_ascii_digits_does_not_crash(tmp_path: Path) -> None:
    facts = extract_tf(tmp_path, 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n'
                     'locals { l = [{ vpc = aws_vpc.main.id }] }\n'
                     'resource "aws_security_group" "s" { vpc_id = local.l["\u00b2"].vpc }\n')
    assert [n["address"] for n in facts["networks"]] == ["aws_vpc.main"]


@pytest.mark.parametrize("level", ["[local.l{n}.a, local.l{n}.b, local.l{n}.c]", "merge(local.l{n}.a, local.l{n}.b, local.l{n}.c)"])
def test_paths_that_fan_out_at_every_level_stop_at_the_read_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: str) -> None:
    from cartographer.clouds import refs
    count_calls(monkeypatch, refs, "_follow", 3 * refs.MAX_READS)
    chain = "".join(f"  l{i} = {level.format(n=i + 1)}\n" for i in range(20))
    facts = extract_tf(tmp_path, f'locals {{\n{chain}  l20 = "x"\n}}\n'
                     'resource "aws_security_group" "s" { vpc_id = local.l0.vpc_id }\n')
    assert facts["networks"] == []


@pytest.mark.parametrize(("local", "subnet", "network"), [
    (("merge({ vpc_id = data.terraform_remote_state.net.outputs.vpc_id, "
      "private_subnet_ids = data.terraform_remote_state.net.outputs.private_subnet_ids }, var.overrides)"),
     "local.net.private_subnet_ids[0]", "vpc"),
    ("merge(data.terraform_remote_state.net.outputs.vpcs, { dr = data.terraform_remote_state.dr.outputs.vpc })",
     "local.net.blue.private_subnet_ids[0]", "vpcs.blue"),
    (("merge({ vpc_id = try(var.overrides.vpc_id, data.terraform_remote_state.net.outputs.vpc_id), "
      "private_subnet_ids = try(var.overrides.subnets, data.terraform_remote_state.net.outputs.private_subnet_ids) }, var.overrides)"),
     "local.net.private_subnet_ids[0]", "vpc"),
    (("merge({ private_subnet_ids = var.overrides == {} ? data.terraform_remote_state.net.outputs.private_subnet_ids "
      ": data.terraform_remote_state.dr.outputs.private_subnet_ids, vpc_id = data.terraform_remote_state.net.outputs.vpc_id }, {})"),
     "local.net.private_subnet_ids[0]", "vpc"),
    (("merge({ a = { vpc_id = data.terraform_remote_state.net.outputs.vpc_id, "
      "private_subnet_ids = data.terraform_remote_state.net.outputs.private_subnet_ids } }, {})"),
     "local.net.a.private_subnet_ids[0]", "vpc"),
])
def test_a_path_reads_only_the_member_of_an_object_inside_a_function_it_names(tmp_path: Path, local: str, subnet: str, network: str) -> None:
    facts = extract_tf(tmp_path, TRS.format("net") + TRS.format("dr") +
        f'variable "overrides" {{ default = {{}} }}\nlocals {{\n  net = {local}\n}}\n'
        f'resource "aws_security_group" "g" {{ vpc_id = {subnet.replace("private_subnet_ids[0]", "vpc_id")} }}\n'
        f'resource "aws_instance" "i" {{ subnet_id = {subnet} }}\n')
    assert placed_in(facts, "name") == {"aws_instance.i": network}
    assert [n["name"] for n in facts["networks"]] == [network]


def test_a_path_through_a_large_object_inside_a_function_reads_in_linear_time(tmp_path: Path) -> None:
    members = ", ".join(f"k{i} = data.terraform_remote_state.net.outputs.vpcs.v{i}" for i in range(3000))
    started = time.monotonic()
    facts = extract_tf(tmp_path, TRS.format("net") + f"locals {{\n  net = merge({{ {members} }}, {{}})\n}}\n"
        'resource "aws_security_group" "g" { vpc_id = local.net.k5.id }\n'
        'resource "aws_instance" "i" { subnet_id = local.net.k5.private_subnet_ids[0] }\n')
    assert time.monotonic() - started < 3  # one scan of the text, not one per reference: 9 s before
    assert [n["name"] for n in facts["networks"]] == ["vpcs.v5"]


@pytest.mark.parametrize("vpc_id", ['lookup(local.vpcs.blue, "vpc_id", null)', 'local.vpc_ids["blue"]'])
def test_a_subnet_output_beside_a_network_in_an_object_is_never_a_network(tmp_path: Path, vpc_id: str) -> None:
    facts = extract_tf(tmp_path, TRS.format("net") +
        'locals {\n  vpcs = { blue = {\n    vpc_id = data.terraform_remote_state.net.outputs.blue_vpc_id\n'
        '    private_subnet_ids = data.terraform_remote_state.net.outputs.blue_private_subnet_ids\n  } }\n'
        '  vpc_ids = { for k, v in local.vpcs : k => v.vpc_id }\n}\n'
        f'resource "aws_security_group" "g" {{ vpc_id = {vpc_id} }}\n')
    assert [n["name"] for n in facts["networks"]] == ["blue-vpc"]


@pytest.mark.parametrize(("nets", "read"), [
    ("concat([{ {0} }], var.extra)", "local.nets[count.index]"),
    ("concat([{ {0} }], var.extra)", "local.nets[0]"),
    ("one([{ {0} }])", "local.nets"),  # a function that drops the list: the attribute passes the list level
])
def test_a_path_reads_only_the_member_of_a_list_element_inside_a_function(tmp_path: Path, nets: str, read: str) -> None:
    members = ("vpc_id = data.tfe_outputs.n.values.vpc_id,"
               " subnet_ids = data.tfe_outputs.n.values.private_subnet_ids")
    facts = extract_tf(tmp_path, 'variable "extra" { default = [] }\n'
        'data "tfe_outputs" "n" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        f'locals {{\n  nets = {nets.replace("{0}", members)}\n}}\n'
        f'resource "aws_security_group" "sg" {{\n  count = 1\n  vpc_id = {read}.vpc_id\n}}\n'
        f'resource "aws_instance" "app" {{\n  count = 1\n  subnet_id = {read}.subnet_ids[0]\n}}\n')
    assert [n["name"] for n in facts["networks"]] == ["vpc"]
    assert placed_in(facts, "name") == {"aws_instance.app": "vpc"}
