from pathlib import Path

import pytest

from pdf_translation_workflow.config import load_config
from pdf_translation_workflow.job_options import (
    JobOptions,
    apply_job_options,
    read_job_options,
    write_job_options_atomic,
)


@pytest.mark.parametrize(
    ("thinking_mode", "analysis_enabled"),
    [
        ("disabled", False),
        ("disabled", True),
        ("enabled", False),
        ("enabled", True),
    ],
)
def test_all_gui_switch_combinations_round_trip_and_apply(
    tmp_path: Path,
    thinking_mode: str,
    analysis_enabled: bool,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[translation]\nbackend='echo'\nthinking_mode='disabled'\n"
        "[document_analysis]\nenabled=true\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    pdf = tmp_path / "queued.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    selected = JobOptions(
        thinking_mode=thinking_mode,
        document_analysis_enabled=analysis_enabled,
        source="gui",
    )
    write_job_options_atomic(pdf, selected)

    loaded = read_job_options(pdf, JobOptions.from_config(config))
    effective = apply_job_options(config, loaded)

    assert loaded.thinking_mode == thinking_mode
    assert loaded.document_analysis_enabled is analysis_enabled
    assert effective.translation.thinking_mode == thinking_mode
    assert effective.document_analysis.enabled is analysis_enabled
