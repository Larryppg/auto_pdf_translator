from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .config import AppConfig, load_config
from .job_options import (
    JobOptions,
    job_options_path,
    remove_job_options,
    write_job_options_atomic,
)
from .state import JobStore
from .watcher import InstanceLock


@dataclass
class GuiJob:
    original: Path
    staged: Path
    tree_id: str
    options: JobOptions
    status: str = "queued"
    output: Path | None = None
    archived: Path | None = None
    error: str = ""


@dataclass(frozen=True)
class LogProgress:
    percent: float | None = None
    status: str | None = None
    job_name: str | None = None


_JOB_ACCEPTED = re.compile(r"Job accepted: (?P<name>.+) \([0-9a-f]{12}\);")
_EXTRACTION = re.compile(r"Extraction/OCR page \d+/\d+ \((?P<pct>[0-9.]+)%\)")
_BATCH_STARTED = re.compile(
    r"Translation batch \d+/\d+ started:.*overall (?P<pct>[0-9.]+)%"
)
_BATCH_COMPLETED = re.compile(
    r"Translation batch \d+/\d+ completed.*\((?P<pct>[0-9.]+)%\); ETA (?P<eta>[^|]+)$"
)
_LAYOUT = re.compile(r"Layout page \d+/\d+ \((?P<pct>[0-9.]+)%\)")
_JOB_RESULT = re.compile(
    r"Job result for (?P<name>.+): (?P<status>completed|duplicate|failed|skipped) -"
)


def _progress_from_log_line(line: str) -> LogProgress:
    if match := _JOB_ACCEPTED.search(line):
        return LogProgress(1, "任务已接收，正在计算文件哈希", match.group("name"))
    if match := _EXTRACTION.search(line):
        value = float(match.group("pct"))
        return LogProgress(value * 0.20, f"正在提取文字和 OCR：{value:.1f}%")
    if "Document pre-analysis started" in line:
        return LogProgress(21, "正在识别文档主题、关键词和歧义术语")
    if "Document pre-analysis completed" in line:
        return LogProgress(25, "文档预分析完成，准备分批翻译")
    if "Document pre-analysis failed" in line:
        return LogProgress(25, "预分析失败，已降级继续翻译")
    if match := _BATCH_STARTED.search(line):
        value = float(match.group("pct"))
        return LogProgress(25 + value * 0.45, f"AI 翻译进行中：{value:.1f}%")
    if match := _BATCH_COMPLETED.search(line):
        value = float(match.group("pct"))
        eta = match.group("eta").strip()
        return LogProgress(
            25 + value * 0.45,
            f"AI 翻译：{value:.1f}%，预计剩余 {eta}",
        )
    if "Phase 2/5 - document analysis and AI translation completed" in line:
        return LogProgress(70, "AI 翻译完成，开始原位排版")
    if match := _LAYOUT.search(line):
        value = float(match.group("pct"))
        return LogProgress(70 + value * 0.20, f"正在排版：{value:.1f}%")
    if "Phase 4/5 - writing temporary PDF" in line:
        return LogProgress(92, "正在写入临时 PDF")
    if "Phase 4/5 - temporary PDF written" in line:
        return LogProgress(95, "PDF 已写入，准备验证")
    if "Phase 5/5 - validating translated PDF" in line:
        return LogProgress(97, "正在验证页数和可读性")
    if "Phase 5/5 - validation completed" in line:
        return LogProgress(99, "验证完成，正在保存和归档")
    if match := _JOB_RESULT.search(line):
        status = match.group("status")
        labels = {
            "completed": "翻译完成",
            "duplicate": "内容重复，已复用现有译文",
            "failed": "翻译失败",
            "skipped": "任务已跳过",
        }
        percent = 100 if status in {"completed", "duplicate"} else None
        return LogProgress(percent, labels[status], match.group("name"))
    return LogProgress()


def _allocate_staging_path(source_directory: Path, filename: str) -> Path:
    candidate = source_directory / Path(filename).name
    if not candidate.exists() and not job_options_path(candidate).exists():
        return candidate
    for number in range(1, 10_000):
        candidate = source_directory / f"{Path(filename).stem}.gui-{number}{Path(filename).suffix}"
        if not candidate.exists() and not job_options_path(candidate).exists():
            return candidate
    raise RuntimeError(f"无法为 {filename} 分配 source 文件名")


def _stage_pdf(
    original: Path,
    source_directory: Path,
    options: JobOptions | None = None,
) -> Path:
    original = original.expanduser().resolve()
    source_directory = source_directory.resolve()
    if not original.is_file():
        raise FileNotFoundError(f"文件不存在：{original}")
    if original.suffix.lower() != ".pdf":
        raise ValueError(f"不是 PDF 文件：{original.name}")
    source_directory.mkdir(parents=True, exist_ok=True)
    try:
        original.relative_to(source_directory)
    except ValueError:
        pass
    else:
        if options is not None:
            write_job_options_atomic(original, options)
        return original

    destination = _allocate_staging_path(source_directory, original.name)
    temporary = source_directory / f".{destination.name}.{uuid.uuid4().hex}.importing"
    try:
        shutil.copy2(original, temporary)
        if options is not None:
            write_job_options_atomic(destination, options)
        os.replace(temporary, destination)
    except Exception:
        if options is not None:
            remove_job_options(destination)
        raise
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination.resolve()


def _watcher_is_running(lock_path: Path) -> bool:
    try:
        with InstanceLock(lock_path):
            return False
    except RuntimeError:
        return True


def _start_watcher_if_needed(config: AppConfig, config_path: Path) -> tuple[str, int | None]:
    lock_path = config.paths.state / "watcher.lock"
    if _watcher_is_running(lock_path):
        return "running", None

    executable = Path(sys.executable)
    console_python = executable.with_name("python.exe")
    if console_python.is_file():
        executable = console_python
    command = [
        str(executable),
        "-m",
        "pdf_translation_workflow",
        "--config",
        str(config_path),
        "watch",
    ]
    kwargs: dict[str, object] = {
        "cwd": str(config.root),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if _watcher_is_running(lock_path):
            return "started", process.pid
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"后台监听器启动失败，退出码 {exit_code}")
        time.sleep(0.1)
    raise RuntimeError("后台监听器启动超时，请查看 .state/workflow.log")


def _open_path(path: Path) -> None:
    path = path.resolve()
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class PdfTranslatorGui:
    def __init__(self, root: tk.Tk, config: AppConfig, config_path: Path):
        self.root = root
        self.config = config
        self.config_path = config_path
        self.store = JobStore(config.paths.state / "jobs.sqlite3")
        self.jobs: dict[str, GuiJob] = {}
        self.events: queue.Queue[tuple[object, ...]] = queue.Queue()
        self.current_job_name: str | None = None
        self.refresh_running = False
        self.log_path = config.paths.state / "workflow.log"
        self.log_offset = self.log_path.stat().st_size if self.log_path.is_file() else 0

        self.status_text = tk.StringVar(value="正在检查后台监听器……")
        self.watcher_text = tk.StringVar(value="监听器：检查中")
        self.progress_value = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar(value="尚未选择 PDF")
        self.thinking_enabled = tk.BooleanVar(
            value=config.translation.thinking_mode == "enabled"
        )
        self.analysis_enabled = tk.BooleanVar(
            value=config.document_analysis.enabled
        )

        self._build_window()
        self.root.after(100, self._drain_events)
        self.root.after(700, self._schedule_refresh)
        threading.Thread(target=self._ensure_watcher_worker, daemon=True).start()

    def _build_window(self) -> None:
        self.root.title("PDF 自动翻译与归档")
        self.root.geometry("1040x720")
        self.root.minsize(820, 560)

        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Sub.TLabel", foreground="#4b5563")

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="PDF 自动翻译与归档", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                f"模型：{self.config.translation.model}　"
                f"目标语言：{self.config.translation.target_language}　"
                "下方开关按本次入队任务生效"
            ),
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 14))

        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        self.select_button = ttk.Button(
            actions,
            text="选择并翻译 PDF…",
            command=self._choose_files,
        )
        self.select_button.pack(side="left")
        ttk.Button(actions, text="打开译文", command=self._open_selected_output).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(
            actions,
            text="打开输出文件夹",
            command=lambda: _open_path(self.config.paths.translated),
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            actions,
            text="打开 source",
            command=lambda: _open_path(self.config.paths.source),
        ).pack(side="left", padx=(8, 0))
        ttk.Label(actions, textvariable=self.watcher_text).pack(side="right")

        settings = ttk.LabelFrame(outer, text="新加入文件的 AI 设置", padding=10)
        settings.pack(fill="x", pady=(14, 0))
        ttk.Checkbutton(
            settings,
            text="开启思考模式",
            variable=self.thinking_enabled,
        ).pack(side="left")
        ttk.Checkbutton(
            settings,
            text="开启文档预分析（主题、关键词、专名、缩写和多义词）",
            variable=self.analysis_enabled,
        ).pack(side="left", padx=(22, 0))
        ttk.Label(
            settings,
            text="设置在点击“选择并翻译”时锁定，不影响已在队列中的文件。",
            style="Sub.TLabel",
        ).pack(side="right")

        progress_frame = ttk.LabelFrame(outer, text="当前进度", padding=10)
        progress_frame.pack(fill="x", pady=(12, 12))
        ttk.Progressbar(
            progress_frame,
            variable=self.progress_value,
            maximum=100,
            mode="determinate",
        ).pack(fill="x")
        ttk.Label(progress_frame, textvariable=self.progress_text).pack(anchor="w", pady=(6, 0))
        ttk.Label(progress_frame, textvariable=self.status_text, style="Sub.TLabel").pack(
            anchor="w", pady=(2, 0)
        )

        jobs_frame = ttk.LabelFrame(outer, text="本次 GUI 加入的文件", padding=8)
        jobs_frame.pack(fill="both", expand=True)
        columns = ("original", "queued", "settings", "status", "output")
        self.tree = ttk.Treeview(jobs_frame, columns=columns, show="headings", height=9)
        self.tree.heading("original", text="原文件")
        self.tree.heading("queued", text="工作副本")
        self.tree.heading("settings", text="本任务设置")
        self.tree.heading("status", text="状态")
        self.tree.heading("output", text="译文")
        self.tree.column("original", width=190, minwidth=110)
        self.tree.column("queued", width=190, minwidth=110)
        self.tree.column("settings", width=170, minwidth=140)
        self.tree.column("status", width=145, minwidth=100)
        self.tree.column("output", width=230, minwidth=130)
        tree_scroll = ttk.Scrollbar(jobs_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _event: self._open_selected_output())

        log_frame = ttk.LabelFrame(outer, text="实时日志", padding=8)
        log_frame.pack(fill="both", expand=True, pady=(12, 0))
        self.log_view = tk.Text(
            log_frame,
            height=9,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
        )
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_view.yview)
        self.log_view.configure(yscrollcommand=log_scroll.set)
        self.log_view.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _choose_files(self) -> None:
        selected = filedialog.askopenfilenames(
            parent=self.root,
            title="选择要翻译的 PDF",
            filetypes=(("PDF 文件", "*.pdf"), ("所有文件", "*.*")),
        )
        if not selected:
            return
        options = JobOptions(
            thinking_mode="enabled" if self.thinking_enabled.get() else "disabled",
            document_analysis_enabled=bool(self.analysis_enabled.get()),
            source="gui",
        )
        self.select_button.configure(state="disabled")
        thinking_label = "开" if options.thinking_mode == "enabled" else "关"
        analysis_label = "开" if options.document_analysis_enabled else "关"
        self.status_text.set(
            f"正在复制 {len(selected)} 个文件到安全工作队列；"
            f"思考 {thinking_label}，预分析 {analysis_label}……"
        )
        threading.Thread(
            target=self._stage_files_worker,
            args=([Path(value) for value in selected], options),
            daemon=True,
        ).start()

    def _stage_files_worker(self, files: list[Path], options: JobOptions) -> None:
        for original in files:
            try:
                staged = _stage_pdf(original, self.config.paths.source, options)
                self.events.put(("staged", original, staged, options))
            except Exception as exc:
                self.events.put(("stage_error", original, str(exc)))
        self.events.put(("stage_complete", len(files)))

    def _ensure_watcher_worker(self) -> None:
        try:
            state, pid = _start_watcher_if_needed(self.config, self.config_path)
            self.events.put(("watcher", state, pid))
        except Exception as exc:
            self.events.put(("watcher_error", str(exc)))

    def _schedule_refresh(self) -> None:
        if not self.refresh_running:
            self.refresh_running = True
            threading.Thread(target=self._refresh_worker, daemon=True).start()
        self.root.after(1_000, self._schedule_refresh)

    def _refresh_worker(self) -> None:
        try:
            rows = self.store.recent(200)
            lines = self._read_new_log_lines()
            self.events.put(("refresh", rows, lines))
        except Exception as exc:
            self.events.put(("refresh_error", str(exc)))
        finally:
            self.refresh_running = False

    def _read_new_log_lines(self) -> list[str]:
        if not self.log_path.is_file():
            return []
        size = self.log_path.stat().st_size
        if size < self.log_offset:
            self.log_offset = 0
        with self.log_path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self.log_offset)
            content = handle.read()
            self.log_offset = handle.tell()
        return [line for line in content.splitlines() if line.strip()]

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _handle_event(self, event: tuple[object, ...]) -> None:
        kind = str(event[0])
        if kind == "watcher":
            state, pid = str(event[1]), event[2]
            if state == "running":
                self.watcher_text.set("监听器：已在运行")
                self.status_text.set("后台监听器已就绪，可以选择 PDF")
            else:
                self.watcher_text.set(f"监听器：已启动（PID {pid}）")
                self.status_text.set("后台监听器已启动，可以选择 PDF")
            return
        if kind == "watcher_error":
            self.watcher_text.set("监听器：启动失败")
            self.status_text.set(str(event[1]))
            messagebox.showerror("监听器启动失败", str(event[1]), parent=self.root)
            return
        if kind == "staged":
            self._add_job(Path(event[1]), Path(event[2]), event[3])  # type: ignore[arg-type]
            return
        if kind == "stage_error":
            original, error = Path(event[1]), str(event[2])
            messagebox.showerror(
                "文件加入失败",
                f"{original.name}\n\n{error}",
                parent=self.root,
            )
            return
        if kind == "stage_complete":
            self.select_button.configure(state="normal")
            self.status_text.set(f"已处理 {event[1]} 个选择；监听器会按顺序翻译")
            return
        if kind == "refresh":
            self._apply_state_rows(event[1])  # type: ignore[arg-type]
            for line in event[2]:  # type: ignore[union-attr]
                self._apply_log_line(str(line))
            return
        if kind == "refresh_error":
            self.status_text.set(f"读取状态失败：{event[1]}")

    def _add_job(self, original: Path, staged: Path, options: JobOptions) -> None:
        if staged.name in self.jobs:
            return
        thinking_label = "思考开" if options.thinking_mode == "enabled" else "思考关"
        analysis_label = "预分析开" if options.document_analysis_enabled else "预分析关"
        tree_id = self.tree.insert(
            "",
            "end",
            values=(
                original.name,
                staged.name,
                f"{thinking_label} / {analysis_label}",
                "等待监听器",
                "",
            ),
        )
        self.jobs[staged.name] = GuiJob(original, staged, tree_id, options)
        self.tree.selection_set(tree_id)
        self.progress_value.set(0)
        self.progress_text.set(f"已加入队列：{staged.name}")

    def _apply_state_rows(self, rows: list[dict[str, object]]) -> None:
        labels = {
            "processing": "处理中",
            "completed": "已完成",
            "duplicate": "重复内容，已复用",
            "failed": "失败",
        }
        newest_by_name: dict[str, dict[str, object]] = {}
        for row in rows:
            name = str(row.get("source_name", ""))
            if name and name not in newest_by_name:
                newest_by_name[name] = row
        for name, job in self.jobs.items():
            row = newest_by_name.get(name)
            if not row:
                continue
            status = str(row.get("status", ""))
            job.status = status
            output_value = row.get("output_path")
            archive_value = row.get("archive_path")
            job.output = Path(str(output_value)) if output_value else None
            job.archived = Path(str(archive_value)) if archive_value else None
            job.error = str(row.get("error") or "")
            self.tree.set(job.tree_id, "status", labels.get(status, status))
            self.tree.set(job.tree_id, "output", job.output.name if job.output else "")
            if status in {"completed", "duplicate"} and name == self.current_job_name:
                self.progress_value.set(100)
                self.progress_text.set(f"完成：{name}")

    def _apply_log_line(self, line: str) -> None:
        self.log_view.configure(state="normal")
        self.log_view.insert("end", line + "\n")
        line_count = int(self.log_view.index("end-1c").split(".")[0])
        if line_count > 350:
            self.log_view.delete("1.0", f"{line_count - 300}.0")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

        update = _progress_from_log_line(line)
        if update.job_name:
            self.current_job_name = update.job_name
        if update.percent is not None:
            self.progress_value.set(max(0, min(100, update.percent)))
        if update.status:
            prefix = f"{self.current_job_name}：" if self.current_job_name else ""
            self.progress_text.set(prefix + update.status)

    def _open_selected_output(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("打开译文", "请先在任务列表中选择一个文件。", parent=self.root)
            return
        tree_id = selected[0]
        job = next((item for item in self.jobs.values() if item.tree_id == tree_id), None)
        if job is None:
            return
        if job.output and job.output.is_file():
            _open_path(job.output)
            return
        if job.status == "failed":
            messagebox.showerror(
                "翻译失败",
                job.error[-4_000:] or "请查看实时日志或 .state/workflow.log。",
                parent=self.root,
            )
            return
        messagebox.showinfo("译文尚未生成", "该任务仍在队列中或正在处理。", parent=self.root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PDF translation workflow GUI")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.cwd() / "config.toml",
        help="TOML configuration file",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    config_path = args.config.expanduser().resolve()
    try:
        config = load_config(config_path)
        config.ensure_directories()
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("PDF 翻译器启动失败", str(exc), parent=root)
        root.destroy()
        return
    root = tk.Tk()
    PdfTranslatorGui(root, config, config_path)
    root.mainloop()


if __name__ == "__main__":
    main()
