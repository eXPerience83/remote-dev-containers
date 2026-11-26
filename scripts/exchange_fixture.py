"""Host-only adapter for tests of the real startup/Doctor Exchange OFF path."""
from pathlib import Path
import shlex
import sys
import tempfile


EXCHANGE_COMMAND = "/usr/local/lib/remote-dev/python -I /usr/local/lib/remote-dev/exchange_mount.py"
TARGET_DECLARATION = 'EXCHANGE_TARGET = "/exchange"'


def adapt_exchange_off(text: str, exchange_source: Path, fixture_root: Path) -> str:
    """Run the real checker on an absent private path, not the host's /exchange.

    The image's installed script and production target are never modified.
    Only the fixture invocation clears the inherited Exchange identity.
    """
    if text.count(EXCHANGE_COMMAND) != 1:
        raise AssertionError("expected exactly one Exchange command in the host fixture")
    source = exchange_source.read_text(encoding="utf-8")
    if source.count(TARGET_DECLARATION) != 1:
        raise AssertionError("expected exactly one Exchange target declaration")
    private = Path(tempfile.mkdtemp(prefix="exchange-fixture-", dir=fixture_root))
    target = private / "absent-exchange"
    checker = private / "exchange_mount.py"
    checker.write_text(
        source.replace(TARGET_DECLARATION, f"EXCHANGE_TARGET = {str(target)!r}"),
        encoding="utf-8",
    )
    command = shlex.join(["env", "REMOTE_DEV_EXCHANGE_FS=", sys.executable, "-I", str(checker)])
    return text.replace(EXCHANGE_COMMAND, command)
