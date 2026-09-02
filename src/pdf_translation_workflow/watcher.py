from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import AppConfig
from .pipeline import ProcessResult, TranslationPipeline

LOG = logging.getLogger(__name__)


@dataclass
class _PendingFile:
    signature: tuple[int, int] | None = None
    unchanged_since: float = 0


class InstanceLock:
    """Cross-platform, non-blocking lock that prevents two watchers sharing one state dir."""

    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    def __enter__(self) -> "InstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        self._handle.seek(0, os.SEEK_END)
        if self._handle.tell() == 0:
            self._handle.write(b"0")
            self._handle.flush()
        self._handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._handle.close()
            self._handle = None
            raise RuntimeError("Another PDF translator watcher is already running") from exc
        return self

    def __exit__(self, *_: object) -> None:
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


class _EventHandler(FileSystemEventHandler):
    def __init__(self, schedule):
        self.schedule = schedule

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.schedule(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory and hasattr(event, "dest_path"):
            self.schedule(Path(event.dest_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.schedule(Path(event.src_path))


class FolderWatcher:
    def __init__(self, config: AppConfig, pipeline: TranslationPipeline):
        self.config = config
        self.pipeline = pipeline
        self._pending: dict[Path, _PendingFile] = {}
        self._pending_lock = threading.Lock()
        self._active: set[Path] = set()
        self._active_lock = threading.Lock()
        self._work: queue.Queue[Path | None] = queue.Queue()
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []
        self._observer = Observer()

    def schedule(self, path: Path) -> None:
        try:
            candidate = path.resolve()
            candidate.relative_to(self.config.paths.source)
        except (OSError, ValueError):
            return
        if candidate.suffix.lower() != ".pdf" or candidate.name.startswith("~"):
            return
        with self._active_lock:
            if candidate in self._active:
                return
        with self._pending_lock:
            if candidate not in self._pending:
                self._pending[candidate] = _PendingFile()
                LOG.info("Detected PDF; waiting for file stability: %s", candidate.name)

    def run(self) -> None:
        self.config.ensure_directories()
        with InstanceLock(self.config.paths.state / "watcher.lock"):
            self._start_workers()
            handler = _EventHandler(self.schedule)
            self._observer.schedule(
                handler,
                str(self.config.paths.source),
                recursive=self.config.watch.recursive,
            )
            self._observer.start()
            if self.config.watch.startup_scan:
                self._scan_source()
            LOG.info("Watching %s", self.config.paths.source)
            last_sweep = 0.0
            try:
                while not self._stop.wait(self.config.watch.poll_seconds):
                    self._promote_stable_files()
                    now = time.monotonic()
                    if now - last_sweep >= 30:
                        self._scan_source()
                        last_sweep = now
            finally:
                self._observer.stop()
                self._observer.join(timeout=10)
                for _ in self._workers:
                    self._work.put(None)
                for worker in self._workers:
                    worker.join(timeout=30)
                LOG.info("Watcher stopped")

    def stop(self) -> None:
        self._stop.set()

    def _scan_source(self) -> None:
        pattern = "**/*.pdf" if self.config.watch.recursive else "*.pdf"
        for path in self.config.paths.source.glob(pattern):
            self.schedule(path)

    def _promote_stable_files(self) -> None:
        now = time.monotonic()
        ready: list[Path] = []
        missing: list[Path] = []
        with self._pending_lock:
            items = list(self._pending.items())
        for path, state in items:
            try:
                stat = path.stat()
                signature = (stat.st_size, stat.st_mtime_ns)
            except (FileNotFoundError, PermissionError, OSError):
                missing.append(path)
                continue
            if signature != state.signature:
                state.signature = signature
                state.unchanged_since = now
            elif stat.st_size > 0 and now - state.unchanged_since >= self.config.watch.stable_seconds:
                ready.append(path)
        with self._pending_lock:
            for path in [*ready, *missing]:
                self._pending.pop(path, None)
        for path in ready:
            with self._active_lock:
                if path in self._active:
                    continue
                self._active.add(path)
            LOG.info("PDF is stable and queued for translation: %s", path.name)
            self._work.put(path)

    def _start_workers(self) -> None:
        for index in range(self.config.watch.worker_count):
            worker = threading.Thread(
                target=self._worker,
                name=f"pdf-worker-{index + 1}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)

    def _worker(self) -> None:
        while True:
            path = self._work.get()
            if path is None:
                self._work.task_done()
                return
            try:
                result: ProcessResult = self.pipeline.process(path)
                LOG.info("Job result for %s: %s - %s", path.name, result.status, result.message)
            except Exception:
                LOG.exception("Unhandled worker error for %s", path)
            finally:
                with self._active_lock:
                    self._active.discard(path)
                self._work.task_done()
