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


def dumps_spec(spec: dict[str, object]) -> str:
    return yaml.safe_dump(spec, sort_keys=True, default_flow_style=False, allow_unicode=True)


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
