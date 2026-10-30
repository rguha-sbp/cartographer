"""Integration hints: external hosts, parameter names and integration folders in the code Terraform deploys."""
from __future__ import annotations

import os
import re
from pathlib import Path

from cartographer.tf_policies import unq
from cartographer.tf_roots import code_roots

# Scaling axis: distinct hosts, parameter names or integration folders in one stack. Highest count first; the rest is cut.
HINT_CAP = 60
KINDS = ("host", "param", "module")
MAX_FILE_BYTES = 200_000
MAX_FILES = 5000
SKIP_DIRS = {"tests", "test", "node_modules", "venv", "site-packages", "__pycache__", "vendor", "vendored", "dist", "build"}
CODE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".go", ".java", ".kt", ".rb", ".sh", ".json", ".yaml", ".yml", ".toml"}
TEST_FILE = re.compile(r"^(test_.*|.*_test\.\w+|.*\.test\.\w+|conftest\.py)$")
INTEGRATION_DIRS = re.compile(r"^(integrations?|processors?|clients?|connectors?|event_processors?)$")
URL = re.compile(r"https?://([A-Za-z0-9{}_.\-]+\.[A-Za-z]{2,})")
NOT_EXTERNAL = re.compile(
    r"(^|\.)(amazonaws\.com|amazonaws\.com\.cn|localhost|w3\.org|json-schema\.org|xmlsoap\.org|purl\.org)$"
    r"|^example\.(com|org|net)$"
)
PARAM_CONTEXT = re.compile(r"ssm|param|secret", re.IGNORECASE)
QUOTED = re.compile(r"""["']([^"'\s]+)["']""")
SSM_NAME = re.compile(r"/[\w.\-{}$]+(?:/[\w.\-{}$]+)+")
SECRET_NAME = re.compile(r"(?!(?:application|text|image|multipart)/)[\w.\-]+(?:/[\w.\-{}$]+)+")
PARAM_TYPES = {"aws_ssm_parameter", "aws_secretsmanager_secret"}
TF_SUFFIXES = ("*.tf", "*.tfvars")

Occurrence = tuple[str, str, str, int, str | None]


def _line_hints(line: str) -> list[tuple[str, str]]:
    found = [("host", m[1].lower().rstrip(".")) for m in URL.finditer(line)]
    found = [(k, v) for k, v in found if not NOT_EXTERNAL.search(v)]
    if PARAM_CONTEXT.search(line):
        secret = "secret" in line.lower()
        for m in QUOTED.finditer(line):
            name = m[1]
            if SSM_NAME.fullmatch(name) or (secret and "://" not in line and SECRET_NAME.fullmatch(name)):
                found.append(("param", name))
    return found


def _scan_text(path: Path, rel: str, owner: str | None, hosts_only: bool = False) -> list[Occurrence]:
    if path.stat().st_size > MAX_FILE_BYTES:
        return []
    out = []
    for no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if line.lstrip().startswith(("#", "//")):
            continue
        out += [(k, v, rel, no, owner) for k, v in _line_hints(line) if not hosts_only or k == "host"]
    return out


def _scan_root(root: Path, owner: str | None, repo_root: Path, budget: list[int]) -> list[Occurrence]:
    out: list[Occurrence] = []
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        here_path = Path(here)
        if INTEGRATION_DIRS.match(here_path.name):
            out += [("module", d, str((here_path / d).relative_to(repo_root)), 1, owner)
                    for d in dirs if not d.startswith("_")]
        for name in sorted(files):
            if Path(name).suffix in CODE_SUFFIXES and not TEST_FILE.match(name) and budget[0] > 0:
                budget[0] -= 1
                path = here_path / name
                out += _scan_text(path, str(path.relative_to(repo_root)), owner)
    return out


def _terraform(insts: list, resources: list, repo_root: Path) -> list[Occurrence]:
    out: list[Occurrence] = []
    for directory in sorted({i.mod.directory for i in insts}):
        for pattern in TF_SUFFIXES:
            for path in sorted(directory.glob(pattern)):
                out += _scan_text(path, str(path.relative_to(repo_root)), None, hosts_only=True)
    for r in resources:
        if r.type in PARAM_TYPES and "name" in r.block.body:
            out.append(("param", unq(r.block.body["name"]), r.block.file, r.block.line, r.address))
    return out


def collect_hints(insts: list, resources: list, repo_root: Path) -> dict:
    budget = [MAX_FILES]
    seen = _terraform(insts, resources, repo_root)
    for root, owner in code_roots(insts, repo_root):
        seen += _scan_root(root, owner, repo_root, budget)
    merged: dict[tuple[str, str], dict] = {}
    for kind, value, file, line, owner in seen:
        hint = merged.setdefault((kind, value), {"kind": kind, "value": value, "file": file, "line": line,
                                                 "owner": owner, "count": 0})
        hint["count"] += 1
    hints, cut = [], {}
    for kind in KINDS:
        ranked = sorted((h for h in merged.values() if h["kind"] == kind), key=lambda h: (-h["count"], h["value"]))
        hints += ranked[:HINT_CAP]
        cut[kind] = max(len(ranked) - HINT_CAP, 0)
    return {"hints": [{"id": f"h{i}", **h} for i, h in enumerate(hints, 1)], "hints_cut": cut}
