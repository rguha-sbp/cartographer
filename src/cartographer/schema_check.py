"""Check a JSON value against a JSON Schema, for the keywords cartographer's schemas use: type, enum, required,
properties, additionalProperties false, items, minItems, minLength, maxLength, minimum, pattern, oneOf and a $ref
into $defs. Each problem names its JSON path, for example `relationships[3]: missing 'dashed'`."""

import re
from typing import Any

Schema = dict[str, Any]

TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}


def check(value: object, schema: Schema) -> list[str]:
    """Every problem with value, in document order; empty means it fits the schema."""
    return _problems(value, schema, schema.get("$defs", {}), "")


def _is(value: object, kind: str) -> bool:
    # JSON true is not the number 1, though Python's bool is an int.
    return isinstance(value, TYPES[kind]) and (kind == "boolean" or not isinstance(value, bool))


def _problems(value: object, schema: Schema, defs: Schema, path: str) -> list[str]:
    at = path or "model"
    if "$ref" in schema:
        schema = defs[schema["$ref"].removeprefix("#/$defs/")]
    if "oneOf" in schema:
        fits = sum(not _problems(value, arm, defs, path) for arm in schema["oneOf"])
        return [] if fits == 1 else [f"{at}: matches {fits} of its {len(schema['oneOf'])} forms, needs exactly one"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{at}: {value!r} is not one of {', '.join(map(repr, schema['enum']))}"]
    if "type" in schema and not _is(value, schema["type"]):
        kind = schema["type"]
        return [f"{at}: must be {'an' if kind[0] in 'aeiou' else 'a'} {kind}"]
    match value:
        case dict():
            return _object(value, schema, defs, path)
        case list():
            return _array(value, schema, defs, path)
        case str():
            return _string(value, schema, at)
        case int() | float() if "minimum" in schema and value < schema["minimum"]:
            return [f"{at}: must be at least {schema['minimum']}"]
    return []


def _object(value: dict, schema: Schema, defs: Schema, path: str) -> list[str]:
    at, properties = path or "model", schema.get("properties", {})
    out = [f"{at}: missing {key!r}" for key in schema.get("required", []) if key not in value]
    if schema.get("additionalProperties") is False:
        out += [f"{at}: unknown key {key!r}" for key in value if key not in properties]
    return out + [p for key, v in value.items() if key in properties
                  for p in _problems(v, properties[key], defs, f"{path}.{key}" if path else key)]


def _array(value: list, schema: Schema, defs: Schema, path: str) -> list[str]:
    least = schema.get("minItems", 0)
    out = [f"{path}: needs at least {least} item{'s' * (least > 1)}"] if len(value) < least else []
    return out + [p for i, v in enumerate(value) for p in _problems(v, schema.get("items", {}), defs, f"{path}[{i}]")]


def _string(value: str, schema: Schema, at: str) -> list[str]:
    out = []
    if len(value) < schema.get("minLength", 0):
        out.append(f"{at}: must be at least {schema['minLength']} characters")
    if len(value) > schema.get("maxLength", len(value)):
        out.append(f"{at}: must be at most {schema['maxLength']} characters")
    if "pattern" in schema and not re.search(schema["pattern"], value):
        out.append(f"{at}: {value!r} does not match {schema['pattern']}")
    return out
