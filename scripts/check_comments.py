import ast
import io
import subprocess
import sys
import tokenize
from pathlib import Path

PYTHON_SUFFIXES = {".py"}
SLASH_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".css"}
HASH_SUFFIXES = {".yaml", ".yml"}
TOML_SUFFIXES = {".toml", ".lock"}
INI_SUFFIXES = {".ini", ".cfg", ".conf"}
MARKUP_SUFFIXES = {".html", ".htm", ".xml", ".svg"}
SQL_SUFFIXES = {".sql"}
EXEMPT_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".json", ".csv"}
HASH_NAMES = {
    "Dockerfile",
    ".gitignore",
    ".dockerignore",
    ".prettierignore",
    ".eslintignore",
    ".npmignore",
    ".gitattributes",
    ".env.example",
    ".htaccess",
    ".trivyignore",
}
INI_NAMES = {".editorconfig", ".npmrc", ".flake8"}
SKIPPED_NAMES = {"next-env.d.ts"}


def tracked_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout.decode()
    return [Path(item) for item in output.split("\0") if item]


def classify(path: Path) -> str:
    if path.name in SKIPPED_NAMES:
        return "exempt"
    if path.name in INI_NAMES:
        return "ini"
    if path.name in HASH_NAMES or path.name.startswith(".trivyignore"):
        return "hash"
    suffix = path.suffix
    if suffix in PYTHON_SUFFIXES:
        return "python"
    if suffix in SLASH_SUFFIXES:
        return "slash"
    if suffix in HASH_SUFFIXES:
        return "hash"
    if suffix in TOML_SUFFIXES:
        return "toml"
    if suffix in INI_SUFFIXES:
        return "ini"
    if suffix in MARKUP_SUFFIXES:
        return "markup"
    if suffix in SQL_SUFFIXES:
        return "sql"
    if suffix in EXEMPT_SUFFIXES:
        return "exempt"
    try:
        path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        return "binary"
    return "unknown"


def python_violations(path: Path, text: str) -> list[int]:
    lines = {
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT and not (token.start[0] == 1 and token.string.startswith("#!"))
    }
    tree = ast.parse(text, filename=str(path))
    nodes = [tree, *ast.walk(tree)]
    for node in nodes:
        body = getattr(node, "body", None)
        if body and isinstance(body, list):
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                if isinstance(first.value.value, str):
                    lines.add(first.lineno)
    return sorted(lines)


def slash_violations(text: str) -> list[int]:
    lines: list[int] = []
    index = 0
    line = 1
    quote = ""
    escaped = False
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if char == "\n":
            line += 1
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            continue
        if char == "/" and following == "/":
            lines.append(line)
            newline = text.find("\n", index + 2)
            if newline == -1:
                break
            index = newline
            continue
        if char == "/" and following == "*":
            lines.append(line)
            ending = text.find("*/", index + 2)
            if ending == -1:
                break
            line += text[index:ending].count("\n")
            index = ending + 2
            continue
        index += 1
    return sorted(set(lines))


def hash_violations(text: str) -> list[int]:
    violations: list[int] = []
    for number, line in enumerate(text.splitlines(), 1):
        quote = ""
        escaped = False
        for char in line:
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
            elif char in {"'", '"'}:
                quote = char
            elif char == "#":
                violations.append(number)
                break
    return violations


def ini_violations(text: str) -> list[int]:
    violations: list[int] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(";") or hash_violations(line):
            violations.append(number)
    return violations


def marker_violations(text: str, markers: tuple[str, ...]) -> list[int]:
    return [
        number
        for number, line in enumerate(text.splitlines(), 1)
        if any(marker in line for marker in markers)
    ]


def violations(path: Path) -> list[int]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    kind = classify(path)
    if kind == "python":
        return python_violations(path, text)
    if kind == "slash":
        return slash_violations(text)
    if kind == "hash" or kind == "toml":
        return hash_violations(text)
    if kind == "ini":
        return ini_violations(text)
    if kind == "markup":
        return marker_violations(text, ("<!--", "-->"))
    if kind == "sql":
        return marker_violations(text, ("--", "/*", "*/"))
    return []


def main() -> int:
    arguments = sys.argv[1:]
    explicit = bool(arguments)
    paths = [Path(item) for item in arguments] if explicit else tracked_files()
    status = 0
    for path in paths:
        if not path.exists():
            print(f"{path}: file not found")
            raise SystemExit(2)
        kind = classify(path)
        if kind == "exempt":
            continue
        if kind == "binary":
            print(f"{path}: binary file, consciously not scanned for comments")
            continue
        if kind == "unknown":
            print(f"{path}: unknown format, refusing silent success")
            raise SystemExit(2)
        for line in violations(path):
            print(f"{path}:{line}: forbidden comment or docstring")
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
