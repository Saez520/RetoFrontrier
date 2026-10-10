"""Contrato estático del proceso de producción."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _procfile_lines() -> list[str]:
    text = (PROJECT_ROOT / "Procfile").read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def test_single_web_process():
    lines = _procfile_lines()
    web = [line for line in lines if line.startswith("web:")]
    assert len(web) == 1
    assert len(lines) == 1


def test_uses_gunicorn_on_replacement_wsgi_object():
    command = _procfile_lines()[0]
    assert "gunicorn" in command
    assert "replacement.app:app" in command


def test_binds_platform_port():
    command = _procfile_lines()[0]
    assert "0.0.0.0:$PORT" in command


def test_single_worker():
    command = _procfile_lines()[0]
    assert "--workers 1" in command
    assert "--workers 2" not in command


def test_no_second_process_or_probe_command():
    joined = " ".join(_procfile_lines()).lower()
    assert "probe" not in joined
    assert "sondeo" not in joined
    assert "curl" not in joined
    assert "worker=" not in joined
