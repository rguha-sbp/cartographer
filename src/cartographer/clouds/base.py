"""The Cloud object: everything that differs between clouds hangs off an instance of it."""

import json
from pathlib import Path
from typing import Any


def load_json(package_file: str, name: str) -> Any:
    return json.loads(Path(package_file).with_name(name).read_text(encoding="utf-8"))


class Cloud:
    def __init__(self, name: str, label: str, providers: tuple[str, ...], icons: dict[str, dict]) -> None:
        self.name = name
        self.label = label
        self.providers = providers
        self.icons = icons

    def icon_style(self, name: str) -> str:
        return (f"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor={self.icons[name]['fill']};"
                f"strokeColor=#ffffff;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
                f"fontSize=12;fontStyle=0;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.resourceIcon;"
                f"resIcon=mxgraph.aws4.{name};")
