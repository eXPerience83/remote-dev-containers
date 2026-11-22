#!/usr/bin/env python3
"""Fail-closed preflight: immutable version tags and monotonic stable promotion.

Executed after image build/smoke/scans, immediately before any GHCR tag write.
Inspect all aliases without mutating them. This is NOT a registry transaction:
partial-promotion failures require documented human reconciliation.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

VERSION = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE = re.compile(r"^ghcr\.io/experience83/remote-dev(?:-base)?@sha256:[0-9a-f]{64}$")
NAMESPACE = "ghcr.io/experience83"


def demand(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=90)


def read_tag(image: str, tag: str) -> str | None:
    ref = f"{NAMESPACE}/{image}:{tag}"
    result = run("docker", "buildx", "imagetools", "inspect", ref,
                 "--format", "{{json .Manifest.Digest}}")
    if result.returncode != 0:
        # A substring is not proof of tag absence: gateways, auth servers
        # and registries may mention "manifest unknown" in a larger failure.
        # Accept ONLY one unambiguous, whole-line missing-manifest response.
        # Everything else (including 503 + manifest unknown) fails closed.
        message = (result.stderr + result.stdout).strip()
        missing = (
            "manifest unknown",
            "manifest not found",
            ref + ": not found",
            ref + ": manifest unknown",
            ref + ": manifest not found",
        )
        normalized = re.sub(r"^(?:ERROR:\s*)", "", message, flags=re.I).strip()
        if any(normalized.lower() == item.lower() for item in missing):
            return None
        # Never print raw registry stderr: token, account and credential
        # context can be included by an upstream docker helper.
        raise ValueError("cannot inspect existing GHCR tag " + ref +
                         " (exit " + str(result.returncode) +
                         "); absence not established")
    try:
        value = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise ValueError("malformed registry digest response for " + ref) from exc
    demand(isinstance(value, str) and bool(DIGEST.fullmatch(value)),
           "invalid registry digest of " + ref)
    return value


def image_release(ref: str) -> str:
    resolver = Path(__file__).resolve().with_name("resolve-oci-platform-manifest.sh")
    child = run("bash", str(resolver), ref, "linux", "amd64")
    demand(child.returncode == 0, "old stable index has no unique linux/amd64 child")
    child_ref = child.stdout.strip()
    demand(bool(IMAGE.fullmatch(child_ref)), "invalid old stable AMD64 ref")
    # Buildx can read the immutable child's image configuration directly
    # from GHCR. Unlike 'docker pull', this does NOT download large image layers
    # to a cold Actions runner under the global 90-second metadata timeout.
    checked = run("docker", "buildx", "imagetools", "inspect", child_ref,
                  "--format", "{{json .Image}}")
    demand(checked.returncode == 0, "cannot inspect previous stable image config")
    try:
        config = json.loads(checked.stdout.strip())
    except json.JSONDecodeError as exc:
        raise ValueError("invalid previous stable OCI image config JSON") from exc
    demand(isinstance(config, dict) and
           config.get("os") == "linux" and config.get("architecture") == "amd64",
           "previous stable image config has invalid platform")
    labels = config.get("config", {}).get("Labels")
    demand(isinstance(labels, dict), "previous stable image config has no labels")
    version = labels.get("org.opencontainers.image.version")
    demand(isinstance(version, str) and VERSION.fullmatch(version) is not None,
           "existing stable image has invalid version label")
    return version


def compare(old: str, new: str) -> bool:
    a, z = VERSION.fullmatch(old), VERSION.fullmatch(new)
    demand(a is not None and z is not None, "invalid SemVer release")
    return tuple(map(int, a.groups())) < tuple(map(int, z.groups()))


def validate(tag: str, base_ref: str, runtime_ref: str) -> dict:
    demand(VERSION.fullmatch(tag) is not None, "tag must be canonical vMAJOR.MINOR.PATCH")
    demand(bool(IMAGE.fullmatch(base_ref)) and "/remote-dev-base@" in base_ref,
           "invalid immutable base candidate")
    demand(bool(IMAGE.fullmatch(runtime_ref)) and "/remote-dev@" in runtime_ref,
           "invalid immutable runtime candidate")
    base_digest, runtime_digest = base_ref.split("@")[1], runtime_ref.split("@")[1]
    # Read all tags *before* any write. A failed lookup is not permission to overwrite.
    tags = {
        "base-version": read_tag("remote-dev-base", tag),
        "base-stable-amd64": read_tag("remote-dev-base", "stable-amd64"),
        "runtime-version": read_tag("remote-dev", tag),
        "runtime-stable": read_tag("remote-dev", "stable"),
        "runtime-stable-amd64": read_tag("remote-dev", "stable-amd64"),
        "runtime-latest": read_tag("remote-dev", "latest"),
    }
    existing_base, existing_runtime = tags["base-version"], tags["runtime-version"]
    demand((existing_base is None) == (existing_runtime is None),
           "partial version-tag publication needs manual reconciliation")
    if existing_runtime is not None:
        demand(existing_base == base_digest and existing_runtime == runtime_digest,
               "immutable SemVer tag exists with another image digest: no overwrite")
        demand(tags["base-stable-amd64"] == base_digest and
               all(tags[k] == runtime_digest for k in (
                   "runtime-stable", "runtime-stable-amd64", "runtime-latest")),
               "rerun is not idempotent: aliases changed; manual reconciliation needed")
        mode = "idempotent"
    else:
        alias_values = [tags[k] for k in (
            "runtime-stable", "runtime-stable-amd64", "runtime-latest")]
        demand(len(set(alias_values)) == 1, "existing stable aliases disagree")
        old_digest = alias_values[0]
        if old_digest is None:
            demand(tags["base-stable-amd64"] is None,
                   "base stable tag exists without runtime stable")
            previous = None
        else:
            demand(tags["base-stable-amd64"] is not None,
                   "runtime stable exists without base stable")
            previous = image_release(f"{NAMESPACE}/remote-dev@{old_digest}")
            old_base_version = image_release(
                f"{NAMESPACE}/remote-dev-base@{tags['base-stable-amd64']}")
            demand(old_base_version == previous, "base/runtime stable version mismatch")
            demand(compare(previous, tag),
                   f"release rollback or same-version overwrite forbidden: {previous} -> {tag}")
        mode = "fresh"
    return {"mode": mode, "tag": tag, "base_candidate": base_ref,
            "runtime_candidate": runtime_ref, "before": tags,
            "previous_version": previous if mode == "fresh" else tag}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tag", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--runtime", required=True)
    p.add_argument("--journal", required=True, type=Path)
    args = p.parse_args()
    try:
        record = validate(args.tag, args.base, args.runtime)
    except (ValueError, subprocess.TimeoutExpired, OSError) as exc:
        print("ERROR: stable release promotion preflight: " + str(exc))
        return 1
    args.journal.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write("mode=" + record["mode"] + "\n")
    print("Stable promotion preflight: " + record["mode"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
