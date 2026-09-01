import yaml

from scripts.export_openapi import SPEC_PATH, build_spec, dumps_spec


def test_committed_openapi_yaml_matches_app() -> None:
    spec = build_spec()
    committed = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    assert committed == spec


def test_spec_dump_is_deterministic() -> None:
    spec = build_spec()
    assert dumps_spec(spec) == dumps_spec(spec)
    assert "openapi" in dumps_spec(spec)
