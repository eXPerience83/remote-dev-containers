"""Fail-closed policy for repository scripts executed during image builds."""
from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

from .docker_parse import docker_instructions, executable_name, instruction_payload, run_commands
from .io import InventoryError

SCRIPT_REFERENCE_RE = re.compile(r"(?:\$ROOT/|\$\{ROOT\}/)?(scripts/[A-Za-z0-9_./-]+(?:\.sh|\.py))")
PYTHON_NETWORK_RE = re.compile(r"(?:urllib(?:\.request)?|requests|http\.client|urlopen|https?://)", re.I)
NODE_NETWORK_RE = re.compile(r"(?:\bfetch\s*\(|require\(['\"]https?['\"]\)|https?://)", re.I)


def _copy_mapping(root: Path, instructions: list[str]) -> dict[str, Path]:
    """Map deterministic COPY destinations back to repository script paths."""
    mapping: dict[str, Path] = {}
    for instruction in instructions:
        payload = instruction_payload(instruction, "COPY")
        if payload is None or payload.startswith("[") or "--from" in payload:
            continue
        try:
            tokens = shlex.split(payload)
        except ValueError as exc:
            raise InventoryError(f"cannot parse COPY while checking build scripts: {payload}") from exc
        tokens = [token for token in tokens if not token.startswith("--")]
        if len(tokens) != 2:
            continue
        source = root / tokens[0]
        if source.is_file() and source.suffix in {".sh", ".py"}:
            mapping[tokens[1]] = source
    return mapping


def _mount_mapping(root: Path, instruction: str) -> dict[str, Path]:
    """Map static BuildKit bind targets back to their context sources."""
    mapping: dict[str, Path] = {}
    payload = instruction_payload(instruction, "RUN") or ""
    for option in re.findall(r"--mount=([^\s]+)", payload):
        fields = dict(item.split("=", 1) for item in option.split(",") if "=" in item)
        if fields.get("type") != "bind" or "source" not in fields or "target" not in fields:
            continue
        source = root / fields["source"]
        if source.exists():
            mapping[fields["target"]] = source
    return mapping


def _resolve_script(token: str, root: Path, mappings: dict[str, Path]) -> Path | None:
    """Resolve one invoked path only when its repository origin is deterministic."""
    candidate = token.strip("'\"")
    if candidate in mappings and mappings[candidate].is_file():
        return mappings[candidate]
    for target, source in mappings.items():
        prefix = target.rstrip("/") + "/"
        if candidate.startswith(prefix) and source.is_dir():
            resolved = source / candidate.removeprefix(prefix)
            if resolved.is_file():
                return resolved
    if candidate.startswith("./"):
        resolved = root / candidate.removeprefix("./")
        if resolved.is_file():
            return resolved
    if candidate.startswith("scripts/"):
        resolved = root / candidate
        if resolved.is_file():
            return resolved
    return None


def _invoked_scripts(root: Path, dockerfile: Path) -> set[Path]:
    """Find context-backed shell or Python scripts invoked by Docker RUN."""
    instructions = docker_instructions(dockerfile)
    copies = _copy_mapping(root, instructions)
    result: set[Path] = set()
    for instruction in instructions:
        mappings = copies | _mount_mapping(root, instruction)
        for tokens in run_commands(instruction, dockerfile):
            if not tokens:
                continue
            executable = executable_name(tokens[0])
            candidates: list[str] = []
            if executable in {"source", "."} and len(tokens) > 1:
                candidates.append(tokens[1])
            elif executable in {"bash", "sh", "dash", "python", "python3"}:
                index = 1
                while index < len(tokens) and tokens[index].startswith("-"):
                    if tokens[index] in {"-c", "-m"}:
                        break
                    index += 1
                if index < len(tokens) and tokens[index] not in {"-c", "-m"}:
                    candidates.append(tokens[index])
            else:
                candidates.append(tokens[0])
            for candidate in candidates:
                resolved = _resolve_script(candidate, root, mappings)
                if resolved is not None:
                    result.add(resolved)
                elif executable in {"bash", "sh", "dash", "python", "python3"} and candidate:
                    raise InventoryError(
                        f"build invokes a script whose context source cannot be resolved in {dockerfile}: {candidate}; "
                        "dynamic, generated and downloaded build helpers are unsupported"
                    )
                elif candidate.startswith(("./", "/")) and executable_name(candidate).endswith((".sh", ".py")):
                    raise InventoryError(
                        f"build invokes an unresolved helper in {dockerfile}: {candidate}; "
                        "dynamic, generated and downloaded build helpers are unsupported"
                    )
    return result


def _command_segments(text: str) -> list[list[str]]:
    """Tokenize simple command segments; ambiguous shell syntax remains non-executable text."""
    logical = text.replace("\\\n", " ")
    result: list[list[str]] = []
    for raw_line in logical.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
            lexer.whitespace_split = True
            lexer.commenters = "#"
            groups: list[list[str]] = [[]]
            for token in lexer:
                if token and all(character in ";&|" for character in token):
                    if groups[-1]:
                        groups.append([])
                else:
                    groups[-1].append(token)
        except ValueError:
            continue
        for tokens in groups:
            while tokens and (
                tokens[0] in {"if", "then", "do", "else", "!", "command", "exec", "{", "}"}
                or "=" in tokens[0]
            ):
                tokens.pop(0)
            if tokens:
                result.append(tokens)
    return result


def _acquisition_reason(tokens: list[str]) -> str | None:
    """Describe a prohibited acquisition command, including interpreter-based fetches."""
    executable = executable_name(tokens[0])
    if executable in {"curl", "wget"}:
        return executable
    if executable == "busybox" and len(tokens) > 1 and tokens[1] == "wget":
        return "busybox wget"
    if executable == "git" and "clone" in tokens[1:]:
        return "git clone"
    if executable in {"apt", "apt-get"} and "install" in tokens[1:]:
        return f"{executable} install"
    if executable in {"pip", "pip3"} and "install" in tokens[1:]:
        return f"{executable} install"
    if executable.startswith("python"):
        module: str | None = None
        code: str | None = None
        for index, token in enumerate(tokens[1:], 1):
            if token == "-m" or (token.startswith("-") and not token.startswith("--") and token.endswith("m")):
                module = tokens[index + 1] if index + 1 < len(tokens) else None
            elif token.startswith("-m") and len(token) > 2:
                module = token[2:]
            if token == "-c" or (token.startswith("-") and not token.startswith("--") and token.endswith("c")):
                code = tokens[index + 1] if index + 1 < len(tokens) else ""
            elif token.startswith("-c") and len(token) > 2:
                code = token[2:]
        if module == "pip" and "install" in tokens:
            return "python -m pip install"
        if code is not None and PYTHON_NETWORK_RE.search(code):
            return "Python inline network acquisition"
    if executable == "node" and any(option in tokens for option in {"-e", "--eval"}):
        option = "-e" if "-e" in tokens else "--eval"
        code = tokens[tokens.index(option) + 1] if tokens.index(option) + 1 < len(tokens) else ""
        if NODE_NETWORK_RE.search(code):
            return "Node.js inline network acquisition"
    if executable == "uv" and "install" in tokens[1:]:
        return "uv install"
    if executable == "npm":
        allowed_queries = {"--help", "-h", "--version", "-v", "config", "get", "prefix", "root"}
        command = next((token for token in tokens[1:] if not token.startswith("-")), None)
        if command not in allowed_queries and not any(option in tokens[1:] for option in {"--help", "-h", "--version", "-v"}):
            return "npm command (package acquisition from build helpers is unsupported)"
    if executable in {"cargo", "go", "gem"} and "install" in tokens[1:]:
        return f"{executable} install"
    if executable == "composer" and len(tokens) > 2 and tokens[1:3] == ["global", "require"]:
        return "composer global require"
    return None


def _python_acquisition_reason(text: str) -> str | None:
    """Detect executed Python network APIs without matching inert fixture strings."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise InventoryError("cannot parse Python build helper for acquisition policy") from exc
    network_calls = {
        "urlopen",
        "urlretrieve",
        "urllib.request.urlopen",
        "urllib.request.urlretrieve",
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.request",
        "http.client.HTTPConnection",
        "http.client.HTTPSConnection",
    }
    import_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                local_name = imported.asname or imported.name.split(".")[0]
                import_aliases[local_name] = imported.name if imported.asname else local_name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for imported in node.names:
                if imported.name == "*":
                    raise InventoryError("wildcard imports are unsupported in Python build helpers")
                import_aliases[imported.asname or imported.name] = f"{node.module}.{imported.name}"

    def call_name(node: ast.AST) -> str:
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        name = ".".join(reversed(parts))
        head, separator, tail = name.partition(".")
        if head in import_aliases:
            return import_aliases[head] + (separator + tail if separator else "")
        return name

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and call_name(node.func) in network_calls:
            return call_name(node.func)
    return None


def validate_build_scripts(root: Path, dockerfiles: list[Path]) -> None:
    """Reject acquisition from context scripts reached by managed Docker builds."""
    pending: list[Path] = []
    for dockerfile in dockerfiles:
        pending.extend(_invoked_scripts(root, dockerfile))
    checked: set[Path] = set()
    while pending:
        script = pending.pop()
        if script in checked:
            continue
        checked.add(script)
        text = script.read_text(encoding="utf-8")
        if script.suffix == ".py":
            reason = _python_acquisition_reason(text)
            if reason is not None:
                raise InventoryError(
                    f"build helper {script.relative_to(root)} performs {reason}; "
                    "declare acquisition directly in the Dockerfile so legal inventory ownership can be verified"
                )
            continue
        for tokens in _command_segments(text):
            reason = _acquisition_reason(tokens)
            if reason is not None:
                raise InventoryError(
                    f"build helper {script.relative_to(root)} performs {reason}; "
                    "declare acquisition directly in the Dockerfile so legal inventory ownership can be verified"
                )
        for match in SCRIPT_REFERENCE_RE.finditer(text):
            referenced = root / match.group(1)
            if referenced.is_file():
                pending.append(referenced)
