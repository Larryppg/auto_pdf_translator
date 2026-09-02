import threading
import time
from pathlib import Path

import pymupdf

from pdf_translation_workflow.config import load_config
from pdf_translation_workflow.pipeline import TranslationPipeline
from pdf_translation_workflow.watcher import FolderWatcher


def test_new_source_pdf_is_processed_automatically(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
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
[watch]
stable_seconds = 0.2
poll_seconds = 0.05
worker_count = 1
startup_scan = true
[archive]
write_manifest = true
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    pipeline = TranslationPipeline(config)
    watcher = FolderWatcher(config, pipeline)
    thread = threading.Thread(target=watcher.run, name="watcher-test")
    thread.start()
    try:
        source = config.paths.source / "arrived.pdf"
        document = pymupdf.open()
        page = document.new_page(width=300, height=200)
        page.insert_text((30, 60), "Automatically detected", fontsize=12)
        document.save(source)
        document.close()

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if list(config.paths.translated.glob("*.pdf")):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("Watcher did not produce a translated PDF within 10 seconds")
    finally:
        watcher.stop()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert len(list(config.paths.translated.glob("*.pdf"))) == 1
    assert len(list(config.paths.archive.rglob("arrived.pdf"))) == 1
    assert not source.exists()
