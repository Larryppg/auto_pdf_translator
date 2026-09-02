from pathlib import Path

from pdf_translation_workflow.gui import _progress_from_log_line, _stage_pdf
from pdf_translation_workflow.job_options import (
    JobOptions,
    read_job_options,
)


def test_gui_staging_preserves_original_and_uses_unique_names(tmp_path: Path) -> None:
    original_directory = tmp_path / "outside"
    original_directory.mkdir()
    original = original_directory / "lecture.pdf"
    original.write_bytes(b"%PDF-1.4\noriginal")
    source = tmp_path / "source"

    selected_options = JobOptions(
        thinking_mode="enabled",
        document_analysis_enabled=False,
        source="gui",
    )
    first = _stage_pdf(original, source, selected_options)
    second = _stage_pdf(original, source)

    assert original.is_file()
    assert original.read_bytes() == b"%PDF-1.4\noriginal"
    assert first == source / "lecture.pdf"
    assert second == source / "lecture.gui-1.pdf"
    assert first.read_bytes() == original.read_bytes()
    assert second.read_bytes() == original.read_bytes()
    loaded_options = read_job_options(
        first,
        JobOptions("disabled", True),
    )
    assert loaded_options.thinking_mode == "enabled"
    assert not loaded_options.document_analysis_enabled
    assert loaded_options.source == "gui"


def test_gui_does_not_duplicate_a_pdf_already_in_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    existing = source / "already-queued.pdf"
    existing.write_bytes(b"%PDF-1.4\nqueued")

    assert _stage_pdf(existing, source) == existing.resolve()
    assert list(source.glob("*.pdf")) == [existing]


def test_gui_maps_workflow_logs_to_overall_progress() -> None:
    accepted = _progress_from_log_line(
        "2026-09-01 | INFO | Job accepted: lecture.pdf (abcdef123456); translation model=x"
    )
    translated = _progress_from_log_line(
        "Translation batch 2/4 completed in 5s: 50/100 regions (50.0%); ETA 5s"
    )
    layout = _progress_from_log_line("Layout page 5/10 (50.0%): 3 regions placed")
    completed = _progress_from_log_line(
        "Job result for lecture.pdf: completed - Translation completed"
    )

    assert accepted.job_name == "lecture.pdf"
    assert accepted.percent == 1
    assert translated.percent == 47.5
    assert "5s" in (translated.status or "")
    assert layout.percent == 80
    assert completed.job_name == "lecture.pdf"
    assert completed.percent == 100


def test_gui_and_backup_launchers_both_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    gui_launcher = root / "启动PDF翻译GUI.cmd"
    backup_launcher = root / "一键启动PDF翻译器.cmd"

    assert gui_launcher.is_file()
    assert "pdf_translation_workflow.gui" in gui_launcher.read_text(encoding="utf-8")
    assert backup_launcher.is_file()
    assert "start_watcher.ps1" in backup_launcher.read_text(encoding="utf-8")
