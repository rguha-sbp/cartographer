"""Inputs of the curation step: the schema, the prompt and the key that says whether a curated file is current."""

import hashlib
import json
from pathlib import Path

from cartographer.diagram_model import AWS_ICONS, BRAND_ICONS, GENERIC_ICONS

HERE = Path(__file__).parent
SCHEMA = HERE / "curated.schema.json"
PROMPT = HERE / "curate_prompt.md"


def schema_text() -> str:
    """The schema the curation must satisfy: the static file with the node `service` and the `icon` enums injected."""
    schema = json.loads(SCHEMA.read_text())
    service = schema["properties"]["nodes"]["items"]["properties"]["service"]
    service["enum"] = [*sorted(AWS_ICONS), "other"]
    icons = [*sorted(GENERIC_ICONS), *sorted(BRAND_ICONS), "none"]
    for kind in ("nodes", "externals"):
        schema["properties"][kind]["items"]["properties"]["icon"]["enum"] = icons
    schema["properties"]["externals"]["items"]["properties"]["service"]["enum"] = sorted(AWS_ICONS)
    return json.dumps(schema, indent=2, sort_keys=True)


def render_prompt(facts_path: Path, repo_root: Path, schema_path: Path, output_path: Path, key: str) -> str:
    fills = {
        "facts_path": facts_path,
        "repo_root": repo_root,
        "schema_path": schema_path,
        "output_path": output_path,
        "inputs_sha256": key,
    }
    text = PROMPT.read_text()
    for name, value in fills.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def inputs_sha256(facts_path: Path) -> str:
    """Key of a curation: facts bytes, prompt template and schema; never a path or a model."""
    h = hashlib.sha256(facts_path.read_bytes())
    for part in (PROMPT.read_text(), schema_text()):
        h.update(b"\0" + part.encode())
    return h.hexdigest()
