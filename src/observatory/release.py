"""Read the one release descriptor supplied with the assembled distribution."""

import json
from pathlib import Path
import sys


def descriptor_path() -> Path:
    source = Path(__file__).resolve().parents[2] / "release.json"
    if source.is_file():
        return source
    assembled = Path(sys.prefix).parent / "release.json"
    if assembled.is_file():
        return assembled
    return Path(sys.prefix) / "share" / "codex-harness-observatory" / "release.json"


RELEASE = json.loads(descriptor_path().read_text(encoding="utf-8"))
VERSION = RELEASE["observatory"]["version"]

