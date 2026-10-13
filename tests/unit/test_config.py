import pytest
import yaml
from pydantic import ValidationError

from career_agent.core.config import Settings, load_yaml


def test_defaults_fail_closed():
    settings = Settings()
    assert not settings.automation.enabled
    assert settings.automation.dry_run
    assert settings.automation.kill_switch
    assert sum(settings.matching.weights.model_dump().values()) == 100


@pytest.mark.parametrize(
    "automation",
    [
        {"enabled": True},
        {"dry_run": False},
        {"daily_application_limit": 11},
        {"max_per_company_per_day": 2},
        {"enabled": "false"},
    ],
)
def test_unsafe_settings_rejected(automation):
    with pytest.raises(ValidationError):
        Settings.model_validate({"automation": automation}, strict=True)


@pytest.mark.parametrize(
    "config",
    [
        {"matching": {"weights": {"stem_relevance": 40}}},
        {"matching": {"minimum_auto_apply_score": 79}},
        {"matching": {"minimum_review_score": 90}},
        {"project": {"timezone": "Invalid/Zone"}},
        {"unexpected_setting": True},
    ],
)
def test_invalid_settings_rejected(config):
    with pytest.raises(ValidationError):
        Settings.model_validate(config)


def test_yaml_cannot_execute_code(tmp_path):
    p = tmp_path / "malicious.yaml"
    p.write_text("!!python/object/apply:os.system ['echo unsafe']")
    with pytest.raises(yaml.YAMLError):
        load_yaml(p)


def test_yaml_mapping_and_size_required(tmp_path):
    p = tmp_path / "invalid.yaml"
    p.write_text("[1, 2]")
    with pytest.raises(ValueError):
        load_yaml(p)
    p.write_text("a" * 1_000_001)
    with pytest.raises(ValueError):
        load_yaml(p)
