#!/usr/bin/env python3
"""Ensure every local Dockerfile build input triggers the main Edge publisher.

The repository's two Dockerfiles use literal COPY sources and literal bind-mount
sources. Keep this bounded static contract explicit rather than building a
general-purpose Dockerfile or GitHub Actions YAML interpreter.
"""
from __future__ import annotations

from pathlib import Path
import re
import shlex
import unittest


ROOT = Path(__file__).resolve().parents[1]
EDGE_WORKFLOW = ROOT / ".github/workflows/publish-edge-amd64.yml"
DOCKERFILES = (ROOT / "images/base/Dockerfile", ROOT / "images/codex/Dockerfile")
PUSH_PATHS = re.compile(
    r'(?m)^  push:\n    branches:\n      - main\n    paths:\n'
    r'(?P<items>(?:      - "[^"\n]+"\n)+)'
)
BIND_SOURCES = re.compile(r'--mount=type=bind,source=([^,\s\\]+)')


def edge_push_paths(source: str) -> tuple[str, ...]:
    matches = list(PUSH_PATHS.finditer(source))
    if len(matches) != 1:
        raise ValueError("Edge must have exactly one reviewed main push paths filter")
    paths = tuple(re.findall(r'^      - "([^"\n]+)"$', matches[0]["items"], re.M))
    if len(paths) != len(set(paths)):
        raise ValueError("Edge push filter contains duplicate paths")
    return paths


def local_source_probe(source: str) -> str:
    """Use one descendant for COPY directories to match subtree path filters."""
    if not source or source.startswith(("/", "-")) or "$" in source or "*" in source:
        raise ValueError(f"unreviewed Dockerfile local input: {source!r}")
    path = ROOT / source
    if not path.exists():
        raise ValueError(f"Dockerfile input is missing from repository: {source}")
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError(f"Dockerfile input escapes repository root: {source}")
    return str(Path(source) / "__edge_source_probe__") if path.is_dir() else source


def dockerfile_inputs() -> set[str]:
    sources: set[str] = {".dockerignore", "versions.env"}
    for dockerfile in DOCKERFILES:
        for line in dockerfile.read_text(encoding="utf-8").splitlines():
            if line.startswith(("COPY ", "ADD ")):
                args = shlex.split(line)
                flags = [arg for arg in args[1:] if arg.startswith("--")]
                # COPY --from reads from a build stage rather than the repository.
                if any(flag.startswith("--from=") for flag in flags):
                    continue
                fields = [arg for arg in args[1:] if not arg.startswith("--")]
                if len(fields) < 2:
                    raise ValueError(f"unrecognized Dockerfile COPY/ADD: {line}")
                sources.update(local_source_probe(item) for item in fields[:-1])
            for source in BIND_SOURCES.findall(line):
                sources.add(local_source_probe(source))
    return sources


def covers(path: str, patterns: tuple[str, ...]) -> bool:
    """Patterns currently admitted by this repository: exact names or subtree/**."""
    for pattern in patterns:
        if pattern == path:
            return True
        if pattern.endswith("/**") and path.startswith(pattern[:-2] + "/"):
            return True
    return False


def require_coverage(inputs: set[str], patterns: tuple[str, ...]) -> None:
    missing = sorted(path for path in inputs if not covers(path, patterns))
    if missing:
        raise ValueError(f"Edge does not rebuild for Dockerfile inputs: {missing}")


class EdgeBuildSourceContract(unittest.TestCase):
    def test_all_literal_dockerfile_inputs_trigger_edge(self) -> None:
        inputs = dockerfile_inputs()
        # Non-vacuous assertions: current Dockerfiles really ship these files.
        self.assertIn("LICENSE", inputs)
        self.assertIn("web/ttyd-osc52/dist/index.html", inputs)
        self.assertIn("config/playwright-mcp.json", inputs)
        self.assertIn("scripts/remote-dev-menu.sh", inputs)
        patterns = edge_push_paths(EDGE_WORKFLOW.read_text(encoding="utf-8"))
        require_coverage(inputs, patterns)

    def test_missing_web_or_license_filter_is_detected(self) -> None:
        patterns = edge_push_paths(EDGE_WORKFLOW.read_text(encoding="utf-8"))
        for removed, uncovered in (
            ("web/**", "web/ttyd-osc52/dist/index.html"),
            ("LICENSE", "LICENSE"),
        ):
            with self.subTest(removed=removed):
                self.assertIn(removed, patterns)
                reduced = tuple(path for path in patterns if path != removed)
                with self.assertRaisesRegex(ValueError, "Edge does not rebuild"):
                    require_coverage({uncovered}, reduced)

    def test_unlisted_future_source_is_rejected(self) -> None:
        patterns = edge_push_paths(EDGE_WORKFLOW.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "Edge does not rebuild"):
            require_coverage({"future-in-image/new-component.dat"}, patterns)

    def test_bad_push_path_contract_fails_closed(self) -> None:
        workflow = EDGE_WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(
            len(edge_push_paths(workflow)),
            len(set(edge_push_paths(workflow))),
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            edge_push_paths(workflow.replace("    paths:\n", "    paths-ignore:\n", 1))


if __name__ == "__main__":
    unittest.main()
