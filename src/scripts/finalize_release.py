"""Pin previously built release archives before building the Python distribution."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


DESCRIPTOR = (
    Path(__file__).resolve().parents[2] / "release.json"
)


def finalize(core: Path, desktop: Path, descriptor: Path = DESCRIPTOR) -> dict:
    """Atomically add archive hashes, refusing to replace existing different pins."""
    document = json.loads(descriptor.read_text(encoding="utf-8"))
    for kind, archive in (("core", core), ("desktop", desktop)):
        artifact = document["artifacts"][kind]
        if archive.name != artifact["name"] or not archive.is_file():
            raise ValueError(
                f"Expected {kind} archive named {artifact['name']}: {archive}"
            )
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if artifact["sha256"] not in (None, digest):
            raise ValueError(
                f"The {kind} archive differs from the existing descriptor pin."
            )
        artifact["sha256"] = digest
    descriptor = descriptor.resolve()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=descriptor.parent,
            prefix=".release-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, indent=2)
            stream.write("\n")
        os.chmod(temporary, descriptor.stat().st_mode & 0o777)
        os.replace(temporary, descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("core", type=Path)
    parser.add_argument("desktop", type=Path)
    args = parser.parse_args()
    try:
        document = finalize(args.core, args.desktop)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    for kind in ("core", "desktop"):
        artifact = document["artifacts"][kind]
        print(f"{artifact['sha256']}  {artifact['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
