"""Fail-closed policy for repository scripts executed during image builds."""
from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

from .docker_parse import docker_instructions, executable_name, instruction_payload, run_commands, short_option_value
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
        if source.is_file() and (source.parent.name == "scripts" or source.suffix in {".sh", ".py"}):
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
                    has_module, attached_module = short_option_value(tokens[index], "m")
                    if executable in {"python", "python3"} and has_module:
                        module = attached_module if attached_module is not None else (
                            tokens[index + 1] if index + 1 < len(tokens) else ""
                        )
                        if module != "pip":
                            raise InventoryError(
                                f"Python -m build helpers are unsupported in {dockerfile}; "
                                "invoke a deterministic context-backed script path instead"
                            )
                    if short_option_value(tokens[index], "c")[0] or short_option_value(tokens[index], "m")[0]:
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
    if executable == "git" and any(command in tokens[1:] for command in {"clone", "fetch", "pull"}):
        return "git acquisition"
    if executable in {"apt", "apt-get"} and "install" in tokens[1:]:
        return f"{executable} install"
    if executable in {"pip", "pip3"} and "install" in tokens[1:]:
        return f"{executable} install"
    if executable.startswith("python"):
        module: str | None = None
        code: str | None = None
        for index, token in enumerate(tokens[1:], 1):
            has_module, attached_module = short_option_value(token, "m")
            has_code, attached_code = short_option_value(token, "c")
            if has_module:
                module = attached_module if attached_module is not None else (tokens[index + 1] if index + 1 < len(tokens) else None)
            if has_code:
                code = attached_code if attached_code is not None else (tokens[index + 1] if index + 1 < len(tokens) else "")
        if module == "pip" and "install" in tokens:
            return "python -m pip install"
        if code is not None and PYTHON_NETWORK_RE.search(code):
            return "Python inline network acquisition"
    if executable == "node" and any(option in tokens for option in {"-e", "--eval", "-p", "--print"}):
        option = next(option for option in {"-e", "--eval", "-p", "--print"} if option in tokens)
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


def _python_acquisition_reason(text: str, *, allow_test_processes: bool = False) -> str | None:
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
    process_calls = {
        "os.popen",
        "os.system",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
        "subprocess.run",
    }
    import_aliases: dict[str, str] = {}
    imports_requests = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                imports_requests = imports_requests or imported.name == "requests"
                local_name = imported.asname or imported.name.split(".")[0]
                import_aliases[local_name] = imported.name if imported.asname else local_name
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports_requests = imports_requests or node.module == "requests"
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
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node.func)
        if name in network_calls:
            return name
        if imports_requests and isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "post", "put", "request"}:
            return f"requests client method {node.func.attr}"
        if not allow_test_processes and (name in process_calls or name.startswith(("os.exec", "os.spawn"))):
            return f"process-spawning API {name}"
    return None


def _heredoc_acquisition_reason(text: str) -> str | None:
    """Inspect interpreter heredoc bodies rather than treating them as shell text."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.search(r"\b(python3?|node|bash|sh|dash)\b[^#\n]*<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)", line)
        if match is None:
            continue
        interpreter, delimiter = match.groups()
        body: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate.strip() == delimiter:
                break
            body.append(candidate)
        else:
            return "unterminated interpreter heredoc"
        source = "\n".join(body)
        if interpreter.startswith("python"):
            reason = _python_acquisition_reason(source)
            if reason is not None:
                return f"Python heredoc {reason}"
        elif interpreter == "node" and NODE_NETWORK_RE.search(source):
            return "Node.js heredoc network acquisition"
        else:
            for tokens in _command_segments(source):
                reason = _acquisition_reason(tokens)
                if reason is not None:
                    return f"shell heredoc {reason}"
    return None


def validate_build_scripts(root: Path, dockerfiles: list[Path]) -> None:
    """Reject acquisition from context scripts reached by managed Docker builds."""
    pending: list[Path] = []
    copied_helpers: dict[str, Path] = {}
    for dockerfile in dockerfiles:
        pending.extend(_invoked_scripts(root, dockerfile))
        copied_helpers.update(_copy_mapping(root, docker_instructions(dockerfile)))
    checked: set[Path] = set()
    while pending:
        script = pending.pop()
        if script in checked:
            continue
        checked.add(script)
        text = script.read_text(encoding="utf-8")
        heredoc_reason = None if script.name.startswith("test-") else _heredoc_acquisition_reason(text)
        if heredoc_reason is not None:
            raise InventoryError(
                f"build helper {script.relative_to(root)} performs {heredoc_reason}; "
                "declare acquisition directly in the Dockerfile so legal inventory ownership can be verified"
            )
        if script.suffix == ".py":
            reason = _python_acquisition_reason(text, allow_test_processes=script.name.startswith("test-"))
            if reason is not None:
                raise InventoryError(
                    f"build helper {script.relative_to(root)} performs {reason}; "
                    "declare acquisition directly in the Dockerfile so legal inventory ownership can be verified"
                )
            tree = ast.parse(text)
            for node in ast.walk(tree):
                names = [item.name for item in node.names] if isinstance(node, ast.Import) else []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    relative = Path(*name.split(".")).with_suffix(".py")
                    for base in (script.parent, root / "scripts"):
                        referenced = base / relative
                        if referenced.is_file():
                            pending.append(referenced)
            continue
        for substitution in re.findall(r"\$\(([^()]*)\)", text, re.DOTALL):
            for tokens in _command_segments(substitution):
                reason = _acquisition_reason(tokens)
                if reason is not None:
                    raise InventoryError(
                        f"build helper {script.relative_to(root)} performs command substitution {reason}; "
                        "declare acquisition directly in the Dockerfile so legal inventory ownership can be verified"
                    )
        for tokens in _command_segments(text):
            reason = _acquisition_reason(tokens)
            if reason is not None:
                raise InventoryError(
                    f"build helper {script.relative_to(root)} performs {reason}; "
                    "declare acquisition directly in the Dockerfile so legal inventory ownership can be verified"
                )
            executable = executable_name(tokens[0])
            candidate = tokens[1] if executable in {"source", ".", "bash", "sh", "dash", "python", "python3"} and len(tokens) > 1 else tokens[0]
            referenced = _resolve_script(candidate, root, copied_helpers)
            if referenced is not None:
                pending.append(referenced)
        for match in SCRIPT_REFERENCE_RE.finditer(text):
            referenced = root / match.group(1)
            if referenced.is_file():
                pending.append(referenced)
