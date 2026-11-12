from pathlib import Path

from mobilerun.config_manager.config_manager import AgentConfig, MobileConfig
from mobilerun.config_manager.loader import ConfigLoader


def test_load_prefers_project_config_over_user_config(monkeypatch, tmp_path: Path):
    project_config = tmp_path / "config.yaml"
    project_config.write_text("_version: 7\nagent:\n  max_steps: 11\n")

    user_config = tmp_path / "user-config.yaml"
    user_config.write_text("_version: 7\nagent:\n  max_steps: 22\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ConfigLoader, "get_user_config_path", lambda: user_config)

    config = ConfigLoader.load()

    assert config.agent.max_steps == 11


def test_explicit_config_still_overrides_project_config(monkeypatch, tmp_path: Path):
    project_config = tmp_path / "config.yaml"
    project_config.write_text("_version: 7\nagent:\n  max_steps: 11\n")

    explicit_config = tmp_path / "explicit.yaml"
    explicit_config.write_text("_version: 7\nagent:\n  max_steps: 33\n")

    monkeypatch.chdir(tmp_path)

    config = ConfigLoader.load(str(explicit_config))

    assert config.agent.max_steps == 33


def test_save_uses_project_config_scope(monkeypatch, tmp_path: Path):
    project_config = tmp_path / "config.yaml"
    project_config.write_text("_version: 7\nagent:\n  max_steps: 11\n")

    monkeypatch.chdir(tmp_path)

    saved_path = ConfigLoader.save(MobileConfig(agent=AgentConfig(max_steps=44)))

    assert saved_path == project_config
    assert ConfigLoader.load().agent.max_steps == 44
