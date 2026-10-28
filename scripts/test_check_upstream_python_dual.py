#!/usr/bin/env python3
"""Regression guard for the bounded, write-capable Python/upstream update step."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

STEP = "      - name: Check stable upstream releases and review metadata\n"
RUN = "        run: |\n"
GUARD = (
    "if ! grep -Eq '^python = "
    '\\["3[.]14[.][0-9]+", "3[.]15[.][0-9]+"\\]$'
    "' mise.toml; then"
)
REQUIRED_ONCE = (
    GUARD,
    'sed -i "s|^python = .*|python = [\\"${latest_python}\\", \\"${latest_python_315}\\"]|" mise.toml',
    'replace_env PYTHON_VERSION "$latest_python"',
    'replace_env PYTHON_315_VERSION "$latest_python_315"',
    'replace_mise_tool node "$latest_node"',
    'replace_mise_tool uv "$latest_uv"',
    'git commit -m "chore: update upstream versions and review evidence"',
    'git push --force-with-lease -u origin "$branch"',
    'gh pr create \\',
    'gh pr edit "$existing_pr" \\',
)


def shell_step(text: str) -> str:
    """Extract the intended updater shell step, never an unrelated workflow step."""
    if text.count(STEP) != 1:
        raise AssertionError("upstream workflow needs exactly one update step")
    suffix = text.split(STEP, 1)[1]
    if RUN not in suffix:
        raise AssertionError("upstream update step must contain a script block")
    body = suffix.split(RUN, 1)[1]
    lines = []
    for line in body.splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line[10:] if line.startswith("          ") else "")
    if len(lines) < 250:
        raise AssertionError("truncated updater shell block")
    return "\n".join(lines) + "\n"


def validate_step(body: str) -> None:
    """Require syntactically valid Bash and one coherent update/PR flow."""
    result = subprocess.run(
        ["bash", "-n"], input=body, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise AssertionError(f"updater Bash syntax invalid: {result.stderr.strip()}")
    for fragment in REQUIRED_ONCE:
        if body.count(fragment) != 1:
            raise AssertionError(f"updater must contain exactly one {fragment!r}")
    if body.index(GUARD) > body.index('replace_mise_tool node "$latest_node"'):
        raise AssertionError("dual-Python guard must precede other mise updates")
    if body.index('git commit -m "chore: update upstream versions and review evidence"') > body.index('gh pr create \\'):
        raise AssertionError("updater must commit changes before proposing a PR")



def simulate_version_updates(
    body: str, root: Path, *, fixture_content: str | None = None
) -> None:
    """Exercise the real updater against either reviewed or already-updated pins."""
    start_marker = "# Python deliberately carries two ordered exact versions in one mise tool."
    stop_marker = "python3 scripts/update-context7-review.py"
    if body.count(start_marker) != 1 or body.count(stop_marker) != 1:
        raise AssertionError("Python updater fragment is missing or duplicated")
    start = body.index(start_marker)
    end = body.index(stop_marker, start)
    patch = body[start:end]
    original = (
        fixture_content if fixture_content is not None
        else (root / "mise.toml").read_text(encoding="utf-8")
    )
    reviewed = tomllib.loads(original)
    old_tools = reviewed["tools"]
    old_python = old_tools["python"]
    if not isinstance(old_python, list) or len(old_python) != 2:
        raise AssertionError("fixture requires both Python versions")
    new_python = [
        f"3.14.{int(old_python[0].split('.')[2]) + 1}",
        f"3.15.{int(old_python[1].split('.')[2]) + 1}",
    ]
    replacements = {
        "latest_python": new_python[0],
        "latest_python_315": new_python[1],
        "latest_node": "24.999.0",
        "latest_uv": "0.999.0",
    }
    # Derive the simulated upstream results from the *input fixture*. The real
    # workflow calls this test both before and after changing version pins:
    # hard-coded old values would silently downgrade updated tools in the test.
    simulated_versions = {
        "RUFF": old_tools["pypi:ruff"]["version"],
        "PYTEST": old_tools["pypi:pytest"]["version"],
        "PRE_COMMIT": old_tools["pypi:pre-commit"]["version"],
        "YQ": old_tools["yq"],
        "SHFMT": old_tools["shfmt"],
        "ACTIONLINT": old_tools["actionlint"],
    }
    for name, version in simulated_versions.items():
        if not isinstance(version, str) or not version.replace(".", "").isdigit():
            raise AssertionError(f"invalid {name} version in test fixture: {version!r}")
    version_assignments = " ".join(
        f"[{name}]={version}" for name, version in simulated_versions.items()
    )
    setup = [
        "set -euo pipefail",
        'replace_env() { :; }',
        f"declare -A validation_versions=({version_assignments})",
        'replace_mise_tool() {',
        '  local name="$1" value="$2"',
        '  grep -q "^${name} = \\"" mise.toml',
        '  sed -i "s|^${name} = .*|${name} = \\"${value}\\"|" mise.toml',
        '}',
    ]
    for name, value in replacements.items():
        setup.append(f'{name}="{value}"')
    script = "\n".join(setup) + "\n" + patch

    with tempfile.TemporaryDirectory(prefix="upstream-python-flow-") as tmp:
        config = Path(tmp) / "mise.toml"
        config.write_text(original, encoding="utf-8")

        def execute() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["bash", "-c", script],
                cwd=tmp, text=True, capture_output=True, check=False,
                timeout=15,
            )

        result = execute()
        if result.returncode:
            raise AssertionError(
                f"valid dual-Python patch failed (exit {result.returncode}): {result.stderr}"
            )
        with config.open("rb") as handle:
            updated = tomllib.load(handle)
        expected = dict(old_tools, python=new_python, node=replacements["latest_node"], uv=replacements["latest_uv"])
        for tool in ("ruff", "pytest", "pre-commit"):
            expected["pypi:" + tool] = dict(old_tools["pypi:" + tool], python=new_python[0])
        if updated["tools"] != expected or updated["settings"] != reviewed["settings"]:
            different_tools = sorted(
                key for key in expected if updated["tools"].get(key) != expected[key]
            )
            raise AssertionError(
                "updater failed to preserve expected pins or Python update; "
                f"mismatched tools: {different_tools}"
            )

        # Malformed/reversed pins must fail closed before changing the other tools.
        for invalid in (
            f'python = ["{old_python[1]}", "{old_python[0]}"]',
            f'python = "{old_python[0]}"',
        ):
            broken = original.replace(
                f'python = ["{old_python[0]}", "{old_python[1]}"]', invalid
            )
            if broken == original:
                raise AssertionError("invalid fixture could not replace reviewed Python declaration")
            config.write_text(broken, encoding="utf-8")
            result = execute()
            if result.returncode == 0 or config.read_text(encoding="utf-8") != broken:
                raise AssertionError("updater modified a malformed dual-Python fixture")


def simulate_post_update_pin_fixture(body: str, root: Path) -> None:
    """The updater's version-pin test must also work after a real upstream bump."""
    original = (root / "mise.toml").read_text(encoding="utf-8")
    tools = tomllib.loads(original)["tools"]
    fixture = original

    # Reproduce a candidate update that has already changed both PyPI and
    # Aqua tool versions, while pytest can still be held back by the age gate.
    for tool in ("ruff", "pre-commit"):
        pin = tools[f"pypi:{tool}"]
        previous = pin["version"]
        newer = previous.rsplit(".", 1)[0] + "." + str(int(previous.rsplit(".", 1)[1]) + 1)
        old_line = f'"pypi:{tool}" = {{ version = "{previous}", python = "{pin["python"]}" }}'
        new_line = f'"pypi:{tool}" = {{ version = "{newer}", python = "{pin["python"]}" }}'
        if fixture.count(old_line) != 1:
            raise AssertionError(f"missing fixture pin for pypi:{tool}")
        fixture = fixture.replace(old_line, new_line, 1)

    old_yq = tools["yq"]
    new_yq = old_yq.rsplit(".", 1)[0] + "." + str(int(old_yq.rsplit(".", 1)[1]) + 1)
    old_line = f'yq = "{old_yq}"'
    if fixture.count(old_line) != 1:
        raise AssertionError("missing fixture pin for yq")
    fixture = fixture.replace(old_line, f'yq = "{new_yq}"', 1)
    simulate_version_updates(body, root, fixture_content=fixture)


def expect_rejection(body: str) -> None:
    try:
        validate_step(body)
    except AssertionError:
        return
    raise AssertionError("unsafe/corrupted updater fixture was accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root
    body = shell_step((root / ".github/workflows/check-upstream.yml").read_text(encoding="utf-8"))
    validate_step(body)
    simulate_version_updates(body, root)
    simulate_post_update_pin_fixture(body, root)
    expect_rejection(body.replace(GUARD, GUARD.replace("' mise.toml; then", ""), 1))
    expect_rejection(body + '\ngit commit -m "chore: update upstream versions and review evidence"\n')
    expect_rejection(body.replace('replace_env PYTHON_315_VERSION "$latest_python_315"', "# removed 3.15 update", 1))
    print("Dual-Python updater shell, offline pin mutation and single-flow regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
