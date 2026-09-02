from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import AppConfig
from .job_options import (
    JobOptions,
    apply_job_options,
    read_job_options,
    remove_job_options,
)
from .pdf_engine import PdfTranslationEngine, atomic_translate
from .state import JobStore
from .translation import create_translator

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessResult:
    status: str
    source: Path
    output: Path | None
    archived: Path | None
    message: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str, fallback: str = "document") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
    if not cleaned or cleaned.split(".", 1)[0].upper() in reserved:
        return fallback
    return cleaned[:160]


def _unique_destination(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for number in range(1, 10_000):
        candidate = directory / f"{stem}.{number}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate a unique destination for {filename}")


class TranslationPipeline:
    def __init__(self, config: AppConfig):
        self.config = config
        config.ensure_directories()
        self.store = JobStore(config.paths.state / "jobs.sqlite3")
        self.engine = PdfTranslationEngine(
            config,
            create_translator(config.translation, config.document_analysis),
        )
        self._engines: dict[tuple[str, bool], PdfTranslationEngine] = {
            (
                config.translation.thinking_mode,
                config.document_analysis.enabled,
            ): self.engine
        }
        self._engines_lock = threading.Lock()
        self._hash_locks: dict[str, threading.Lock] = {}
        self._hash_locks_guard = threading.Lock()

    def process(self, source: Path) -> ProcessResult:
        source = source.resolve()
        if not source.is_file():
            return ProcessResult("skipped", source, None, None, "File no longer exists")
        if source.suffix.lower() != ".pdf":
            return ProcessResult("skipped", source, None, None, "Not a PDF")
        source_hash = sha256_file(source)
        LOG.info(
            "Job accepted: %s (%s); translation model=%s",
            source.name,
            source_hash[:12],
            self.config.translation.model,
        )
        with self._hash_locks_guard:
            hash_lock = self._hash_locks.setdefault(source_hash, threading.Lock())
        with hash_lock:
            return self._process_hashed(source, source_hash)

    def _process_hashed(self, source: Path, source_hash: str) -> ProcessResult:
        defaults = JobOptions.from_config(self.config)
        try:
            job_options = read_job_options(source, defaults)
        except Exception:
            LOG.exception(
                "Could not read per-job options for %s; using config defaults",
                source.name,
            )
            job_options = defaults
        effective_config = apply_job_options(self.config, job_options)
        try:
            return self._process_hashed_with_options(
                source,
                source_hash,
                effective_config,
                job_options,
            )
        finally:
            remove_job_options(source)

    def _process_hashed_with_options(
        self,
        source: Path,
        source_hash: str,
        effective_config: AppConfig,
        job_options: JobOptions,
    ) -> ProcessResult:
        job_id = self.store.start(source, source_hash)
        LOG.info(
            "Job settings for %s: thinking_mode=%s; document_analysis=%s; source=%s",
            source.name,
            job_options.thinking_mode,
            "enabled" if job_options.document_analysis_enabled else "disabled",
            job_options.source,
        )
        previous = self.store.find_completed(source_hash)
        if previous and previous.output_path.is_file():
            archived = self._archive(source, duplicate=True)
            self.store.finish_duplicate(job_id, previous.id, previous.output_path, archived)
            message = f"Duplicate content; reused {previous.output_path.name}"
            LOG.info("%s: %s", source.name, message)
            return ProcessResult("duplicate", source, previous.output_path, archived, message)

        output = self._output_path(source, source_hash)
        started_at = datetime.now(UTC)
        try:
            LOG.info("Processing started: %s", source)
            metrics = atomic_translate(
                self._engine_for(effective_config),
                source=source,
                output=output,
                state_dir=self.config.paths.state,
            )
            LOG.info("Archiving original source: %s", source.name)
            archived = self._archive(source, duplicate=False)
            LOG.info("Original source archived: %s", archived)
            finished_at = datetime.now(UTC)
            manifest = {
                "schema_version": 2,
                "status": "completed",
                "source_filename": source.name,
                "source_sha256": source_hash,
                "archived_source": str(archived),
                "translated_pdf": str(output),
                "source_language": self.config.translation.source_language,
                "target_language": self.config.translation.target_language,
                "translation_backend": self.config.translation.backend,
                "translation_model": effective_config.translation.model,
                "thinking_mode": effective_config.translation.thinking_mode,
                "document_analysis_enabled": (
                    effective_config.document_analysis.enabled
                ),
                "job_options": job_options.as_dict(),
                "document_analysis": metrics.get("document_analysis"),
                "ocr_enabled": self.config.ocr.enabled,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "elapsed_seconds": round((finished_at - started_at).total_seconds(), 3),
                "metrics": metrics,
            }
            LOG.info("Recording completed job in state database")
            self.store.finish(job_id, output, archived, metrics)
            if self.config.archive.write_manifest:
                manifest_path = output.with_suffix(".manifest.json")
                try:
                    LOG.info("Writing translation manifest: %s", manifest_path.name)
                    self._write_json_atomic(manifest_path, manifest)
                    LOG.info("Translation manifest saved: %s", manifest_path)
                except Exception:
                    LOG.exception("Could not write optional manifest %s", manifest_path)
            LOG.info(
                "Completed %s -> %s in %.1fs",
                source.name,
                output.name,
                (finished_at - started_at).total_seconds(),
            )
            return ProcessResult("completed", source, output, archived, "Translation completed")
        except Exception as exc:
            error_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            failed_path: Path | None = None
            try:
                if source.exists():
                    failed_path = self._move_failed(source)
                    self._write_json_atomic(
                        failed_path.with_suffix(".error.json"),
                        {
                            "status": "failed",
                            "source_filename": source.name,
                            "source_sha256": source_hash,
                            "job_options": job_options.as_dict(),
                            "failed_at": datetime.now(UTC).isoformat(),
                            "error": str(exc),
                            "traceback": error_text,
                        },
                    )
            except Exception:
                LOG.exception("Could not move failed input %s", source)
            self.store.fail(job_id, error_text, failed_path)
            LOG.exception("Failed to process %s", source)
            return ProcessResult("failed", source, None, failed_path, str(exc))

    def _engine_for(self, effective_config: AppConfig) -> PdfTranslationEngine:
        key = (
            effective_config.translation.thinking_mode,
            effective_config.document_analysis.enabled,
        )
        with self._engines_lock:
            engine = self._engines.get(key)
            if engine is None:
                engine = PdfTranslationEngine(
                    effective_config,
                    create_translator(
                        effective_config.translation,
                        effective_config.document_analysis,
                    ),
                )
                self._engines[key] = engine
            return engine

    def _output_path(self, source: Path, source_hash: str) -> Path:
        language = _safe_component(self.config.translation.target_language.lower().replace(" ", "-"))
        stem = _safe_component(source.stem)
        filename = f"{stem}.{language}.{source_hash[:8]}.pdf"
        return self.config.paths.translated / filename

    def _dated_directory(self, root: Path) -> Path:
        now = datetime.now()
        return root / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}" if self.config.archive.date_folders else root

    def _archive(self, source: Path, duplicate: bool) -> Path:
        root = self.config.paths.archive / "duplicates" if duplicate else self.config.paths.archive
        directory = self._dated_directory(root)
        if self.config.archive.keep_original_filename:
            name = _safe_component(source.name)
        else:
            name = f"{datetime.now():%H%M%S}-{_safe_component(source.name)}"
        destination = _unique_destination(directory, name)
        return Path(shutil.move(str(source), str(destination))).resolve()

    def _move_failed(self, source: Path) -> Path:
        directory = self._dated_directory(self.config.paths.failed)
        destination = _unique_destination(directory, _safe_component(source.name))
        return Path(shutil.move(str(source), str(destination))).resolve()

    @staticmethod
    def _write_json_atomic(path: Path, data: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
        try:
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
