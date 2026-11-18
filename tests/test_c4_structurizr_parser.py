"""Each case's workspace through the real Structurizr: it must parse, and every view must show what its page draws.

Optional: set CARTOGRAPHER_STRUCTURIZR to the command that runs Structurizr, for example
`java -jar structurizr.war` (Java 21) or `docker run --rm -v "$PWD:/usr/local/structurizr" structurizr/structurizr`.
"""

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest
from c4_structurizr_cases import CASES

from cartographer import c4_structurizr, c4_views

COMMAND = os.environ.get("CARTOGRAPHER_STRUCTURIZR")
pytestmark = pytest.mark.skipif(not COMMAND, reason="set CARTOGRAPHER_STRUCTURIZR to run Structurizr")


def _export(model: dict, folder: Path) -> dict:
    dsl = folder / "workspace.dsl"
    dsl.write_text(c4_structurizr.workspace(model), encoding="utf-8")
    run = subprocess.run([*shlex.split(COMMAND), "export", "-w", str(dsl), "-f", "json", "-o", str(folder)],
                         capture_output=True, text=True, timeout=300, check=False)
    assert run.returncode == 0 and (folder / "workspace.json").exists(), run.stdout + run.stderr
    return json.loads((folder / "workspace.json").read_text(encoding="utf-8"))


def _walk(element: dict, found: dict[str, dict]) -> None:
    found[element["id"]] = element
    for key in ("containers", "components", "children", "infrastructureNodes", "containerInstances"):
        for child in element.get(key, []):
            _walk(child, found)


def _index(workspace: dict) -> tuple[dict[str, dict], dict[str, dict], dict[str, str]]:
    """Elements by id, relationships by id, and a name for each element (a container instance: its container's)."""
    found: dict[str, dict] = {}
    model = workspace["model"]
    for element in (*model.get("people", []), *model.get("softwareSystems", []), *model.get("deploymentNodes", [])):
        _walk(element, found)
    relationships = {r["id"]: r for e in found.values() for r in e.get("relationships", [])}
    names = {eid: found[e["containerId"]]["name"] if "containerId" in e else e["name"] for eid, e in found.items()}
    return found, relationships, names


def _shown(view: dict, relationships: dict, names: dict) -> tuple[set[str], set[tuple]]:
    elements = {names[e["id"]] for e in view.get("elements", [])}
    arrows = set()
    for item in view.get("relationships", []):
        r = relationships[item["id"]]
        arrows.add((names[r["sourceId"]], names[r["destinationId"]], item.get("description") or r["description"],
                    r.get("technology") or None))
    return elements, arrows


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_view_shows_what_its_page_draws(case, tmp_path):
    model = CASES[case]()
    workspace = _export(model, tmp_path)
    _, relationships, names = _index(workspace)
    by_key = {v["key"]: v for kind, views in workspace["views"].items() if kind.endswith("Views") for v in views}
    pages = [v for v in c4_views.views(model) if v.kind != c4_views.CODE]
    assert set(by_key) == {page.slug for page in pages}
    model_names = {e["id"]: e["name"] for e in model["elements"]}
    for page in pages:
        view, curated = by_key[page.slug], page.curated
        assert view["title"] == page.title
        elements, arrows = _shown(view, relationships, names)
        if page.kind == c4_views.DEPLOYMENT:
            hosted = {i["container"] for i in model["deployment"]["instances"]}
            expected = {(model_names[e["src"].split(".", 1)[1]], model_names[e["dst"].split(".", 1)[1]], e["text"],
                         e["technology"]) for e in curated["edges"]}
            assert arrows == expected, page.slug
            assert {model_names[c] for c in hosted} <= elements, page.slug
            continue
        expected = {(model_names[e["src"]], model_names[e["dst"]], e["text"], e["technology"])
                    for e in curated["edges"]}
        if page.kind == c4_views.DYNAMIC:
            steps = sorted(view.get("relationships", []), key=lambda item: int(item["order"]))
            assert [int(item["order"]) for item in steps] == [e["step"] for e in curated["edges"]], page.slug
            assert {a[:3] for a in arrows} == {e[:3] for e in expected}, page.slug
            continue
        assert elements == {model_names[n["id"]] for n in (*curated["nodes"], *curated["externals"])}, page.slug
        assert arrows == expected, page.slug
