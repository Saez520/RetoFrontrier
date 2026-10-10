"""Pruebas de la configuración leída desde el entorno."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from replacement.settings import load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ready_with_token_and_existing_file(tmp_path):
    evidence = tmp_path / "experimentos.jsonl"
    evidence.write_text("{}\n", encoding="utf-8")

    settings = load_settings(
        {"TEAM_TOKEN": "secreto-de-prueba", "REFERENCE_RESPONSES_PATH": str(evidence)}
    )

    assert settings.ready is True
    assert settings.reason == ""
    assert settings.token == "secreto-de-prueba"
    assert settings.references_path == str(evidence)


def test_missing_token_is_not_ready(tmp_path):
    evidence = tmp_path / "experimentos.jsonl"
    evidence.write_text("{}\n", encoding="utf-8")

    settings = load_settings({"REFERENCE_RESPONSES_PATH": str(evidence)})

    assert settings.ready is False
    assert settings.token == ""
    assert settings.reason
    assert "secreto" not in settings.reason


def test_missing_references_path_is_not_ready(tmp_path):
    missing = tmp_path / "no-existe.jsonl"

    settings = load_settings(
        {"TEAM_TOKEN": "secreto-de-prueba", "REFERENCE_RESPONSES_PATH": str(missing)}
    )

    assert settings.ready is False
    assert settings.reason
    assert "secreto-de-prueba" not in settings.reason


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root puede leer cualquier archivo")
def test_unreadable_references_path_is_not_ready(tmp_path):
    evidence = tmp_path / "experimentos.jsonl"
    evidence.write_text("{}\n", encoding="utf-8")
    evidence.chmod(0o000)
    try:
        settings = load_settings(
            {"TEAM_TOKEN": "secreto-de-prueba", "REFERENCE_RESPONSES_PATH": str(evidence)}
        )
    finally:
        evidence.chmod(0o600)

    assert settings.ready is False
    assert settings.reason


def test_default_references_path_used_when_unset():
    settings = load_settings({"TEAM_TOKEN": "secreto-de-prueba"})
    assert settings.references_path == "experimentos.jsonl"


def test_env_example_declares_names_without_values():
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()

    assert set(values) == {"TEAM_TOKEN", "REFERENCE_RESPONSES_PATH"}
    assert values["TEAM_TOKEN"] == ""
