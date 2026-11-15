"""Package supplied Core binaries against the pinned Observatory source descriptor."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "lib" / "codex"
sys.path.insert(0, str(REPO_ROOT / "src"))
from observatory.release import RELEASE


PACKAGE_FILES = {
    "codex": "bin/codex",
    "codex-code-mode-host": "bin/codex-code-mode-host",
    "codex-exec-server": "bin/codex-exec-server",
    "bwrap": "codex-resources/bwrap",
    "rg": "codex-path/rg",
}


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(*arguments: str, deterministic: bool = False) -> bytes:
    environment = None
    if deterministic:
        environment = {
            "PATH": os.defpath,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
    return subprocess.run(
        ["git", "-C", str(CORE_ROOT), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    ).stdout


def source_identity() -> tuple[str, str]:
    """Require all nonignored source files and compare the whole Rust diff to the pin."""
    core = RELEASE["core"]
    expected = core.get("observatory_patch_sha256")
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ValueError(
            "release descriptor has no valid core.observatory_patch_sha256"
        )
    base = core["upstream_commit"]
    git("cat-file", "-e", f"{base}^{{commit}}")
    git("merge-base", "--is-ancestor", base, "HEAD")
    untracked = git(
        "ls-files", "--others", "--exclude-standard", "-z", "--", "codex-rs"
    )
    if untracked:
        raise ValueError(
            "untracked files under lib/codex/codex-rs would be omitted from the source patch; stage them first"
        )
    head = git("rev-parse", "HEAD").decode("ascii").strip()
    patch = git(
        "-c",
        "core.quotePath=true",
        "-c",
        f"core.attributesFile={os.devnull}",
        "-c",
        f"diff.orderFile={os.devnull}",
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
        "--no-renames",
        "--no-relative",
        "--no-indent-heuristic",
        "--diff-algorithm=myers",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--unified=3",
        "--inter-hunk-context=0",
        base,
        "--",
        "codex-rs",
        deterministic=True,
    )
    actual = hashlib.sha256(patch).hexdigest()
    if actual != expected:
        raise ValueError(
            f"Rust source patch SHA-256 {actual} does not match the descriptor"
        )
    return head, actual


def executable(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"{label} is not an executable file: {path}")
    return path


def private_environment(home: Path) -> dict[str, str]:
    """Construct a private, minimal environment for tools that touch user state."""
    directories = {
        "CODEX_HOME": home / ".codex",
        "XDG_CONFIG_HOME": home / "config",
        "XDG_DATA_HOME": home / "data",
        "XDG_CACHE_HOME": home / "cache",
        "XDG_STATE_HOME": home / "state",
        "XDG_RUNTIME_DIR": home / "runtime",
    }
    for path in directories.values():
        path.mkdir(mode=0o700)
    environment = {key: str(path) for key, path in directories.items()}
    environment.update(
        {
            "PATH": os.defpath,
            "HOME": str(home),
            "TMPDIR": str(home),
            "XDG_CONFIG_DIRS": environment["XDG_CONFIG_HOME"],
            "XDG_DATA_DIRS": environment["XDG_DATA_HOME"],
        }
    )
    return environment


def build(args: argparse.Namespace) -> tuple[Path, Path]:
    head, patch_sha = source_identity()
    descriptor = RELEASE
    core = descriptor["core"]
    artifact_name = descriptor["artifacts"]["core"]["name"]
    if Path(artifact_name).name != artifact_name or not artifact_name.endswith(
        ".tar.gz"
    ):
        raise ValueError(
            "Core archive name in release descriptor is unsafe or unsupported"
        )
    output_dir = args.output_dir.expanduser().resolve(strict=True)
    if not output_dir.is_dir():
        raise ValueError(f"output directory is not a directory: {output_dir}")
    if output_dir.is_relative_to(CORE_ROOT.resolve()):
        raise ValueError("output directory must be outside lib/codex")
    archive_output = output_dir / artifact_name
    report_output = output_dir / f"{artifact_name}.build.json"
    for output in (archive_output, report_output):
        if output.exists() or output.is_symlink():
            raise ValueError(f"refusing to replace existing output: {output}")

    bin_dir = args.bin_dir.expanduser().resolve(strict=True)
    inputs = {
        name: executable(bin_dir / name, name) for name in PACKAGE_FILES if name != "rg"
    }
    rg = args.rg or shutil.which("rg")
    if not rg:
        raise ValueError("ripgrep was not found; specify --rg")
    inputs["rg"] = executable(Path(rg), "ripgrep")
    with tempfile.TemporaryDirectory(
        prefix="observatory-core-version-"
    ) as temporary_home:
        result = subprocess.run(
            [str(inputs["codex"]), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env=private_environment(Path(temporary_home)),
        )
    expected_version = f"codex-cli {core['version']}"
    if result.stdout.strip() != expected_version:
        raise ValueError(
            f"Core binary reported {result.stdout.strip()!r}; expected {expected_version!r}"
        )

    with tempfile.TemporaryDirectory(
        prefix=".observatory-core-", dir=output_dir
    ) as temporary:
        stage = Path(temporary)
        package_dir = stage / "package"
        archive = stage / artifact_name
        builder_home = stage / "home"
        builder_home.mkdir(mode=0o700)
        env = private_environment(builder_home)
        env["CODEX_REPO_ROOT"] = str(CORE_ROOT)
        command = [
            sys.executable,
            str(CORE_ROOT / "scripts/build_codex_package.py"),
            "--target",
            core["target"],
            "--variant",
            "codex",
            "--package-version",
            core["version"],
            "--cargo-profile",
            args.profile,
            "--strip",
            "none",
            "--package-dir",
            str(package_dir),
            "--archive-output",
            str(archive),
            "--entrypoint-bin",
            str(inputs["codex"]),
            "--code-mode-host-bin",
            str(inputs["codex-code-mode-host"]),
            "--exec-server-bin",
            str(inputs["codex-exec-server"]),
            "--bwrap-bin",
            str(inputs["bwrap"]),
            "--rg-bin",
            str(inputs["rg"]),
        ]
        subprocess.run(command, check=True, cwd=CORE_ROOT, env=env)
        if source_identity() != (head, patch_sha):
            raise ValueError("Rust source changed during package assembly")
        report = {
            "schema_version": 1,
            "observatory_version": descriptor["observatory"]["version"],
            "core": {**core, "source_head_commit": head},
            "build": {
                "profile": args.profile,
                "optimization": args.optimization,
                "profile_evidence": "caller-supplied; prebuilt binary profile not independently verified",
                "source_linkage": "prebuilt binaries supplied by caller; linkage to source not independently verified",
            },
            "files_sha256": {
                relative: sha256_file(package_dir / relative)
                for relative in ("codex-package.json", *PACKAGE_FILES.values())
            },
            "archive": {"name": artifact_name, "sha256": sha256_file(archive)},
        }
        report_path = stage / "build.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if source_identity() != (head, patch_sha):
            raise ValueError("Rust source changed before archive promotion")
        created_report = False
        try:
            os.link(report_path, report_output)
            created_report = True
            os.link(archive, archive_output)
        except OSError:
            if created_report:
                report_output.unlink()
            raise
    return archive_output, report_output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bin-dir",
        required=True,
        type=Path,
        help="directory containing the four prebuilt Core executables",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="existing directory for the archive and build report",
    )
    parser.add_argument(
        "--profile",
        required=True,
        help="Cargo profile used to build the supplied binaries",
    )
    parser.add_argument(
        "--optimization",
        required=True,
        choices=("unoptimized", "optimized"),
        help="optimization setting used to build the supplied binaries",
    )
    parser.add_argument(
        "--rg", type=Path, help="ripgrep executable (default: rg on PATH)"
    )
    args = parser.parse_args()
    try:
        archive, report = build(args)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"build-observatory-core: {exc}", file=sys.stderr)
        return 1
    print(f"Core archive: {archive}")
    print(f"Build report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
