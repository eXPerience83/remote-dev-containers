#!/usr/bin/env python3
"""Offline executable sentinels: no Docker daemon, GHCR writes or secrets."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/validate-edge-publication-candidate.sh"
STABLE = ROOT / ".github/workflows/publish-amd64.yml"
TAIL_MARKER = "# Exercise the exact runtime manifest rather than rebuilding a second image.\n"
PROMOTE_MARKER = "      - name: Promote one scanned digest to canonical stable tags\n"

RUNTIME_STUB = r"""
set -euo pipefail
root=/offline/remote-dev
runtime_ref=ghcr.io/experience83/remote-dev@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
expected_version=v0.3.0
expected_revision=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
expected_channel=stable
docker() {
  printf 'docker:%s\n' "$*" >> "$AUDIT_LOG"
  if [[ "$SIM_FAIL" == codex && "$*" == *codex-smoke-test* ]]; then return 73; fi
}
timeout() { printf 'timeout:%s\n' "$*" >> "$AUDIT_LOG"; }
bash() {
  printf 'probe:%s\n' "$1" >> "$AUDIT_LOG"
  case "$SIM_FAIL:$1" in
    runtime:*/runtime-smoke-test.sh|password:*/test-web-password-runtime.sh|isolation:*/test-cross-service-isolation.sh) return 73;;
  esac
}
"""
PROMOTE_STUB = r"""
set -euo pipefail
NAMESPACE=experience83
GITHUB_REF_NAME=v0.3.0
BASE_DIGEST=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
REMOTE_DEV_DIGEST=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
docker() {
  printf 'docker:%s\n' "$*" >> "$AUDIT_LOG"
  if [[ "$1 $2 $3" == "buildx imagetools create" ]]; then
    local old="" metadata="" item=""
    for item in "$@"; do
      if [[ "$old" == "--metadata-file" ]]; then metadata="$item"; fi
      old="$item"
    done
    local ref="${!#}"
    printf '{"containerimage.descriptor":{"digest":"%s"}}\n' "${ref##*@}" > "$metadata"
    return 0
  fi
  if [[ "$1 $2 $3" == "buildx imagetools inspect" ]]; then
    local digest="$REMOTE_DEV_DIGEST"
    if [[ "$4" == */remote-dev-base:* ]]; then
      digest="$BASE_DIGEST"
      if [[ "$SIM_FAIL" == base ]]; then digest=sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff; fi
    elif [[ "$SIM_FAIL" == runtime ]]; then
      digest=sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    fi
    printf '"%s"\n' "$digest"
    return 0
  fi
  return 75
}
"""

def ensure(test: bool, message: str) -> None:
    if not test:
        raise AssertionError(message)

def tail(helper: str) -> str:
    ensure(helper.count(TAIL_MARKER) == 1, "candidate probe marker absent/ambiguous")
    return helper.split(TAIL_MARKER, 1)[1]

def promotion(workflow: str) -> str:
    ensure(workflow.count(PROMOTE_MARKER) == 1, "stable promotion step absent")
    block = workflow.split(PROMOTE_MARKER, 1)[1]
    ensure("        run: |\n" in block, "promotion run block absent")
    block = block.split("        run: |\n", 1)[1]
    end = block.find("\n      - name:")
    ensure(end != -1, "promotion must be followed by journal upload")
    return textwrap.dedent(block[:end]).strip() + "\n"

def execute(shell: str, stub: str, failure: str = "") -> tuple[int, list[str], str]:
    with tempfile.TemporaryDirectory(prefix="release-shell-test-") as td:
        logfile = Path(td) / "events"
        logfile.touch()
        env = {**os.environ, "AUDIT_LOG": str(logfile), "SIM_FAIL": failure}
        res = subprocess.run(["bash", "-c", stub + "\n" + shell],
                             cwd=td, env=env, capture_output=True,
                             text=True, timeout=20, check=False)
        return res.returncode, logfile.read_text().splitlines(), res.stderr

def probe_contract(helper: str) -> None:
    snippet = tail(helper)
    rc, events, err = execute(snippet, RUNTIME_STUB)
    ensure(rc == 0, "candidate probe tail failed with stubs: " + err[-250:])
    observed = [e for e in events if e.startswith("probe:")]
    expected = [
        "probe:/offline/remote-dev/scripts/runtime-smoke-test.sh",
        "probe:/offline/remote-dev/scripts/test-web-password-runtime.sh",
        "probe:/offline/remote-dev/scripts/test-cross-service-isolation.sh",
    ]
    ensure(observed == expected, "mandatory probes omitted/out of order: " + repr(observed))
    ensure(sum("codex-smoke-test" in e for e in events) == 1, "Codex image smoke not reached")
    for failure in ("codex", "runtime", "password", "isolation"):
        rc, _, _ = execute(snippet, RUNTIME_STUB, failure)
        ensure(rc != 0, "failure silently ignored by candidate probe: " + failure)

def registry_contract(workflow: str) -> None:
    snippet = promotion(workflow)
    rc, events, err = execute(snippet, PROMOTE_STUB)
    ensure(rc == 0, "registry simulation failed: " + err[-400:])
    writes = [e for e in events if e.startswith("docker:buildx imagetools create")]
    reads = [e for e in events if e.startswith("docker:buildx imagetools inspect")]
    ensure(len(writes) == 2 and len(reads) == 6,
           "expected two index writes and six registry readbacks")
    for failure in ("base", "runtime"):
        rc, _, _ = execute(snippet, PROMOTE_STUB, failure)
        ensure(rc != 0, "mismatched registry readback did not block: " + failure)

def main() -> None:
    helper = HELPER.read_text(encoding="utf-8")
    workflow = STABLE.read_text(encoding="utf-8")
    probe_contract(helper)
    registry_contract(workflow)
    password = 'bash "$root/scripts/test-web-password-runtime.sh" "$runtime_ref"'
    isolation = 'bash "$root/scripts/test-cross-service-isolation.sh" "$runtime_ref"'
    ensure(helper.count(password) == 1 and helper.count(isolation) == 1,
           "mandatory probe fixture missing")
    mutations = (
        ("exit before password", helper.replace(password, "exit 0\n" + password, 1)),
        ("unreachable password/isolation", helper.replace(
            password + "\n" + isolation,
            "if false; then\n" + password + "\n" + isolation + "\nfi", 1)),
    )
    for label, mutated in mutations:
        try:
            probe_contract(mutated)
        except AssertionError:
            continue
        raise AssertionError("false PASS for candidate probe mutation: " + label)
    check = 'if [[ "$actual_digest" != "$REMOTE_DEV_DIGEST" ]]; then'
    ensure(workflow.count(check) == 1, "runtime registry readback fixture missing")
    try:
        registry_contract(workflow.replace(check, "if false; then", 1))
    except AssertionError:
        pass
    else:
        raise AssertionError("false PASS for bypassed runtime registry readback")
    print("Offline publication shell execution sentinels: OK")

if __name__ == "__main__":
    main()
