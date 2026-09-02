import json
from pathlib import Path
from shutil import copy2

import pymupdf

from pdf_translation_workflow.config import load_config
from pdf_translation_workflow.job_options import (
    JobOptions,
    job_options_path,
    write_job_options_atomic,
)
from pdf_translation_workflow.models import TextRegion
from pdf_translation_workflow.pdf_engine import PdfTranslationEngine, atomic_translate
from pdf_translation_workflow.pipeline import TranslationPipeline
from pdf_translation_workflow.translation import Translator


def _write_config(path: Path) -> Path:
    value = path / "config.toml"
    value.write_text(
        """
[paths]
source = "source"
translated = "translated"
archive = "archive"
failed = "failed"
state = ".state"
[translation]
backend = "echo"
target_language = "test"
[ocr]
enabled = false
[archive]
write_manifest = true
""",
        encoding="utf-8",
    )
    return value


def _write_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((30, 60), "A short test paragraph", fontsize=12)
    document.save(path)
    document.close()


def test_pipeline_writes_output_then_archives_and_deduplicates(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path))
    config.ensure_directories()
    source = config.paths.source / "sample.pdf"
    _write_pdf(source)
    pipeline = TranslationPipeline(config)

    first = pipeline.process(source)
    assert first.status == "completed"
    assert first.output and first.output.is_file()
    assert first.archived and first.archived.is_file()
    assert first.output.with_suffix(".manifest.json").is_file()
    manifest = json.loads(
        first.output.with_suffix(".manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == 2
    assert manifest["thinking_mode"] == "disabled"
    assert manifest["document_analysis"] is None
    translated_document = pymupdf.open(first.output)
    assert translated_document.page_count == 1
    translated_document.close()

    duplicate = config.paths.source / "same-content.pdf"
    copy2(first.archived, duplicate)
    second = pipeline.process(duplicate)
    assert second.status == "duplicate"
    assert second.output == first.output
    assert second.archived and "duplicates" in second.archived.parts

    # SQLite connections must be closed promptly on Windows, not left to garbage collection.
    database = config.paths.state / "jobs.sqlite3"
    moved_database = database.with_name("jobs-moved.sqlite3")
    database.replace(moved_database)
    assert moved_database.is_file()


def test_default_layout_embeds_searchable_chinese_text(tmp_path: Path) -> None:
    class ChineseTranslator(Translator):
        def translate_regions(self, regions: list[TextRegion]) -> None:
            for region in regions:
                region.translated_text = "中文翻译测试：人体解剖与生理学"

    config = load_config(_write_config(tmp_path))
    source = tmp_path / "chinese-source.pdf"
    output = tmp_path / "chinese-output.pdf"
    _write_pdf(source)
    metrics = atomic_translate(
        PdfTranslationEngine(config, ChineseTranslator()),
        source,
        output,
        tmp_path / ".atomic-state",
    )
    document = pymupdf.open(output)
    extracted = document[0].get_text()
    document.close()
    assert metrics["pdf_text_regions"] == 1
    assert "中文翻译测试" in extracted


def test_pipeline_applies_and_records_per_job_gui_options(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path))
    config.ensure_directories()
    source = config.paths.source / "custom-options.pdf"
    _write_pdf(source)
    write_job_options_atomic(
        source,
        JobOptions(
            thinking_mode="enabled",
            document_analysis_enabled=False,
            source="gui",
        ),
    )

    result = TranslationPipeline(config).process(source)

    assert result.status == "completed"
    assert result.output
    manifest = json.loads(
        result.output.with_suffix(".manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["thinking_mode"] == "enabled"
    assert manifest["document_analysis_enabled"] is False
    assert manifest["job_options"] == {
        "thinking_mode": "enabled",
        "document_analysis_enabled": False,
        "source": "gui",
    }
    assert not job_options_path(source).exists()
