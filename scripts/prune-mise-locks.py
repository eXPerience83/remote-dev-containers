#!/usr/bin/env python3
"""Prune only obsolete, unchanged, tracked mise Python graphs in a trusted checkout."""

from __future__ import annotations

import argparse
import re
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

TOOLS = ("pre-commit", "pytest", "ruff")
FILES = {"pyproject.toml", "uv.lock"}
GRAPH_FILE = re.compile(
    r"\.mise/locks/pypi-(pre-commit|pytest|ruff)/"
    r"([0-9]+\.[0-9]+\.[0-9]+)~[0-9a-f]{8}/(pyproject\.toml|uv\.lock)"
)
VALIDATOR = Path(__file__).resolve().with_name("validate-mise-lock.py")


def git(root: Path, *args: str) -> bytes:
    """Run git in the specified checkout; propagate all unexpected failures."""
    return subprocess.check_output(["git", "-C", str(root), *args])


def validate(root: Path) -> None:
    """Use the existing complete lock validator, not a second pin policy."""
    subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root)], check=True
    )


def plain_dir(path: Path) -> None:
    """Reject symlinks and non-directories without following them."""
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise ValueError(f"not a plain directory: {path}")


def load_toml(path: Path) -> dict:
    """Parse a bounded regular file."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 2_000_000:
        raise ValueError(f"not a bounded regular file: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def prune(root: Path, *, write: bool) -> int:
    """Preflight the entire removal plan before unlinking exact generated files."""
    root = root.resolve()
    if Path(git(root, "rev-parse", "--show-toplevel").decode().rstrip("\n")) != root:
        raise ValueError("root must be the checkout's Git top level")
    for path in (root / ".mise", root / ".mise/locks"):
        plain_dir(path)
    lock = load_toml(root / "mise.lock")
    validate(root)
    active = {lock["tools"][f"pypi:{name}"][0]["uv"]["path"] for name in TOOLS}
    groups: dict[Path, set[str]] = {}
    for raw in git(root, "ls-files", "-z", "--", ".mise/locks/").split(b"\0"):
        if not raw:
            continue
        name = raw.decode()
        if not GRAPH_FILE.fullmatch(name):
            raise ValueError(f"unexpected tracked lock path: {name}")
        path = Path(name)
        groups.setdefault(path.parent, set()).add(path.name)

    plan: list[Path] = []
    for relative, names in sorted(groups.items()):
        if names != FILES:
            raise ValueError(f"incomplete tracked graph: {relative}")
        if relative.as_posix() in active:
            continue
        directory = root / relative
        plain_dir(directory.parent)
        # A repeated invocation before staging deletions is harmless.
        if not directory.exists() and not directory.is_symlink():
            continue
        plain_dir(directory)
        if {p.name for p in directory.iterdir()} != FILES:
            raise ValueError(f"unexpected contents: {relative}")
        for filename in FILES:
            info = (directory / filename).lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError(f"not a plain, singly linked file: {relative / filename}")
        match = GRAPH_FILE.fullmatch((relative / "uv.lock").as_posix())
        assert match is not None
        tool, version = match.group(1, 2)
        project = load_toml(directory / "pyproject.toml").get("project", {})
        graph = load_toml(directory / "uv.lock")
        if (
            project.get("name") != "mise-pypi-tool-environment"
            or project.get("dependencies") != [f"{tool}=={version}"]
            or not any(
                item.get("name") == tool and item.get("version") == version
                for item in graph.get("package", [])
            )
        ):
            raise ValueError(f"unexpected generated graph identity: {relative}")
        # Do not remove locally edited or staged replacement data.
        git(root, "diff", "--quiet", "HEAD", "--", relative.as_posix())
        plan.append(relative)

    for relative in plan:
        print(f"{'Pruning' if write else 'Would prune'} {relative}")
        if write:
            directory = root / relative
            for filename in sorted(FILES):
                (directory / filename).unlink()
            directory.rmdir()
    if write:
        validate(root)
    print(f"Obsolete tracked mise graphs: {len(plan)}")
    return len(plan)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write", action="store_true", help="apply the preflighted plan")
    args = parser.parse_args()
    try:
        prune(args.root, write=args.write)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: mise graph pruning refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
