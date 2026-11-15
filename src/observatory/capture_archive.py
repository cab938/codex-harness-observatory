"""Export and open portable, byte-preserving Observatory capture bundles."""

import contextlib
import os
import shutil
import stat
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Iterator

from observatory.trace_viewer import TraceInputError, manifest_metadata, validated_events


_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _parts(name: str, *, directory: bool = False) -> tuple[str, ...]:
    if directory and name.endswith("/"):
        name = name[:-1]
    parts = name.split("/")
    if not name or any(
        not part
        or part in {".", ".."}
        or part[-1] in {" ", "."}
        or any(ord(char) < 32 or char in '<>:"\\|?*' for char in part)
        or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED
        for part in parts
    ):
        raise TraceInputError(f"unsafe archive path: {name!r}")
    return tuple(parts)


def _check_names(entries: list[tuple[str, bool]]) -> None:
    nodes: dict[tuple[str, ...], tuple[tuple[str, ...], bool]] = {}
    explicit: set[tuple[str, ...]] = set()
    for name, directory in entries:
        parts = _parts(name, directory=directory)
        for index in range(1, len(parts) + 1):
            prefix = parts[:index]
            key = tuple(
                unicodedata.normalize("NFC", part).casefold() for part in prefix
            )
            is_directory = index < len(parts) or directory
            previous = nodes.get(key)
            if previous is not None and (
                previous[0] != prefix or previous[1] != is_directory
            ):
                raise TraceInputError(f"colliding archive path: {name!r}")
            nodes[key] = (prefix, is_directory)
            if index == len(parts):
                if key in explicit:
                    raise TraceInputError(f"duplicate archive path: {name!r}")
                explicit.add(key)
    for required in ("manifest.json", "trace.jsonl"):
        if nodes.get((required,)) != ((required,), False):
            raise TraceInputError(f"archive must contain {required} at its root")
    for key, (parts, is_directory) in nodes.items():
        if len(parts) > 1 and not is_directory and parts[-1] == "trace.jsonl":
            manifest = (*key[:-1], "manifest.json")
            if manifest in nodes:
                raise TraceInputError("archive contains more than one bundle")


def _snapshot(root: Path) -> dict[str, os.stat_result]:
    files: dict[str, os.stat_result] = {}
    names: list[tuple[str, bool]] = []

    def visit(directory: Path) -> None:
        with os.scandir(directory) as children:
            for child in children:
                path = Path(child.path)
                relative = path.relative_to(root).as_posix()
                # Windows DirEntry.stat omits file identity; lstat agrees with fstat.
                info = path.lstat()
                if getattr(info, "st_file_attributes", 0) & getattr(
                    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
                ):
                    raise TraceInputError(
                        f"bundle contains a non-regular file: {relative}"
                    )
                if stat.S_ISDIR(info.st_mode):
                    names.append((relative, True))
                    visit(path)
                elif stat.S_ISREG(info.st_mode):
                    names.append((relative, False))
                    files[relative] = info
                else:
                    raise TraceInputError(
                        f"bundle contains a non-regular file: {relative}"
                    )

    visit(root)
    _check_names(names)
    return files


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def export_bundle(bundle: Path, output: Path) -> None:
    """Write one stable bundle to a new ZIP, retaining every regular file's bytes."""
    root = Path(bundle).resolve(strict=True)
    target = Path(output).absolute()
    if not root.is_dir():
        raise TraceInputError("export source must be a bundle directory")
    try:
        target.resolve().relative_to(root)
    except ValueError:
        pass
    else:
        raise TraceInputError("archive output must be outside the bundle")
    if target.exists():
        raise TraceInputError(f"archive output already exists: {target}")
    before = _snapshot(root)
    manifest_metadata(root / "trace.jsonl", recorded=True)
    # Resolve both inline and externalized event payload references before
    # copying. The later snapshot check detects changes during this validation.
    for _ in validated_events(root / "trace.jsonl"):
        pass
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".observatory-", suffix=".zip", dir=target.parent, delete=False
        ) as temp:
            temporary = temp.name
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            for name, original in sorted(before.items()):
                flags = (
                    os.O_RDONLY
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                descriptor = os.open(root / name, flags)
                with os.fdopen(descriptor, "rb") as source:
                    if not _same_file(original, os.fstat(source.fileno())):
                        raise TraceInputError(f"bundle changed during export: {name}")
                    with archive.open(name, "w", force_zip64=True) as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                    if not _same_file(original, os.fstat(source.fileno())):
                        raise TraceInputError(f"bundle changed during export: {name}")
        after = _snapshot(root)
        if before.keys() != after.keys() or any(
            not _same_file(before[name], after[name]) for name in before
        ):
            raise TraceInputError("bundle changed during export")
        # Linking a completed file within the output directory is atomic and
        # does not overwrite an existing archive, including in a race.
        os.link(temporary, target)
    except (OSError, zipfile.BadZipFile) as error:
        raise TraceInputError(f"cannot export bundle: {error}") from error
    finally:
        if temporary is not None:
            os.unlink(temporary)


@contextlib.contextmanager
def open_capture(path: Path) -> Iterator[Path]:
    """Yield a bundle directory, retaining a ZIP's private extraction until exit."""
    source = Path(path)
    if source.is_dir() or (source.is_file() and source.suffix.lower() == ".jsonl"):
        yield source
        return
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as error:
        raise TraceInputError(f"cannot open capture archive: {error}") from error
    with (
        archive,
        tempfile.TemporaryDirectory(prefix="observatory-capture-") as temporary,
    ):
        entries = archive.infolist()
        _check_names([(entry.filename, entry.is_dir()) for entry in entries])
        for entry in entries:
            if entry.orig_filename != entry.filename:
                raise TraceInputError(f"unsafe archive path: {entry.orig_filename!r}")
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if (
                kind not in (0, stat.S_IFREG, stat.S_IFDIR)
                or (entry.is_dir() and kind == stat.S_IFREG)
                or (not entry.is_dir() and kind == stat.S_IFDIR)
            ):
                raise TraceInputError(
                    f"archive contains a non-regular file: {entry.filename}"
                )
            if entry.flag_bits & 1:
                raise TraceInputError(
                    f"archive contains an encrypted file: {entry.filename}"
                )
        root = Path(temporary)
        try:
            for entry in entries:
                parts = _parts(entry.filename, directory=entry.is_dir())
                destination = root.joinpath(*parts)
                if entry.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        archive.open(entry) as source_file,
                        destination.open("xb") as target_file,
                    ):
                        shutil.copyfileobj(source_file, target_file, length=1024 * 1024)
        except (
            OSError,
            RuntimeError,
            NotImplementedError,
            zipfile.BadZipFile,
        ) as error:
            raise TraceInputError(f"cannot extract capture archive: {error}") from error
        yield root
