import json

from scripts.export_openapi import SPEC_PATH, build_spec


def test_committed_openapi_spec_matches_app() -> None:
    spec = build_spec()
    committed = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert committed == spec
