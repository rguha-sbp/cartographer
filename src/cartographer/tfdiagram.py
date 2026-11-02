"""Inputs of the curation step: the schema, the prompt and the key that says whether a curated file is current."""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
SCHEMA = HERE / "curated.schema.json"
PROMPT = HERE / "curate_prompt.md"
DESCRIBE_PROMPT = HERE / "describe_prompt.md"
VIEW_NAMES = {"l7": "Layer 7"}


def schema_text() -> str:
    """The schema the curation must satisfy: the static file, normalised."""
    return json.dumps(json.loads(SCHEMA.read_text()), indent=2, sort_keys=True)


def fill(template: Path, **fills: object) -> str:
    """The text of `template` with every `{name}` replaced by its fill."""
    text = template.read_text()
    for name, value in fills.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def render_prompt(facts_path: Path, repo_root: Path, schema_path: Path, output_path: Path, key: str) -> str:
    return fill(PROMPT, facts_path=facts_path, repo_root=repo_root, schema_path=schema_path, output_path=output_path,
                inputs_sha256=key)


def render_describe_prompt(schema_path: Path, output_path: Path, interview_path: Path) -> str:
    return fill(DESCRIBE_PROMPT, schema_path=schema_path, output_path=output_path, interview_path=interview_path)


def inputs_sha256(facts_path: Path) -> str:
    """Key of a curation: facts bytes, prompt template and schema; never a path or a model."""
    h = hashlib.sha256(facts_path.read_bytes())
    for part in (PROMPT.read_text(), schema_text()):
        h.update(b"\0" + part.encode())
    return h.hexdigest()


def diagram_title(curated: dict) -> str:
    return f"{VIEW_NAMES[curated['view']]} diagram for {curated['system']}"
