"""Which integration hints the curator neither drew as an external nor listed as omitted."""
from __future__ import annotations

import re


def _named_in(value: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(value)}(?![\w-])", text, re.IGNORECASE) is not None


def unaccounted(hints: list[dict], externals: list[dict], omitted: list[dict]) -> list[str]:
    cited = " ".join(
        f"{ev['file']} {ev['contains']}" for x in externals for ev in x["evidence"] if "file" in ev
    )
    waived = {o["hint"].strip().lower() for o in omitted}
    return [
        f"{h['id']} {h['kind']} {h['value']} ({h['file']}:{h['line']})"
        for h in hints
        if not _named_in(h["value"], cited) and not {h["id"], h["value"].lower()} & waived
    ]
