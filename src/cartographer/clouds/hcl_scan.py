"""A scan of HCL expression text as python-hcl2 writes it (`${merge({vpc_id = x}, var.o)}`, `"private-${var.zone}"`):
the object keys a position sits under, and the string literals a value holds. One pass tracks brackets, strings and
interpolations, so a `}` inside a string or a `=` inside a condition never ends or starts an object member."""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

KEY = re.compile(r'([A-Za-z_][\w-]*|"[^"]*")\s*=(?![=>])')  # `key =` that starts an object member, never `==` or `=>`
NOT_KEY_START = re.compile(r"[\w.-]")  # what a key never follows: `a.b = ` is no member
TEMPLATES = ("${", "%{")  # an interpolation or a template directive inside a string


@dataclass
class _Frame:
    kind: str  # `(`, `[`, `{`, `${` (an interpolation or directive) or `"` (a string literal)
    start: int
    key: str | None = None  # an object's: the key of the member being read; None before its `=` and in a `for`


def _scan(text: str) -> Iterator[tuple[int, list[_Frame]]]:
    """Each position of `text` with the frames open there, outermost first."""
    stack: list[_Frame] = []
    i = 0
    while i < len(text):
        yield i, stack
        top = stack[-1] if stack else None
        if top and top.kind == '"':
            if text.startswith(TEMPLATES, i):
                stack.append(_Frame("${", i))
            elif text[i] == '"':
                stack.pop()
            i += 2 if text[i] == "\\" or text.startswith(TEMPLATES, i) else 1
            continue
        if top and top.kind == "{" and top.key is None and not NOT_KEY_START.match(text[i - 1]) and (key := KEY.match(text, i)):
            top.key = key[1].strip('"')
            i = key.end()
            continue
        if text.startswith("${", i):
            stack.append(_Frame("${", i))
            i += 1
        elif text[i] in '"([{':
            stack.append(_Frame(text[i], i))
        elif text[i] in ")]}" and stack:
            stack.pop()
        elif top and top.kind == "{" and text[i] == ",":
            top.key = None
        i += 1


def member_keys(text: str, starts: set[int]) -> dict[int, tuple[str, ...]]:
    """The keys of the object members each position in `starts` is the value of, outermost first:
    `merge({a = {vpc_id = x}}, var.o)` reads `x` at (`a`, `vpc_id`). An object without written keys (a `for`
    expression) adds none."""
    return {i: tuple(f.key for f in stack if f.kind == "{" and f.key is not None) for i, stack in _scan(text) if i in starts}


def literals(text: str) -> list[str]:
    """The string literals of an HCL value, each without its interpolations: `"private-${var.zone}"` -> `private-`,
    `${format("%s-public", var.p)}` -> `%s-public`. Text with no quotes and no interpolation is one literal."""
    if '"' not in text and "${" not in text:
        return [text]
    parts: dict[int, list[str]] = {}
    for i, stack in _scan(text):
        if stack and stack[-1].kind == '"' and text[i] not in '"\\' and not text.startswith(TEMPLATES, i):
            parts.setdefault(stack[-1].start, []).append(text[i])
    return ["".join(p) for p in parts.values()]
