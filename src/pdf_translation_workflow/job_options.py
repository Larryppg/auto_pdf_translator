from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from .config import AppConfig


@dataclass(frozen=True)
class JobOptions:
    thinking_mode: str
    document_analysis_enabled: bool
    source: str = "config"

    @classmethod
    def from_config(cls, config: AppConfig) -> "JobOptions":
        return cls(
            thinking_mode=config.translation.thinking_mode,
            document_analysis_enabled=config.document_analysis.enabled,
            source="config",
        )

    def validate(self) -> "JobOptions":
        if self.thinking_mode not in {"disabled", "enabled", "provider_default"}:
            raise ValueError(
                "Job thinking_mode must be disabled, enabled, or provider_default"
            )
        if not isinstance(self.document_analysis_enabled, bool):
            raise ValueError("Job document_analysis_enabled must be a boolean")
        return self

    def as_dict(self) -> dict[str, object]:
        return {
            "thinking_mode": self.thinking_mode,
            "document_analysis_enabled": self.document_analysis_enabled,
            "source": self.source,
        }


def job_options_path(pdf_path: Path) -> Path:
    return pdf_path.parent / f".{pdf_path.name}.translation-job.json"


def write_job_options_atomic(pdf_path: Path, options: JobOptions) -> Path:
    options.validate()
    path = job_options_path(pdf_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    payload = {
        "schema_version": 1,
        "thinking_mode": options.thinking_mode,
        "document_analysis_enabled": options.document_analysis_enabled,
        "source": options.source,
    }
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def read_job_options(pdf_path: Path, defaults: JobOptions) -> JobOptions:
    path = job_options_path(pdf_path)
    if not path.is_file():
        return defaults.validate()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError(f"Unsupported or malformed job options file: {path.name}")
    thinking_mode = data.get("thinking_mode")
    analysis_enabled = data.get("document_analysis_enabled")
    if not isinstance(thinking_mode, str) or not isinstance(analysis_enabled, bool):
        raise ValueError(f"Invalid values in job options file: {path.name}")
    return JobOptions(
        thinking_mode=thinking_mode.strip().lower(),
        document_analysis_enabled=analysis_enabled,
        source="gui",
    ).validate()


def apply_job_options(config: AppConfig, options: JobOptions) -> AppConfig:
    options.validate()
    return replace(
        config,
        translation=replace(
            config.translation,
            thinking_mode=options.thinking_mode,
        ),
        document_analysis=replace(
            config.document_analysis,
            enabled=options.document_analysis_enabled,
        ),
    )


def remove_job_options(pdf_path: Path) -> None:
    path = job_options_path(pdf_path)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
