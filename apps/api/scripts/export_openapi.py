import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = API_ROOT / "docs" / "openapi.json"
sys.path.insert(0, str(API_ROOT))


def build_spec() -> dict[str, object]:
    from app.main import app

    return app.openapi()


def main() -> int:
    spec = build_spec()
    if "--check" in sys.argv:
        if not SPEC_PATH.exists():
            print(f"missing {SPEC_PATH}", file=sys.stderr)
            return 1
        committed = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        if committed != spec:
            print(
                "openapi.json is out of date; run scripts/export_openapi.py and commit",
                file=sys.stderr,
            )
            return 1
        print("openapi.json is up to date")
        return 0
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(json.dumps(spec, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {SPEC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
