from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import signal
import sys
from pathlib import Path

from .config import AppConfig, load_config
from .pipeline import TranslationPipeline
from .state import JobStore
from .watcher import FolderWatcher


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-translator",
        description="Translate PDFs from a watched folder, including text inside images.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.cwd() / "config.toml",
        help="TOML configuration file (default: ./config.toml)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show debug logging")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("watch", help="Watch the source directory continuously")
    once = commands.add_parser("once", help="Process files once, without watching")
    once.add_argument("files", nargs="*", type=Path, help="PDFs; default is every source PDF")
    commands.add_parser("doctor", help="Check configuration and required components")
    status = commands.add_parser("status", help="Show recent job history")
    status.add_argument("--limit", type=int, default=20)
    return parser


def _configure_logging(config: AppConfig, verbose: bool) -> None:
    config.ensure_directories()
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s"
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.handlers.RotatingFileHandler(
        config.paths.state / "workflow.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=4,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)


def _doctor(config: AppConfig) -> int:
    checks: list[tuple[str, bool, str]] = []
    config.ensure_directories()
    checks.append(("config", True, str(config.root / "config.toml")))
    for name, path in config.paths.__dict__.items():
        writable = path.is_dir() and os.access(path, os.W_OK)
        checks.append((f"directory:{name}", writable, str(path)))
    if config.translation.backend == "openai_compatible":
        key = os.getenv(config.translation.api_key_env, "").strip()
        key_set = bool(key) and key.lower() not in {"replace-me", "changeme", "your-api-key"}
        checks.append((f"environment:{config.translation.api_key_env}", key_set, "set" if key_set else "missing"))
    if config.layout.font_file:
        checks.append(("font_file", config.layout.font_file.is_file(), str(config.layout.font_file)))
    if config.ocr.enabled:
        try:
            import onnxruntime  # noqa: F401
            import rapidocr  # noqa: F401

            ocr_ok, ocr_message = True, "available"
        except ImportError as exc:
            ocr_ok, ocr_message = False, str(exc)
        checks.append(("ocr", ocr_ok, ocr_message))
    try:
        import pymupdf  # noqa: F401

        pdf_ok, pdf_message = True, "available"
    except ImportError:
        try:
            import fitz  # noqa: F401

            pdf_ok, pdf_message = True, "available (legacy import)"
        except ImportError as exc:
            pdf_ok, pdf_message = False, str(exc)
    checks.append(("pymupdf", pdf_ok, pdf_message))
    for name, ok, message in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {message}")
    return 0 if all(item[1] for item in checks) else 2


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        _configure_logging(config, args.verbose)
        if args.command == "doctor":
            raise SystemExit(_doctor(config))
        if args.command == "status":
            store = JobStore(config.paths.state / "jobs.sqlite3")
            print(json.dumps(store.recent(max(1, args.limit)), ensure_ascii=False, indent=2))
            return
        pipeline = TranslationPipeline(config)
        if args.command == "once":
            paths = [path.resolve() for path in args.files]
            if not paths:
                pattern = "**/*.pdf" if config.watch.recursive else "*.pdf"
                paths = sorted(config.paths.source.glob(pattern))
            if not paths:
                print(f"No PDF files found in {config.paths.source}")
                return
            failed = False
            for path in paths:
                result = pipeline.process(path)
                print(f"[{result.status}] {path.name}: {result.message}")
                failed = failed or result.status == "failed"
            if failed:
                raise SystemExit(1)
            return
        watcher = FolderWatcher(config, pipeline)
        for signal_name in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signal_name, lambda *_: watcher.stop())
        watcher.run()
    except KeyboardInterrupt:
        return
    except Exception as exc:
        logging.getLogger(__name__).exception("Fatal error")
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
