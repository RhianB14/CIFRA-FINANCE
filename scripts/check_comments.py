import ast
import io
import subprocess
import sys
import tokenize
from pathlib import Path

PYTHON_SUFFIXES = {".py"}
SLASH_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".css"}
HASH_SUFFIXES = {".yaml", ".yml"}
HTML_SUFFIXES = {".html", ".htm"}
SQL_SUFFIXES = {".sql"}
CONFIG_NAMES = {"Dockerfile"}
SKIPPED_NAMES = {"next-env.d.ts"}


def tracked_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout.decode()
    return [Path(item) for item in output.split("\0") if item]


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


def marker_violations(text: str, markers: tuple[str, ...]) -> list[int]:
    return [
        number
        for number, line in enumerate(text.splitlines(), 1)
        if any(marker in line for marker in markers)
    ]


def violations(path: Path) -> list[int]:
    if path.name in SKIPPED_NAMES or not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if path.suffix in PYTHON_SUFFIXES:
        return python_violations(path, text)
    if path.suffix in SLASH_SUFFIXES:
        return slash_violations(text)
    if path.suffix in HASH_SUFFIXES or path.name in CONFIG_NAMES:
        return hash_violations(text)
    if path.suffix in HTML_SUFFIXES:
        return marker_violations(text, ("<!--", "-->"))
    if path.suffix in SQL_SUFFIXES:
        return marker_violations(text, ("--", "/*", "*/"))
    return []


def relevant(path: Path) -> bool:
    return (
        path.suffix in PYTHON_SUFFIXES | SLASH_SUFFIXES | HASH_SUFFIXES | HTML_SUFFIXES | SQL_SUFFIXES
        or path.name in CONFIG_NAMES
    )


def main() -> int:
    paths = [Path(item) for item in sys.argv[1:]] if len(sys.argv) > 1 else tracked_files()
    findings = [(path, violations(path)) for path in paths if relevant(path)]
    failed = False
    for path, lines in findings:
        for line in lines:
            print(f"{path}:{line}: forbidden comment or docstring")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
