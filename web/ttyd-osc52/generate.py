#!/usr/bin/env python3
"""Generate the ttyd 1.7.7 index with the bounded Remote Dev OSC 52 writer."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVENANCE_PATH = HERE / "provenance.json"
SCRIPT_PATH = HERE / "osc52-write.js"
DIST_PATH = HERE / "dist" / "index.html"
SUPPORTED_TTYD_VERSION = "1.7.7"
UPSTREAM_OWNER = "tsl0922"
UPSTREAM_REPOSITORY = "ttyd"
UPSTREAM_COMMIT = "40e79c706be14029b391f369bee6613c31667abb"
UPSTREAM_ARCHIVE_URL = (
    f"https://codeload.github.com/{UPSTREAM_OWNER}/{UPSTREAM_REPOSITORY}/tar.gz/{UPSTREAM_COMMIT}"
)
HEADER_PATTERN = re.compile(
    rb"unsigned char index_html\[\] = \{\n(?P<body>.*?)\n\};\n"
    rb"unsigned int index_html_len = (?P<length>\d+);\n"
    rb"unsigned int index_html_size = (?P<size>\d+);\n?",
    re.DOTALL,
)


class GenerationError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise GenerationError(f"{label} mismatch: expected {expected}, got {actual}")


def configured_ttyd_version() -> str:
    matches = re.findall(r"^TTYD_VERSION=(.+)$", (ROOT / "versions.env").read_text(), re.MULTILINE)
    if len(matches) != 1:
        raise GenerationError("versions.env must contain exactly one TTYD_VERSION")
    return matches[0]


def load_provenance() -> dict[str, object]:
    data = json.loads(PROVENANCE_PATH.read_text())
    require_equal(data.get("ttyd_version"), SUPPORTED_TTYD_VERSION, "provenance ttyd version")
    require_equal(configured_ttyd_version(), SUPPORTED_TTYD_VERSION, "repository ttyd version")
    require_equal(data.get("compatibility_issue"), 174, "compatibility review issue")
    require_equal(data.get("ttyd_commit"), UPSTREAM_COMMIT, "upstream ttyd commit")
    require_equal(data.get("archive_url"), UPSTREAM_ARCHIVE_URL, "upstream archive URL")
    return data


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_archive(path: Path | None, provenance: dict[str, object]) -> bytes:
    if path is not None:
        return path.read_bytes()
    require_equal(provenance.get("ttyd_commit"), UPSTREAM_COMMIT, "upstream ttyd commit")
    require_equal(provenance.get("archive_url"), UPSTREAM_ARCHIVE_URL, "upstream archive URL")
    request = urllib.request.Request(UPSTREAM_ARCHIVE_URL, headers={"User-Agent": "remote-dev-ttyd-osc52-generator"})
    opener = urllib.request.build_opener(NoRedirectHandler())
    try:
        with opener.open(request, timeout=300) as response:
            require_equal(response.geturl(), UPSTREAM_ARCHIVE_URL, "upstream archive response URL")
            require_equal(response.getcode(), 200, "upstream archive response status")
            return response.read()
    except urllib.error.HTTPError as error:
        raise GenerationError(f"upstream archive download failed: HTTP {error.code}") from error


def extract_header(archive: bytes, provenance: dict[str, object]) -> bytes:
    return extract_member(archive, str(provenance["html_header_path"]))


def extract_member(archive: bytes, member_name: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        matches = [member for member in source.getmembers() if member.name == member_name and member.isfile()]
        if len(matches) != 1:
            raise GenerationError(f"archive must contain exactly one regular {member_name}")
        extracted = source.extractfile(matches[0])
        if extracted is None:
            raise GenerationError(f"cannot extract {member_name}")
        return extracted.read()


def validate_zmodem_patch(archive: bytes, provenance: dict[str, object]) -> None:
    patch = provenance.get("zmodem_patch")
    if not isinstance(patch, dict):
        raise GenerationError("zmodem patch provenance must be an object")
    require_equal(patch.get("ttyd_commit"), UPSTREAM_COMMIT, "zmodem patch ttyd commit")
    upstream_path = f"ttyd-{UPSTREAM_COMMIT}/html/.yarn/patches/zmodem.js-npm-0.1.10-e5537fa2ed.patch"
    require_equal(patch.get("upstream_path"), upstream_path, "zmodem patch upstream path")
    require_equal(sha256(extract_member(archive, upstream_path)), patch.get("sha256"), "zmodem patch SHA-256")


def decode_baseline(header: bytes, provenance: dict[str, object]) -> bytes:
    match = HEADER_PATTERN.fullmatch(header)
    if match is None:
        raise GenerationError("src/html.h does not match the exact expected declaration shape")
    compressed = bytes(int(value, 16) for value in re.findall(rb"0x([0-9a-fA-F]{2})", match["body"]))
    require_equal(len(compressed), int(match["length"]), "embedded gzip length")
    try:
        baseline = gzip.decompress(compressed)
    except gzip.BadGzipFile as error:
        raise GenerationError("embedded index is not valid gzip") from error
    require_equal(len(baseline), int(match["size"]), "embedded HTML declared size")
    require_equal(len(baseline), provenance["baseline_html_size"], "baseline HTML size")
    require_equal(sha256(baseline), provenance["baseline_html_sha256"], "baseline HTML SHA-256")
    return baseline


def generate(archive: bytes, provenance: dict[str, object]) -> bytes:
    require_equal(sha256(archive), provenance["archive_sha256"], "archive SHA-256")
    header = extract_header(archive, provenance)
    require_equal(sha256(header), provenance["html_header_sha256"], "src/html.h SHA-256")
    validate_zmodem_patch(archive, provenance)
    baseline = decode_baseline(header, provenance)

    anchor = str(provenance["insertion_anchor"]).encode()
    require_equal(baseline.count(anchor), 1, "insertion anchor count")
    script = SCRIPT_PATH.read_bytes()
    if b"</script" in script.lower():
        raise GenerationError("OSC 52 source must not contain a closing script token")
    insertion = b'<script id="remote-dev-osc52-write">\n' + script.rstrip(b"\n") + b"\n</script>"
    return baseline.replace(anchor, insertion + anchor, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, help="use an already-downloaded exact upstream archive")
    parser.add_argument("--check", action="store_true", help="verify the committed asset instead of replacing it")
    args = parser.parse_args()

    try:
        provenance = load_provenance()
        generated = generate(read_archive(args.archive, provenance), provenance)
        if args.check:
            require_equal(len(generated), provenance["generated_html_size"], "generated HTML size")
            require_equal(sha256(generated), provenance["generated_html_sha256"], "generated HTML SHA-256")
            require_equal(DIST_PATH.read_bytes(), generated, "committed dist/index.html")
            print(f"OK ttyd OSC 52 index {len(generated)} bytes sha256:{sha256(generated)}")
        else:
            DIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            DIST_PATH.write_bytes(generated)
            print(f"Wrote {DIST_PATH.relative_to(ROOT)} {len(generated)} bytes sha256:{sha256(generated)}")
    except (GenerationError, OSError, json.JSONDecodeError, tarfile.TarError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
