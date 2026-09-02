import sys
from pathlib import Path

import yaml

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parent.parent
SPEC_PATH = REPO_ROOT / "docs" / "api" / "openapi.yaml"
sys.path.insert(0, str(API_ROOT))


def build_spec() -> dict[str, object]:
    from app.main import app

    return app.openapi()


def _quote_hash_leading_values(yaml_text: str) -> str:
    out: list[str] = []
    for line in yaml_text.splitlines():
        stripped = line.lstrip()
        if ": " in stripped:
            key, _, value = stripped.partition(": ")
            has_ref = "$ref" in key
            if not has_ref and "#" in value and not (value.startswith('"') and value.endswith('"')):
                prefix = line[: len(line) - len(stripped)]
                escaped = value.replace('"', '\\"')
                out.append(f'{prefix}{key}: "{escaped}"')
                continue
        out.append(line)
    return "\n".join(out)


def dumps_spec(spec: dict[str, object]) -> str:
    raw = yaml.safe_dump(spec, sort_keys=True, default_flow_style=False, allow_unicode=True)
    return _quote_hash_leading_values(raw) + "\n"


def main() -> int:
    spec = build_spec()
    if "--check" in sys.argv:
        if not SPEC_PATH.exists():
            print(f"missing {SPEC_PATH}", file=sys.stderr)
            return 1
        committed = SPEC_PATH.read_text(encoding="utf-8")
        if committed != dumps_spec(spec):
            print(
                "docs/api/openapi.yaml is out of date;"
                " run pnpm --filter @cifra/api openapi:export and commit",
                file=sys.stderr,
            )
            return 1
        print("docs/api/openapi.yaml is up to date")
        return 0
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(dumps_spec(spec), encoding="utf-8")
    print(f"wrote {SPEC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
