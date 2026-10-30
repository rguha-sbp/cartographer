import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "cartographer" / "SKILL.md"
BANNED = "—–‘’“”"


def test_versions_agree() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    pins = set(re.findall(r"cartographer@v(\d+\.\d+\.\d+)", SKILL.read_text()))
    assert pins == {pyproject} == {plugin["version"]}


def test_marketplace_lists_the_plugin_at_the_repo_root() -> None:
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert market["name"] == "cartographer"
    assert [(p["name"], p["source"]) for p in market["plugins"]] == [("cartographer", "./")]


def test_skill_calls_the_tool_through_uvx_and_cartographer_from() -> None:
    text = SKILL.read_text()
    assert 'uvx --from "${CARTOGRAPHER_FROM:-git+ssh://git@github.com/rguha-sbp/cartographer@v' in text
    assert "claude -p" not in text and "cartographer-snapshot" not in text


def test_user_facing_text_has_no_dashes_or_smart_quotes() -> None:
    for path in (SKILL, ROOT / "README.md", ROOT / "src" / "cartographer" / "curate_prompt.md"):
        assert not [c for c in path.read_text() if c in BANNED], path


def test_pre_commit_hook_runs_check_on_the_diagrams_folder() -> None:
    hook = (ROOT / ".pre-commit-hooks.yaml").read_text()
    for line in ("- id: cartographer-check", "entry: cartographer check docs/architecture/diagrams", "language: python",
                 "files: ^docs/architecture/diagrams/", "pass_filenames: false"):
        assert line in hook
