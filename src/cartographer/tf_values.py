"""Helpers every Terraform reader shares: text of an HCL value, attribute bodies and attribute search."""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from cartographer.tf_policies import unq

UNRESOLVED = object()  # the attribute exists but is not a literal (reference, local, var without default)


def text(obj: Any) -> str:
    return obj if isinstance(obj, str) else json.dumps(obj, default=str)


def attrs(body: dict) -> dict[str, Any]:
    return {k: v for k, v in body.items() if not k.startswith("__")}


def find(obj: Any, key: re.Pattern[str]) -> Iterator[Any]:
    """Values of every attribute whose name matches `key`, at any block depth."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if key.fullmatch(unq(k)):
                yield v
            else:
                yield from find(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from find(v, key)
