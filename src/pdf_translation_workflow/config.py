from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PathsConfig:
    source: Path
    translated: Path
    archive: Path
    failed: Path
    state: Path


@dataclass(frozen=True)
class TranslationConfig:
    source_language: str = "auto"
    target_language: str = "Simplified Chinese"
    backend: str = "openai_compatible"
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "OPENAI_API_KEY"
    thinking_mode: str = "disabled"
    temperature: float = 0.1
    request_timeout_seconds: float = 120
    max_request_characters: int = 12_000
    retry_attempts: int = 4
    glossary: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentAnalysisConfig:
    enabled: bool = True
    required: bool = False
    sample_characters: int = 18_000
    max_keywords: int = 24
    max_terms: int = 48


@dataclass(frozen=True)
class OcrConfig:
    enabled: bool = True
    languages: tuple[str, ...] = ("en", "ch_sim")
    minimum_confidence: float = 0.58
    render_dpi: int = 220
    minimum_image_width: int = 80
    minimum_image_height: int = 40


@dataclass(frozen=True)
class LayoutConfig:
    minimum_font_size: float = 5.5
    maximum_font_size: float = 24
    box_padding: float = 1.2
    redaction_padding: float = 0.6
    line_height: float = 1.12
    font_file: Path | None = None
    fallback_cjk_font: str = "china-s"
    background_sampling: bool = True


@dataclass(frozen=True)
class WatchConfig:
    stable_seconds: float = 3
    poll_seconds: float = 1
    worker_count: int = 1
    startup_scan: bool = True
    recursive: bool = False


@dataclass(frozen=True)
class ArchiveConfig:
    date_folders: bool = True
    keep_original_filename: bool = True
    write_manifest: bool = True


@dataclass(frozen=True)
class AppConfig:
    root: Path
    paths: PathsConfig
    translation: TranslationConfig
    document_analysis: DocumentAnalysisConfig
    ocr: OcrConfig
    layout: LayoutConfig
    watch: WatchConfig
    archive: ArchiveConfig

    def ensure_directories(self) -> None:
        for path in (
            self.paths.source,
            self.paths.translated,
            self.paths.archive,
            self.paths.failed,
            self.paths.state,
        ):
            path.mkdir(parents=True, exist_ok=True)


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Configuration section [{name}] must be a table")
    return value


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def load_dotenv(path: Path) -> None:
    """Load a small, dependency-free subset of .env syntax without overwriting env vars."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(config_path: str | Path) -> AppConfig:
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    root = path.parent
    load_dotenv(root / ".env")
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    paths_raw = _section(raw, "paths")
    translation_raw = _section(raw, "translation")
    document_analysis_raw = _section(raw, "document_analysis")
    ocr_raw = _section(raw, "ocr")
    layout_raw = _section(raw, "layout")
    watch_raw = _section(raw, "watch")
    archive_raw = _section(raw, "archive")

    font_value = str(layout_raw.get("font_file", "")).strip()
    config = AppConfig(
        root=root,
        paths=PathsConfig(
            source=_resolve(root, paths_raw.get("source", "source")),
            translated=_resolve(root, paths_raw.get("translated", "translated")),
            archive=_resolve(root, paths_raw.get("archive", "archive")),
            failed=_resolve(root, paths_raw.get("failed", "failed")),
            state=_resolve(root, paths_raw.get("state", ".state")),
        ),
        translation=TranslationConfig(
            source_language=str(translation_raw.get("source_language", "auto")),
            target_language=str(translation_raw.get("target_language", "Simplified Chinese")),
            backend=str(translation_raw.get("backend", "openai_compatible")),
            model=os.getenv(
                "OPENAI_MODEL",
                str(translation_raw.get("model", "deepseek-v4-flash")),
            ),
            base_url=os.getenv(
                "OPENAI_BASE_URL",
                str(translation_raw.get("base_url", "https://api.deepseek.com")),
            ).rstrip("/"),
            api_key_env=str(translation_raw.get("api_key_env", "OPENAI_API_KEY")),
            thinking_mode=str(
                translation_raw.get("thinking_mode", "disabled")
            ).strip().lower(),
            temperature=float(translation_raw.get("temperature", 0.1)),
            request_timeout_seconds=float(
                translation_raw.get("request_timeout_seconds", 120)
            ),
            max_request_characters=int(
                translation_raw.get("max_request_characters", 12_000)
            ),
            retry_attempts=max(1, int(translation_raw.get("retry_attempts", 4))),
            glossary={str(k): str(v) for k, v in translation_raw.get("glossary", {}).items()},
        ),
        document_analysis=DocumentAnalysisConfig(
            enabled=bool(document_analysis_raw.get("enabled", True)),
            required=bool(document_analysis_raw.get("required", False)),
            sample_characters=max(
                1_000, int(document_analysis_raw.get("sample_characters", 18_000))
            ),
            max_keywords=max(
                1, int(document_analysis_raw.get("max_keywords", 24))
            ),
            max_terms=max(1, int(document_analysis_raw.get("max_terms", 48))),
        ),
        ocr=OcrConfig(
            enabled=bool(ocr_raw.get("enabled", True)),
            languages=tuple(str(item) for item in ocr_raw.get("languages", ["en", "ch_sim"])),
            minimum_confidence=float(ocr_raw.get("minimum_confidence", 0.58)),
            render_dpi=max(72, int(ocr_raw.get("render_dpi", 220))),
            minimum_image_width=max(1, int(ocr_raw.get("minimum_image_width", 80))),
            minimum_image_height=max(1, int(ocr_raw.get("minimum_image_height", 40))),
        ),
        layout=LayoutConfig(
            minimum_font_size=float(layout_raw.get("minimum_font_size", 5.5)),
            maximum_font_size=float(layout_raw.get("maximum_font_size", 24)),
            box_padding=float(layout_raw.get("box_padding", 1.2)),
            redaction_padding=float(layout_raw.get("redaction_padding", 0.6)),
            line_height=float(layout_raw.get("line_height", 1.12)),
            font_file=_resolve(root, font_value) if font_value else None,
            fallback_cjk_font=str(layout_raw.get("fallback_cjk_font", "china-s")),
            background_sampling=bool(layout_raw.get("background_sampling", True)),
        ),
        watch=WatchConfig(
            stable_seconds=max(0.5, float(watch_raw.get("stable_seconds", 3))),
            poll_seconds=max(0.2, float(watch_raw.get("poll_seconds", 1))),
            worker_count=max(1, int(watch_raw.get("worker_count", 1))),
            startup_scan=bool(watch_raw.get("startup_scan", True)),
            recursive=bool(watch_raw.get("recursive", False)),
        ),
        archive=ArchiveConfig(
            date_folders=bool(archive_raw.get("date_folders", True)),
            keep_original_filename=bool(archive_raw.get("keep_original_filename", True)),
            write_manifest=bool(archive_raw.get("write_manifest", True)),
        ),
    )
    if config.layout.minimum_font_size <= 0:
        raise ValueError("layout.minimum_font_size must be positive")
    if config.layout.maximum_font_size < config.layout.minimum_font_size:
        raise ValueError("layout.maximum_font_size must be >= layout.minimum_font_size")
    if config.translation.thinking_mode not in {"disabled", "enabled", "provider_default"}:
        raise ValueError(
            "translation.thinking_mode must be disabled, enabled, or provider_default"
        )
    return config
