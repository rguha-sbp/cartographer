"""Patterns for text that must never reach a diagram or a report."""

import re

SECRET_PATTERNS = (
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp_|gho_|github_pat_)\w{16,}"),
    re.compile(r"\bxox[abposr]-[\w-]+"),
    re.compile(r"\beyJ[\w-]+\.eyJ[\w-]+"),
    re.compile(r"(?:password|secret|token|api[_-]?key)\s*[:=]\s*\S{8,}", re.IGNORECASE),
)


def looks_like_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def contains_secret(value: object) -> bool:
    """True when any string anywhere inside a nested dict, list or str looks like a secret."""
    if isinstance(value, str):
        return looks_like_secret(value)
    if isinstance(value, dict):
        return any(contains_secret(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_secret(v) for v in value)
    return False
