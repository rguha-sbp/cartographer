"""IAM policy expression -> Statement list. Handles jsonencode, templatefile and file; no HCL evaluation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import hcl2

OPTS = hcl2.SerializationOptions(with_comments=False)
JSONENC = re.compile(r"\$\{jsonencode\((.*)\)\}", re.DOTALL)
TEMPLATEFILE = re.compile(r'\$\{templatefile\(\s*"([^"]+)"\s*,\s*(.*)\)\}', re.DOTALL)
FILE = re.compile(r'\$\{file\(\s*"([^"]+)"\s*\)\}')
TOKEN = re.compile(r"\$\{([^}]*)\}|%\{[^}]*\}")
UNKNOWN = "${?}"


def unq(value: Any) -> str:
    return str(value).strip('"')


def norm_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {unq(k): norm_keys(v) for k, v in obj.items()}
    return [norm_keys(v) for v in obj] if isinstance(obj, list) else obj


def hcl_value(src: str) -> Any:
    try:
        return norm_keys(hcl2.loads(f"x = {src.strip()}", serialization_options=OPTS)["x"])
    except Exception:  # noqa: BLE001 lark errors
        return None


def read_file(ref: str, directory: Path) -> str | None:
    path = Path(ref.replace("${path.module}", str(directory)))
    return path.read_text() if "${" not in str(path) and path.is_file() else None


def render_template(tpl: str, names: set[str]) -> str:
    """Make a template valid JSON: `${name}` becomes a placeholder, other interpolations and %{} directives vanish."""
    out, pos, in_str = [], 0, False
    for m in TOKEN.finditer(tpl):
        chunk = tpl[pos:m.start()]
        in_str ^= len(re.findall(r'(?<!\\)"', chunk)) % 2 == 1
        out.append(chunk)
        pos = m.end()
        if m[1] is not None:
            name = m[1].strip()
            token = f"@@{name}@@" if name in names else UNKNOWN
            out.append(token if in_str else f'"{token}"')
    out.append(tpl[pos:])
    return "".join(out)


def fill(obj: Any, values: dict[str, Any]) -> Any:
    """Swap template placeholders for the HCL expressions the template was called with."""
    if isinstance(obj, str):
        return re.sub(r"@@(\w+)@@", lambda m: str(values[m[1]]), obj)
    if isinstance(obj, dict):
        return {k: fill(v, values) for k, v in obj.items()}
    return [fill(v, values) for v in obj] if isinstance(obj, list) else obj


def policy_doc(expr: str, directory: Path) -> Any:
    """Policy document behind a jsonencode, templatefile or file expression, or None."""
    if m := JSONENC.fullmatch(expr):
        return hcl_value(m[1])
    if m := TEMPLATEFILE.fullmatch(expr):
        values = hcl_value(m[2])
        tpl = read_file(m[1], directory)
        if tpl is None or not isinstance(values, dict):
            return None
        try:
            return fill(json.loads(render_template(tpl, set(values))), values)
        except ValueError:
            return None
    if m := FILE.fullmatch(expr):
        try:
            return json.loads(read_file(m[1], directory) or "")
        except ValueError:
            return None
    return None


def doc_statements(doc: Any) -> list[dict] | None:
    stmts = doc.get("Statement") if isinstance(doc, dict) else None
    return [stmts] if isinstance(stmts, dict) else stmts if isinstance(stmts, list) else None
