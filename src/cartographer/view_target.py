"""Which diagram `cartographer view` opens: a path, a bare name, or the only one in the repo."""

from pathlib import Path

DIAGRAMS = Path("docs/architecture/diagrams")
GENERATED = ".generated.drawio"


class TargetError(Exception):
    pass


def _is_name(arg: str) -> bool:
    return "/" not in arg and "\\" not in arg and not Path(arg).suffix


def resolve(arg: str | None, root: Path = Path(".")) -> Path:
    folder = root / DIAGRAMS
    if arg is not None and not _is_name(arg):
        return Path(arg)
    found = sorted(p for p in folder.glob("*.drawio") if not p.name.endswith(GENERATED))
    if arg is not None:
        if (folder / f"{arg}.drawio") not in found:
            raise TargetError(f"no diagram named {arg} in {DIAGRAMS}")
        return folder / f"{arg}.drawio"
    if not found:
        raise TargetError(f"no .drawio files in {DIAGRAMS}: pass a path to one")
    if len(found) > 1:
        names = "\n".join(p.stem for p in found)
        raise TargetError(f"several diagrams in {DIAGRAMS}, name one:\n{names}")
    return found[0]
