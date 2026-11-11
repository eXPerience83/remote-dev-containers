#!/usr/bin/env python3
"""Read-only Playwright candidate discovery and bounded upstream PR reconciliation.

Discovery runs separately on each architecture without repository write
credentials. The writer only parses/revalidates JSON; it never installs or
executes downloaded npm/browser packages. This is not an image publisher.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ("chromium-headless-shell", "ffmpeg")
ARCHES = ("amd64", "arm64")
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
HASH = re.compile(r"[0-9a-f]{64}")
BUNDLE_NAME = "remote-dev-playwright-bundle"
MAX_META_BYTES = 2_000_000
MAX_ARCHIVE_BYTES = 600_000_000


class CandidateError(ValueError):
    """Unsupported update or untrusted metadata, without modifying any pins."""


def require(ok: bool, message: str) -> None:
    if not ok:
        raise CandidateError(message)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "expected a JSON object")
    return value


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def baseline_version(root: Path) -> str:
    from_text = (root / "versions.env").read_text(encoding="utf-8")
    matches = re.findall(r"^PLAYWRIGHT_MCP_VERSION=([^\s]+)$", from_text, re.M)
    require(len(matches) == 1 and SEMVER.fullmatch(matches[0]) is not None,
            "invalid baseline Playwright pin")
    return matches[0]


def lock_validator():
    path = ROOT / "scripts/validate-playwright-lock.py"
    spec = importlib.util.spec_from_file_location("playwright_lock_contract", path)
    require(spec is not None and spec.loader is not None, "missing lock validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def browser_validator():
    path = ROOT / "scripts/install-verified-playwright-browser.py"
    spec = importlib.util.spec_from_file_location("playwright_archive_contract", path)
    require(spec is not None and spec.loader is not None, "missing browser validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_archives(arch: str, archives: dict, core_version: str) -> None:
    require(arch in ARCHES and isinstance(archives, dict)
            and set(archives) == set(COMPONENTS), "unreviewed browser payload graph")
    for component in COMPONENTS:
        item = archives[component]
        require(isinstance(item, dict), "browser artifact is not an object")
        required = {"revision", "url", "sha256", "executable"}
        require(set(item) in (required, required | {"browserVersion"}),
                "unreviewed browser artifact metadata fields")
        rev, url = item["revision"], item["url"]
        require(isinstance(rev, str) and rev.isdecimal(), "unreviewed browser revision")
        require(isinstance(url, str), "unreviewed browser URL")
        parsed = urlsplit(url)
        require(parsed.scheme == "https" and parsed.hostname == "cdn.playwright.dev"
                and not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment, "unreviewed browser download host")
        require(isinstance(item["sha256"], str)
                and HASH.fullmatch(item["sha256"]) is not None, "missing browser SHA-256")
        if component == "chromium-headless-shell":
            suffix = ("linux64/chrome-headless-shell-linux64.zip" if arch == "amd64"
                      else "linux-arm64/chrome-headless-shell-linux-arm64.zip")
            require(url.startswith("https://cdn.playwright.dev/builds/cft/")
                    and url.endswith("/" + suffix), "unreviewed headless-shell URL")
            require(isinstance(item.get("browserVersion"), str)
                    and re.fullmatch(r"[0-9]+(\.[0-9]+){3}", item["browserVersion"]) is not None,
                    "unexpected Chromium version")
            expected_exe = ("chrome-headless-shell-linux64/chrome-headless-shell"
                            if arch == "amd64" else
                            "chrome-headless-shell-linux-arm64/chrome-headless-shell")
        else:
            require("browserVersion" not in item, "unexpected FFmpeg browser version")
            require(url == ("https://cdn.playwright.dev/dbazure/download/playwright/"
                            f"builds/ffmpeg/{rev}/"
                            + ("ffmpeg-linux.zip" if arch == "amd64" else
                               "ffmpeg-linux-arm64.zip")), "unreviewed FFmpeg URL")
            expected_exe = "ffmpeg-linux"
        require(item["executable"] == expected_exe, "unexpected browser binary path")
    require(SEMVER.fullmatch(core_version.split("-")[0]) is not None,
            "unreviewed Playwright Core version")


def npm_latest() -> str:
    url = "https://registry.npmjs.org/@playwright%2fmcp/latest"
    with urllib.request.urlopen(urllib.request.Request(
        url, headers={"User-Agent": "remote-dev-playwright-upstream/1"},
    ), timeout=30) as response:
        require(response.geturl() == url, "unexpected npm metadata redirect")
        payload = response.read(MAX_META_BYTES + 1)
    require(len(payload) <= MAX_META_BYTES, "npm metadata too large")
    data = json.loads(payload)
    require(isinstance(data, dict), "invalid npm release metadata")
    latest = data.get("version")
    require(isinstance(latest, str) and SEMVER.fullmatch(latest) is not None,
            "npm latest is not a stable semantic version")
    require(data.get("license") == "Apache-2.0", "upstream license changed")
    sri = data.get("dist", {}).get("integrity")
    require(isinstance(sri, str) and sri.startswith("sha512-"),
            "npm dist-tag lacks SHA-512")
    return latest, sri


def parse_dry_run(text: str) -> dict:
    return browser_validator()._metadata_blocks(text)


def archive_urls(arch: str, browser_metadata: dict, dry_run: str) -> dict:
    lines = parse_dry_run(dry_run)
    entries = {x["name"]: x for x in browser_metadata.get("browsers", [])
               if isinstance(x, dict) and isinstance(x.get("name"), str)}
    require(all(name in entries for name in COMPONENTS), "missing Playwright browser revision")
    result: dict = {}
    for component in COMPONENTS:
        entry = entries[component]
        revision = entry.get("revision")
        require(isinstance(revision, str) and revision.isdecimal(),
                "invalid upstream browser revision")
        actual = lines[component]
        expected_dir = ("/opt/remote-dev/playwright-browsers/"
                        + component.replace("-", "_") + "-" + revision)
        require(actual["location"] == expected_dir, "browser installed outside pinned image path")
        result[component] = {
            "revision": revision,
            **({"browserVersion": entry["browserVersion"]}
               if entry.get("browserVersion") is not None else {}),
            "url": actual["url"],
            "sha256": "0" * 64,  # replaced after hashing; never used for installation
            "executable": ("ffmpeg-linux" if component == "ffmpeg"
                           else ("chrome-headless-shell-linux64/chrome-headless-shell"
                                 if arch == "amd64" else
                                 "chrome-headless-shell-linux-arm64/chrome-headless-shell")),
        }
    core = browser_metadata.get("core_version", "1.0.0")
    validate_archives(arch, result, core)
    return result


def download_digest(url: str, temp: Path) -> str:
    parsed = urlsplit(url)
    require(parsed.scheme == "https" and parsed.hostname == "cdn.playwright.dev",
            "unreviewed archive host")
    archive = temp / "archive.zip"
    subprocess.run(
        ["curl", "--fail", "--show-error", "--silent", "--location",
         "--proto", "=https", "--proto-redir", "=https",
         "--retry", "3", "--connect-timeout", "25",
         "--max-time", "700", "--max-filesize", str(MAX_ARCHIVE_BYTES),
         "--output", str(archive), url],
        check=True, timeout=740,
    )
    require(0 < archive.stat().st_size <= MAX_ARCHIVE_BYTES,
            "oversized or empty browser archive")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    with zipfile.ZipFile(archive) as container:
        require(1 <= len(container.infolist()) <= 20_000,
                "unreviewed browser ZIP entry count")
        require(container.testzip() is None, "browser ZIP checksum validation failed")
    archive.unlink()
    return digest.hexdigest()


def produce(root: Path, arch: str) -> dict:
    require(arch in ARCHES, "unsupported architecture")
    baseline = baseline_version(root)
    release, release_sri = npm_latest()
    if tuple(map(int, release.split("."))) <= tuple(map(int, baseline.split("."))):
        return dict(schema_version=1, status="unchanged", arch=arch,
                    baseline_version=baseline, version=release)
    # Source notices must exist on the exact reviewed tag before any candidate
    # can enter the write-capable PR update path.
    notice = f"https://raw.githubusercontent.com/microsoft/playwright-mcp/v{release}/LICENSE"
    with urllib.request.urlopen(notice, timeout=30) as response:
        require(response.geturl() == notice, "unexpected license notice redirect")
        require(0 < len(response.read(65537)) <= 65536, "upstream license invalid")
    with tempfile.TemporaryDirectory(prefix="playwright-discovery-") as working:
        temp = Path(working)
        package = {"name": BUNDLE_NAME, "version": "0.0.0",
                   "private": True, "dependencies": {"@playwright/mcp": release}}
        (temp / "package.json").write_bytes(json_bytes(package))
        env = dict(os.environ, PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD="1",
                   npm_config_ignore_scripts="true", npm_config_audit="false")
        subprocess.run(
            ["npm", "install", "--package-lock-only", "--package-lock-version=3",
             "--ignore-scripts", "--no-audit", "--no-fund", "--prefix", str(temp)],
            check=True, timeout=240, env=env,
        )
        lock = read_json(temp / "package-lock.json")
        lock_validator().validate(package, lock, release)
        require(lock["packages"]["node_modules/@playwright/mcp"]["integrity"]
                == release_sri, "npm release integrity differs from reviewed lock")
        subprocess.run(
            ["npm", "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund",
             "--prefix", str(temp)], check=True, timeout=300, env=env,
        )
        core = lock["packages"]["node_modules/playwright-core"]["version"]
        manifest = read_json(temp / "node_modules/playwright-core/browsers.json")
        dry_run = subprocess.run(
            [str(temp / "node_modules/.bin/playwright"), "install",
             "--dry-run", "--only-shell", "chromium"],
            capture_output=True, text=True, check=True, timeout=90,
            env=dict(env, PLAYWRIGHT_BROWSERS_PATH="/opt/remote-dev/playwright-browsers"),
        ).stdout
        manifest["core_version"] = core
        archives = archive_urls(arch, manifest, dry_run)
        for name in COMPONENTS:
            archives[name]["sha256"] = download_digest(archives[name]["url"], temp)
        validate_archives(arch, archives, core)
        return {
            "schema_version": 1, "status": "candidate", "arch": arch,
            "baseline_version": baseline, "version": release,
            "package": package, "lock": lock,
            "playwright_core_version": core, "archives": archives,
        }


def check_report(report: dict, arch: str, baseline: str) -> str:
    require(isinstance(report, dict)
            and report.get("schema_version") == 1
            and report.get("arch") == arch
            and report.get("baseline_version") == baseline,
            "discovery artifact does not match reviewed baseline")
    status = report.get("status")
    require(status in ("candidate", "unchanged", "deferred"), "unknown discovery status")
    if status != "candidate":
        require(set(report) == {"schema_version", "status", "arch",
                               "baseline_version", "version"}
                if status == "unchanged" else
                set(report) == {"schema_version", "status", "arch",
                                "baseline_version", "reason"},
                "invalid reduced discovery artifact")
        if status == "unchanged":
            require(isinstance(report.get("version"), str)
                    and SEMVER.fullmatch(report["version"]) is not None,
                    "malformed unchanged version")
        else:
            require(isinstance(report.get("reason"), str)
                    and 1 <= len(report["reason"]) <= 160,
                    "malformed deferred reason")
        return status
    require(set(report) == {"schema_version", "status", "arch",
                           "baseline_version", "version", "package", "lock",
                           "playwright_core_version", "archives"},
            "unreviewed discovery artifact fields")
    version = report["version"]
    require(isinstance(version, str)
            and SEMVER.fullmatch(version) is not None
            and tuple(map(int, version.split("."))) >
                tuple(map(int, baseline.split("."))),
            "candidate version does not advance reviewed pin")
    require(isinstance(report["package"], dict)
            and isinstance(report["lock"], dict), "invalid npm lock metadata")
    lock_validator().validate(report["package"], report["lock"], version)
    core = report["lock"]["packages"]["node_modules/playwright-core"]["version"]
    require(report["playwright_core_version"] == core,
            "Playwright core version differs from npm lock")
    validate_archives(arch, report["archives"], core)
    return status


def reconcile(root: Path, amd64: dict, arm64: dict, *, write: bool) -> str:
    """Propose a coherent atomic source set or leave Playwright unchanged."""
    baseline = baseline_version(root)
    a = check_report(amd64, "amd64", baseline)
    b = check_report(arm64, "arm64", baseline)
    if a != "candidate" or b != "candidate":
        print(f"Playwright candidate deferred: amd64={a}, arm64={b}")
        return "deferred"
    for key in ("version", "package", "lock", "playwright_core_version"):
        require(amd64[key] == arm64[key], "architecture reports disagree: " + key)
    # Never accept identical archives masquerading as different architectures.
    for component in COMPONENTS:
        require(amd64["archives"][component]["url"] != arm64["archives"][component]["url"],
                "architecture-specific archive URLs were not distinct")
        require(amd64["archives"][component]["revision"]
                == arm64["archives"][component]["revision"],
                "architecture-specific revisions disagree")
        require(amd64["archives"][component].get("browserVersion")
                == arm64["archives"][component].get("browserVersion"),
                "architecture-specific browser versions disagree")
    version = amd64["version"]
    archive_manifest = {
        "schema_version": 1,
        "playwright_core_version": amd64["playwright_core_version"],
        "archives": {"amd64": amd64["archives"], "arm64": arm64["archives"]},
    }
    if not write:
        return "candidate"
    edits = {
        root / "config/playwright-package.json": json_bytes(amd64["package"]),
        root / "config/playwright-package-lock.json": json_bytes(amd64["lock"]),
        root / "config/playwright-browser-archives.json": json_bytes(archive_manifest),
    }
    for filename, line in (
        ("versions.env", "PLAYWRIGHT_MCP_VERSION="),
        ("images/base/Dockerfile", "ARG PLAYWRIGHT_MCP_VERSION="),
    ):
        target = root / filename
        source = target.read_text(encoding="utf-8")
        prefix = line + baseline
        require(source.splitlines().count(prefix) == 1,
                "Playwright version default differs from baseline: " + filename)
        new = source.replace(prefix + "\n", line + version + "\n")
        require(new != source, "could not rewrite version pin")
        edits[target] = new.encode("utf-8")
    for path, data in edits.items():
        path.write_bytes(data)
    print(f"Playwright candidate proposed: {baseline} -> {version} "
          "(npm SHA-512 and 4 browser SHA-256 hashes)")
    return "updated"


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_subparsers(dest="mode", required=True)
    discover = mode.add_parser("discover")
    discover.add_argument("--arch", choices=ARCHES, required=True)
    discover.add_argument("--output", type=Path, required=True)
    apply = mode.add_parser("reconcile")
    apply.add_argument("--amd64", type=Path, required=True)
    apply.add_argument("--arm64", type=Path, required=True)
    apply.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.mode == "discover":
        base = baseline_version(ROOT)
        try:
            report = produce(ROOT, args.arch)
        except Exception as exc:
            # Any unusual dependency graph, network outage, license change or
            # ZIP mismatch must not block the unrelated grouped tool updates.
            reason = type(exc).__name__
            report = {"schema_version": 1, "status": "deferred",
                      "arch": args.arch, "baseline_version": base,
                      "reason": reason}
            print(f"::warning::Playwright {args.arch} candidate deferred ({reason})",
                  file=sys.stderr)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(json_bytes(report))
        check_report(report, args.arch, base)
    else:
        result = reconcile(ROOT, read_json(args.amd64),
                           read_json(args.arm64), write=args.write)
        print("Playwright upstream proposal:", result)


if __name__ == "__main__":
    try:
        main()
    except (CandidateError, ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit("ERROR: Playwright upstream contract: " + str(exc)) from None
