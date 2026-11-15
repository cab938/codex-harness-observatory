#!/usr/bin/env python3
"""Reproduce the Observatory's pinned Linux V8 binding in a private workspace."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=REPO_ROOT / "lib" / "codex"
    )
    parser.add_argument("--descriptor", type=Path)
    parser.add_argument(
        "--bazel", type=Path, required=True, help="Pinned Bazel executable"
    )
    parser.add_argument(
        "--archive", type=Path, required=True, help="Pinned upstream V8 archive"
    )
    parser.add_argument(
        "--work-dir", type=Path, required=True, help="New private workspace"
    )
    parser.add_argument(
        "--cache-dir", type=Path, help="Private Bazel cache; defaults to work-dir/cache"
    )
    parser.add_argument("--output", type=Path, required=True, help="New binding output")
    args = parser.parse_args()

    source = args.source.resolve(strict=True)
    descriptor = args.descriptor or REPO_ROOT / "release.json"
    release = json.loads(descriptor.read_text())
    core, v8 = release["core"], release["core"]["v8"]
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        raise ValueError("V8 binding generation requires Linux x86_64")
    if (
        core["target"] != "x86_64-unknown-linux-gnu"
        or v8["profile"] != "sandbox_release"
    ):
        raise ValueError(
            "descriptor does not describe the supported V8 target and profile"
        )
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", v8["crate_version"]):
        raise ValueError("invalid V8 crate version")
    archive_path = args.archive.resolve(strict=True)
    if sha256(archive_path) != v8["archive_sha256"]:
        raise ValueError("V8 archive does not match the descriptor SHA-256")
    bazel = args.bazel.resolve(strict=True)
    if sha256(bazel) != v8["bazel_sha256"]:
        raise ValueError("Bazel executable does not match the descriptor SHA-256")
    if (
        subprocess.check_output([bazel, "--version"], text=True).strip()
        != "bazel " + v8["bazel_version"]
    ):
        raise ValueError("Bazel version does not match the descriptor")

    commit = core["upstream_commit"]
    actual_commit = subprocess.check_output(
        ["git", "-C", source, "rev-parse", "--verify", f"{commit}^{{commit}}"],
        text=True,
    ).strip()
    if actual_commit != commit:
        raise ValueError("upstream commit is unavailable")
    output = args.output.absolute()
    report = Path(str(output) + ".provenance.json")
    if output.exists() or report.exists():
        raise FileExistsError("binding output or provenance report already exists")
    work = args.work_dir.absolute()
    work.mkdir(parents=True, exist_ok=False)
    workspace = work / "source"
    workspace.mkdir()
    cache = args.cache_dir.absolute() if args.cache_dir else work / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    private_home, tmp = work / "home", work / "tmp"
    private_home.mkdir()
    tmp.mkdir()

    # Archive the immutable upstream commit, excluding all uncommitted source changes.
    archive = subprocess.Popen(
        ["git", "-C", source, "archive", "--format=tar", commit], stdout=subprocess.PIPE
    )
    assert archive.stdout is not None
    extract = subprocess.run(
        ["tar", "-xf", "-", "-C", workspace], stdin=archive.stdout, check=False
    )
    archive.stdout.close()
    if archive.wait() != 0 or extract.returncode != 0:
        raise RuntimeError("could not export the pinned source commit")

    binding_rule = "binding_generated_" + v8["crate_version"].replace(".", "_")
    build_file = workspace / "third_party/v8/BUILD.bazel"
    original = build_file.read_text()
    alias = "observatory_binding_sandbox_release_only"
    if f'name = "{alias}"' in original:
        raise ValueError("diagnostic binding alias already exists upstream")
    with build_file.open("a") as f:
        f.write(
            f'\nv8_artifact_files(\n    name = "{alias}",\n'
            f'    srcs = [":{binding_rule}"],\n    profile = "{v8["profile"]}",\n'
            '    v8_cpu = "x64",\n)\n'
        )

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(private_home),
        "XDG_CACHE_HOME": str(private_home / ".cache"),
        "TMPDIR": str(tmp),
        "STABLE_GIT_COMMIT": commit,
    }
    command = [
        str(bazel),
        "--nosystem_rc",
        "--nohome_rc",
        "--host_jvm_args=-Xmx2048m",
        f"--output_user_root={cache / 'output'}",
        "--noexperimental_remote_repo_contents_cache",
        "build",
        "-c",
        "opt",
        f"--platforms={v8['bazel_platform']}",
        "--config=ci-v8",
        "--lockfile_mode=error",
        "--jobs=1",
        "--local_resources=cpu=1",
        "--local_resources=memory=4096",
        f"--repository_cache={cache / 'repository'}",
        f"--repo_contents_cache={cache / 'contents'}",
        f"--symlink_prefix={work / 'bazel-link-'}",
        f"//third_party/v8:{alias}",
    ]
    subprocess.run(command, cwd=workspace, env=env, check=True)
    matches = list(
        (work / "bazel-link-out").glob(f"*/bin/third_party/v8/{binding_rule}.rs")
    )
    if len(matches) != 1:
        raise RuntimeError(f"expected one generated binding, found {len(matches)}")
    actual_hash = sha256(matches[0])
    expected_binding_hash = v8.get("binding_sha256")
    if expected_binding_hash is not None and actual_hash != expected_binding_hash:
        raise ValueError(f"generated binding SHA-256 mismatch: {actual_hash}")
    with matches[0].open("rb") as src, output.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    with report.open("x") as f:
        json.dump(
            {
                "upstream_commit": commit,
                "target": core["target"],
                "v8": v8,
                "generated_binding_sha256": actual_hash,
                "binding_pin_status": (
                    "matched" if expected_binding_hash is not None else "computed_unfinalized"
                ),
                "producer": {
                    "target": f"//third_party/v8:{binding_rule}",
                    "wrapper": "temporary v8_artifact_files alias",
                    "profile": v8["profile"],
                    "v8_cpu": "x64",
                },
                "verification": (
                    "Archive and generated binding digests verified."
                    if expected_binding_hash is not None
                    else "Archive digest verified; generated binding digest recorded for pinning."
                ) + " Linkage and ABI are not tested by this helper.",
            },
            f,
            indent=2,
        )
        f.write("\n")
    print(f"Generated binding: {output}")
    print(f"Build provenance: {report}")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"build-observatory-v8-binding: {exc}", file=sys.stderr)
        raise SystemExit(1)
