import json
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "cartographer" / "SKILL.md"
BANNED = "—–‘’“”"


def test_versions_agree() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    pins = set(re.findall(r"cartographer@v(\d+\.\d+\.\d+)", (ROOT / "README.md").read_text()))
    assert pins == {pyproject} == {plugin["version"]}


def test_marketplace_lists_the_plugin_at_the_repo_root() -> None:
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert market["name"] == "cartographer"
    assert [(p["name"], p["source"]) for p in market["plugins"]] == [("cartographer", "./")]


def test_every_plugin_invocation_goes_through_the_launcher() -> None:
    launcher = '"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" '
    for path in (SKILL, ROOT / "commands" / "view.md"):
        text = path.read_text()
        assert "uvx" not in text and "CARTOGRAPHER_FROM" not in text, path
        assert "claude -p" not in text and "cartographer-snapshot" not in text, path
        assert text.count(launcher) >= 1, path
        assert text.count("${CLAUDE_PLUGIN_ROOT}") == text.count(launcher), path
        bare = [ln for ln in text.splitlines() if "To reopen later" not in ln and re.search(r"\bcartographer (extract|prompt|build|image|snapshot|view|check|docs)\b", ln)]
        assert not bare, (path, bare)


def test_launcher_is_posix_sh_and_executable() -> None:
    launcher = ROOT / "scripts" / "cartographer"
    assert launcher.read_text().startswith("#!/bin/sh\n")
    staged = subprocess.run(["git", "ls-files", "--stage", "scripts/cartographer"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout
    assert staged.startswith("100755 "), "the launcher must be committed executable: it ships with that mode"
    assert "[[" not in launcher.read_text()


def test_user_facing_text_has_no_dashes_or_smart_quotes() -> None:
    package = ROOT / "src" / "cartographer"
    for path in (SKILL, ROOT / "README.md", *(package / n for n in ("curate_prompt.md", "describe_prompt.md", "INTERVIEW.md"))):
        assert not [c for c in path.read_text() if c in BANNED], path


def test_pre_commit_hook_runs_check_on_the_diagrams_folder() -> None:
    hook = (ROOT / ".pre-commit-hooks.yaml").read_text()
    for line in ("- id: cartographer-check", "entry: cartographer check docs/architecture/diagrams", "language: python",
                 "files: ^docs/architecture/diagrams/", "pass_filenames: false"):
        assert line in hook
