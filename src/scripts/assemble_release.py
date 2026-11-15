#!/usr/bin/env python3
"""Assemble a self-contained Observatory release from pinned Core/Desktop archives."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[2]
DESCRIPTOR = REPO_ROOT / "release.json"
CORE_FILES = (
    "codex-package.json",
    "bin/codex",
    "bin/codex-code-mode-host",
    "bin/codex-exec-server",
    "codex-resources/bwrap",
    "codex-path/rg",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_parts(name: str) -> tuple[str, ...]:
    path = PurePosixPath(name)
    raw_parts = name.split("/")
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in raw_parts
    ):
        raise ValueError(f"unsafe archive path: {name!r}")
    return path.parts


def _extract_archive(archive_path: Path, destination: Path, *, strip_first: bool) -> None:
    seen: set[tuple[str, ...]] = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError(f"archive is empty: {archive_path}")
        first_component: str | None = None
        for member in members:
            parts = _safe_parts(member.name)
            if parts in seen:
                raise ValueError(f"archive contains a duplicate path: {member.name}")
            seen.add(parts)
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"archive contains a non-regular entry: {member.name}")
            if strip_first:
                if first_component is None:
                    first_component = parts[0]
                if parts[0] != first_component:
                    raise ValueError("Desktop archive has more than one top-level path")
                if len(parts) == 1:
                    if not member.isdir():
                        raise ValueError("Desktop archive root is not a directory")
                    continue
                parts = parts[1:]
            target = destination.joinpath(*parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"archive path escapes its destination: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"archive file cannot be read: {member.name}")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(member.mode & 0o777)
        if strip_first and first_component != "codex-observatory-desktop":
            raise ValueError(
                "Desktop archive must have a codex-observatory-desktop top-level directory"
            )


def _verify_core(package_root: Path, release: dict) -> None:
    expected = {
        "layoutVersion": 1,
        "version": release["core"]["version"],
        "target": release["core"]["target"],
        "variant": "codex",
        "entrypoint": "bin/codex",
        "execServer": "bin/codex-exec-server",
        "resourcesDir": "codex-resources",
        "pathDir": "codex-path",
    }
    metadata_path = package_root / release["runtime"]["core"] / "codex-package.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Core package metadata is missing or unreadable: {metadata_path}") from exc
    if metadata != expected:
        raise ValueError("Core package metadata does not match release.json")
    for relative in CORE_FILES[1:]:
        path = package_root / release["runtime"]["core"] / relative
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(f"Core package file is missing or not executable: {path}")


def _copy_observatory_sources(package_root: Path) -> None:
    for name in ("README.md", "LICENSE", "NOTICE", "observatory"):
        shutil.copy2(REPO_ROOT / name, package_root / name)
    (package_root / "src").mkdir()
    shutil.copy2(REPO_ROOT / "src" / "launch.py", package_root / "src" / "launch.py")
    shutil.copytree(
        REPO_ROOT / "src" / "observatory",
        package_root / "src" / "observatory",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(DESCRIPTOR, package_root / "release.json")
    shutil.copytree(REPO_ROOT / "docs", package_root / "docs")


def _write_archive(directory: Path, archive_path: Path) -> None:
    with archive_path.open("xb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, mtime=0
    ) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(directory.rglob("*")):
                relative = path.relative_to(directory.parent).as_posix()
                info = archive.gettarinfo(str(path), arcname=relative)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                if info.isfile():
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
                else:
                    archive.addfile(info)


def assemble(core: Path, desktop: Path, output_dir: Path) -> tuple[Path, Path, Path]:
    release = json.loads(DESCRIPTOR.read_text(encoding="utf-8"))
    for kind, archive in (("core", core), ("desktop", desktop)):
        expected = release["artifacts"][kind]
        digest = expected.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"release.json has no pinned {kind} archive SHA-256")
        if archive.name != expected["name"]:
            raise ValueError(f"expected {kind} archive named {expected['name']}: {archive}")
        if not archive.is_file() or sha256(archive) != digest:
            raise ValueError(f"{kind} archive does not match release.json SHA-256")

    output_dir.mkdir(parents=True, exist_ok=True)
    version = release["observatory"]["version"]
    name = f"codex-observatory-{version}-linux-x86_64"
    package_root = output_dir / name
    archive_path = output_dir / f"{name}.tar.gz"
    sidecar_path = output_dir / f"{name}.sha256"
    for path in (package_root, archive_path, sidecar_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"refusing to replace existing output: {path}")

    with tempfile.TemporaryDirectory(prefix=".observatory-release-", dir=output_dir) as temporary:
        staging = Path(temporary) / name
        staging.mkdir()
        core_root = staging / release["runtime"]["core"]
        desktop_root = staging / release["runtime"]["desktop"]
        core_root.mkdir(parents=True)
        desktop_root.mkdir(parents=True)
        _extract_archive(core, core_root, strip_first=False)
        _extract_archive(desktop, desktop_root, strip_first=True)
        _verify_core(staging, release)
        _copy_observatory_sources(staging)
        staged_archive = Path(temporary) / f"{name}.tar.gz"
        _write_archive(staging, staged_archive)
        archive_hash = sha256(staged_archive)
        staged_sidecar = Path(temporary) / f"{name}.sha256"
        staged_sidecar.write_text(f"{archive_hash}  {archive_path.name}\n", encoding="ascii")
        os.rename(staging, package_root)
        try:
            os.link(staged_archive, archive_path)
            os.link(staged_sidecar, sidecar_path)
        except OSError:
            archive_path.unlink(missing_ok=True)
            sidecar_path.unlink(missing_ok=True)
            shutil.rmtree(package_root)
            raise
    return package_root, archive_path, sidecar_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", required=True, type=Path, help="pinned Core archive")
    parser.add_argument("--desktop", required=True, type=Path, help="pinned Desktop archive")
    parser.add_argument("--output-dir", required=True, type=Path, help="existing or new output directory")
    args = parser.parse_args()
    try:
        package_root, archive_path, sidecar_path = assemble(args.core, args.desktop, args.output_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, tarfile.TarError) as exc:
        parser.error(str(exc))
    print(f"Release directory: {package_root}")
    print(f"Release archive: {archive_path}")
    print(f"SHA-256 sidecar: {sidecar_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
