from pathlib import Path

from pdf_translation_workflow.config import load_config


def test_relative_paths_are_resolved_from_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[paths]
source = "incoming"
translated = "out"
archive = "archive"
failed = "failed"
state = ".state"
[translation]
backend = "echo"
[ocr]
enabled = false
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.paths.source == (tmp_path / "incoming").resolve()
    assert config.paths.translated == (tmp_path / "out").resolve()
    assert config.translation.backend == "echo"
    assert config.translation.thinking_mode == "disabled"
    assert config.document_analysis.enabled
    assert not config.ocr.enabled


def test_environment_file_does_not_override_existing_value(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "from-environment")
    (tmp_path / ".env").write_text("OPENAI_MODEL=from-file\n", encoding="utf-8")
    (tmp_path / "config.toml").write_text(
        "[translation]\nbackend='echo'\nmodel='from-config'\n", encoding="utf-8"
    )
    config = load_config(tmp_path / "config.toml")
    assert config.translation.model == "from-environment"
