import json
from pathlib import Path

import pytest

from cartographer import gen_drawio, tf_layout
from cartographer.curated_format import upgrade

GOLDEN = Path(__file__).parent / "golden"
CASES = sorted(p.name.removesuffix(".curated.json") for p in GOLDEN.glob("*.curated.json"))


def load_curated(path: Path) -> dict:
    return upgrade(json.loads(path.read_text()))


def test_golden_cases_are_present() -> None:
    assert len(CASES) >= 4


@pytest.mark.parametrize("case", CASES)
def test_layout_and_render_match_the_golden(case: str) -> None:
    curated = load_curated(GOLDEN / f"{case}.curated.json")
    diagram = tf_layout.layout(curated)
    assert gen_drawio.render(diagram, page_id="golden", page_name="golden") == (GOLDEN / f"{case}.drawio").read_text()
