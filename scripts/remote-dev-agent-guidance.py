#!/usr/bin/env python3
"""Offline provider-native guidance; owns a block, never a user-global file."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import secrets
import stat
import sys

CANONICAL = Path('/usr/share/remote-dev/agent-rules/development-environment.md')
CODEX_NATIVE_HOME = Path('/root/.codex')
ANTIGRAVITY_CONFIG = Path('/root/.gemini/config')
ANTIGRAVITY_NAME = 'remote-dev-development-environment.md'
START = b'<!-- BEGIN REMOTE DEV MANAGED DEVELOPMENT ENVIRONMENT -->'
END = b'<!-- END REMOTE DEV MANAGED DEVELOPMENT ENVIRONMENT -->'
IDENTITY = b'REMOTE DEV MANAGED DEVELOPMENT ENVIRONMENT'
FRONTMATTER = (b'---\ntrigger: always_on\n'
               b'description: "Remote Dev development environment guidance"\n---\n')
MAX_BYTES = 2 * 1024 * 1024
MAX_RULE_BYTES = 8192
DIRECTORY_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW


class GuidanceError(RuntimeError):
    def __init__(self, state: str):
        self.state = state
        super().__init__(state)


@dataclass
class File:
    data: bytes
    info: os.stat_result | None


def identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def directory(path: Path, *, create: bool = False, private_root: Path | None = None):
    """Pin each ancestor without following links; never chmod existing state."""
    if not path.is_absolute() or '..' in path.parts:
        raise GuidanceError('unsafe')
    fd = os.open('/', DIRECTORY_FLAGS)
    allowed_uids = {0, os.geteuid()}
    current = Path('/')
    try:
        for index, part in enumerate(path.parts[1:]):
            current = current / part
            try:
                next_fd = os.open(part, DIRECTORY_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, mode=0o700, dir_fd=fd)
                next_fd = os.open(part, DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            info = os.fstat(fd)
            # The native private bind root may retain an operator's host UID.
            # Bootstrap deliberately preserves it. Trust that owner only at
            # this fixed root, with private 0700 mode, and below it; do not chown.
            if current == private_root and stat.S_IMODE(info.st_mode) == 0o700:
                allowed_uids.add(info.st_uid)
            # Root-owned sticky /tmp is allowed as an ancestor for synthetic
            # fixtures, never as the managed provider directory itself.
            sticky_ancestor = (index < len(path.parts) - 2
                               and info.st_uid == 0 and info.st_mode & stat.S_ISVTX)
            if info.st_uid not in allowed_uids or (info.st_mode & 0o022 and not sticky_ancestor):
                raise GuidanceError('unsafe')
        info = os.fstat(fd)
        if info.st_uid not in allowed_uids:
            raise GuidanceError('unsafe')
        yield fd
    finally:
        os.close(fd)


def read_file(fd: int, name: str, *, limit: int = MAX_BYTES,
              canonical: bool = False) -> File:
    try:
        before = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return File(b'', None)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise GuidanceError('unsafe')
    expected_uids = {0, os.geteuid()} if canonical else {os.geteuid(), os.fstat(fd).st_uid}
    if (before.st_uid not in expected_uids or before.st_mode & 0o7022
            or not before.st_mode & stat.S_IRUSR or before.st_size > limit):
        raise GuidanceError('unsafe')
    file_fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        if identity(before) != identity(os.fstat(file_fd)):
            raise GuidanceError('unsafe')
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(file_fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b''.join(chunks)
        if len(data) > limit or identity(before) != identity(os.fstat(file_fd)):
            raise GuidanceError('unsafe')
        data.decode('utf-8')
        return File(data, before)
    finally:
        os.close(file_fd)


def atomic_write(fd: int, name: str, old: File, data: bytes) -> None:
    if old.info is not None and old.data == data:
        return
    if len(data) > MAX_BYTES:
        raise GuidanceError('unsafe')
    # Private staging is in the pinned provider directory, never inherited TMPDIR.
    temporary = f'.{name}.{secrets.token_hex(12)}'
    temp_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                      0o600, dir_fd=fd)
    try:
        with os.fdopen(temp_fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            if old.info is not None:
                temporary_info = os.fstat(stream.fileno())
                if (temporary_info.st_uid, temporary_info.st_gid) != (old.info.st_uid, old.info.st_gid):
                    # Atomic replacement must preserve the user file's owner,
                    # not turn operator-owned global instructions into root state.
                    os.fchown(stream.fileno(), old.info.st_uid, old.info.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(old.info.st_mode) if old.info else 0o600)
            os.fsync(stream.fileno())
        fresh = read_file(fd, name)
        if (fresh.data != old.data or (fresh.info is None) != (old.info is None)
                or (fresh.info is not None and identity(fresh.info) != identity(old.info))):
            raise GuidanceError('unsafe')
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def marker_span(data: bytes) -> tuple[int, int] | None:
    """Exact complete lines only; reject duplicate, partial and malformed markers."""
    if IDENTITY not in data:
        return None
    lines = data.splitlines(keepends=True)
    starts, ends = [], []
    offset = 0
    for line in lines:
        plain = line.rstrip(b'\r\n')
        if IDENTITY in line:
            if plain == START:
                starts.append(offset)
            elif plain == END:
                ends.append(offset + len(line))
            else:
                raise GuidanceError('unowned-conflict')
        offset += len(line)
    if len(starts) != 1 or len(ends) != 1 or ends[0] <= starts[0]:
        raise GuidanceError('unowned-conflict')
    return starts[0], ends[0]


def unowned(data: bytes, span: tuple[int, int] | None) -> bytes:
    return data if span is None else data[:span[0]] + data[span[1]:]


def codex_nonempty(data: bytes) -> bool:
    # Rust str::trim uses Unicode White_Space. Python str.strip additionally
    # strips U+001C..001F, which must remain active user text for Codex 0.160.0.
    whitespace = '\u0009\u000a\u000b\u000c\u000d\u0020\u0085\u00a0\u1680' \
                 '\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a' \
                 '\u2028\u2029\u202f\u205f\u3000'
    return bool(data.decode('utf-8').strip(whitespace))


def codex(fd: int, block: bytes, *, reconcile: bool) -> str:
    degraded = False
    removals = []
    # Only a directory override has an unambiguous native non-file fallback.
    # Readable symlinks/invalid UTF-8/oversize are never treated as inactive.
    try:
        info = os.stat('AGENTS.override.md', dir_fd=fd, follow_symlinks=False)
        degraded = stat.S_ISDIR(info.st_mode)
    except FileNotFoundError:
        pass
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EPERM}:
            raise
        degraded = True
    if not degraded:
        try:
            override = read_file(fd, 'AGENTS.override.md')
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EPERM}:
                raise
            degraded = True
        else:
            span = marker_span(override.data)
            remainder = unowned(override.data, span)
            if codex_nonempty(remainder):
                return apply(fd, 'AGENTS.override.md', override, span, block, reconcile=reconcile)
            if span is not None:
                removals.append(('AGENTS.override.md', override, remainder))
    base = read_file(fd, 'AGENTS.md')
    span = marker_span(base.data)
    # Validate both edits before changing the managed-only override. A conflict
    # in the default must not cause a partially repaired pair of global files.
    candidate = candidate_block(base.data, span, block)
    if len(candidate) > MAX_BYTES:
        raise GuidanceError('unsafe')
    result = apply(fd, 'AGENTS.md', base, span, block, reconcile=reconcile)
    if reconcile:
        for name, old, remainder in removals:
            atomic_write(fd, name, old, remainder)
    elif removals:
        result = 'stale'
    return 'unsafe' if degraded else result


def candidate_block(data: bytes, span: tuple[int, int] | None, block: bytes) -> bytes:
    if span is None:
        return block + data
    return data[:span[0]] + block + data[span[1]:]


def apply(fd: int, name: str, old: File, span: tuple[int, int] | None,
          block: bytes, *, reconcile: bool) -> str:
    candidate = candidate_block(old.data, span, block)
    state = 'missing' if span is None else ('current' if old.data == candidate else 'stale')
    if reconcile:
        atomic_write(fd, name, old, candidate)
        return 'current'
    return state


def antigravity(fd: int, block: bytes, *, reconcile: bool) -> str:
    old = read_file(fd, ANTIGRAVITY_NAME)
    if old.info is not None:
        span = marker_span(old.data)
        # Entire dedicated representation is owned, only with exact frontmatter
        # and a complete bounded block; unrelated bytes indicate a collision.
        if span is None or span != (len(FRONTMATTER), len(old.data)) or not old.data.startswith(FRONTMATTER):
            raise GuidanceError('unowned-conflict')
    candidate = FRONTMATTER + block
    state = 'missing' if old.info is None else ('current' if old.data == candidate else 'stale')
    if reconcile:
        atomic_write(fd, ANTIGRAVITY_NAME, old, candidate)
        return 'current'
    return state


def run(provider: str, *, reconcile: bool) -> str:
    # Check role before reading canonical or private state. Launcher gets neither.
    if provider not in {'codex', 'antigravity'} or os.environ.get('REMOTE_DEV_ROLE', 'codex') != provider:
        return 'unsupported'
    with directory(CANONICAL.parent) as fd:
        rule = read_file(fd, CANONICAL.name, limit=MAX_RULE_BYTES, canonical=True).data
    if not rule or not codex_nonempty(rule) or IDENTITY in rule:
        raise GuidanceError('unsafe')
    block = START + b'\n' + rule + (b'' if rule.endswith(b'\n') else b'\n') + END + b'\n'
    home = Path(os.environ.get('CODEX_HOME', str(CODEX_NATIVE_HOME))) if provider == 'codex' else ANTIGRAVITY_CONFIG
    workspace = Path(os.environ.get('WORKSPACE', '/workspace'))
    if home.is_relative_to(Path('/workspace')) or home.is_relative_to(workspace):
        raise GuidanceError('unsafe')
    private_root = ANTIGRAVITY_CONFIG if provider == 'antigravity' else (
        CODEX_NATIVE_HOME if home == CODEX_NATIVE_HOME else None)
    if provider == 'antigravity':
        home = home / 'rules'
    try:
        with directory(home, create=reconcile, private_root=private_root) as fd:
            return codex(fd, block, reconcile=reconcile) if provider == 'codex' else antigravity(fd, block, reconcile=reconcile)
    except FileNotFoundError:
        return 'missing'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['reconcile', 'status'])
    parser.add_argument('provider', choices=['codex', 'antigravity'])
    args = parser.parse_args()
    try:
        state = run(args.provider, reconcile=args.command == 'reconcile')
    except GuidanceError as exc:
        state = exc.state
    except (OSError, UnicodeError, ValueError):
        state = 'unsafe'
    print(f'{args.provider.capitalize()} Remote Dev guidance: {state}')
    degraded = state in {'unsafe', 'unowned-conflict', 'unsupported'}
    if args.command == 'reconcile' and degraded:
        print('WARNING: Remote Dev guidance is degraded; unsafe or unowned content was not repaired. '
              'The provider session may continue; inspect global guidance manually.', file=sys.stderr)
    return 3 if degraded else 0


if __name__ == '__main__':
    raise SystemExit(main())
