from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("filename", ["启动PDF翻译GUI.cmd", "一键启动PDF翻译器.cmd"])
def test_windows_launchers_are_ascii_crlf(filename: str) -> None:
    raw = (ROOT / filename).read_bytes()
    raw.decode("ascii")
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")


def test_gui_launcher_checks_required_files() -> None:
    text = (ROOT / "启动PDF翻译GUI.cmd").read_text(encoding="ascii")
    assert ".venv\\Scripts\\pythonw.exe" in text
    assert "config.toml" in text
    assert ".state\\gui-startup.log" in text
