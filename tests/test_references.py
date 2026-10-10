"""Pruebas del lector de evidencia y del catálogo de referencias."""

from __future__ import annotations

import hashlib

from replacement.references import build_reference_response, load_catalog
from replacement.settings import Settings


def _settings(evidence_path) -> Settings:
    return Settings(token="token-de-prueba", references_path=str(evidence_path), ready=True, reason="")


def _build(write_jsonl, write_manifest, reference_data, mutate_evidence=None, mutate_cases=None):
    evidence = [dict(line) for line in reference_data["evidence"]]
    cases = [dict(case) for case in reference_data["cases"]]
    if mutate_evidence is not None:
        mutate_evidence(evidence)
    if mutate_cases is not None:
        mutate_cases(cases)

    evidence_path = write_jsonl(evidence)
    manifest_path = write_manifest(cases)
    return load_catalog(_settings(evidence_path), str(manifest_path)), evidence_path, manifest_path


# --- Construcción de respuestas ---------------------------------------------


def test_list_response_is_compact_json_and_preserves_order():
    response = build_reference_response(200, ["b", "a", 1])
    assert response.body == b'["b","a",1]'
    assert response.content_type.startswith("application/json")


def test_dict_response_is_compact_json():
    response = build_reference_response(200, {"a": 1, "b": [2, 3]})
    assert response.body == b'{"a":1,"b":[2,3]}'
    assert response.content_type.startswith("application/json")


def test_text_response_is_literal_bytes():
    response = build_reference_response(400, "texto exacto ")
    assert response.body == b"texto exacto "
    assert response.content_type.startswith("text/plain")


# --- Catálogo válido ---------------------------------------------------------


def test_valid_catalog_is_ready(write_jsonl, write_manifest, reference_data):
    catalog, _, _ = _build(write_jsonl, write_manifest, reference_data)
    assert catalog.ready is True
    assert catalog.reason == ""
    assert catalog.used_evidence_ids  # solo visible para el operador


def test_exact_selector_wins_over_fallback(write_jsonl, write_manifest, reference_data):
    def add_exact(evidence):
        evidence.append({"id": 12, "status": 418, "response": {"error": "E999", "mensaje": "exacto"}})

    def add_case(cases):
        cases.append({"method": "GET", "path": "/especial", "auth": "valid", "evidence_id": 12})

    catalog, _, _ = _build(write_jsonl, write_manifest, reference_data, add_exact, add_case)

    exact = catalog.resolve("GET", "/especial", "valid")
    assert exact is not None and exact.status == 418

    fallback = catalog.resolve("GET", "/otra", "valid")
    assert fallback is not None and fallback.status == 404


def test_resolve_returns_none_when_not_ready(write_jsonl, write_manifest, reference_data):
    catalog, _, _ = _build(
        write_jsonl,
        write_manifest,
        reference_data,
        mutate_cases=lambda cases: cases.clear(),
    )
    assert catalog.ready is False
    assert catalog.resolve("GET", "/health", "valid") is None


# --- Evidencia inválida ------------------------------------------------------


def test_missing_evidence_file_is_not_ready(write_manifest, reference_data, tmp_path):
    manifest_path = write_manifest(reference_data["cases"])
    catalog = load_catalog(_settings(tmp_path / "no-existe.jsonl"), str(manifest_path))
    assert catalog.ready is False
    assert catalog.reason


def test_malformed_jsonl_line_is_not_ready(write_jsonl, write_manifest, reference_data, tmp_path):
    evidence_path = tmp_path / "experimentos.jsonl"
    evidence_path.write_text('{"id": 1, "status": 200, "response": {}}\n{no-json}\n', encoding="utf-8")
    manifest_path = write_manifest(reference_data["cases"])
    catalog = load_catalog(_settings(evidence_path), str(manifest_path))
    assert catalog.ready is False
    assert "línea" in catalog.reason


def test_duplicate_evidence_id_is_not_ready(write_jsonl, write_manifest, reference_data):
    def duplicate(evidence):
        evidence[1]["id"] = evidence[0]["id"]

    catalog, _, _ = _build(write_jsonl, write_manifest, reference_data, mutate_evidence=duplicate)
    assert catalog.ready is False
    assert "repite" in catalog.reason


def test_invalid_status_type_is_not_ready(write_jsonl, write_manifest, reference_data):
    def bad_status(evidence):
        evidence[0]["status"] = "200"

    catalog, _, _ = _build(write_jsonl, write_manifest, reference_data, mutate_evidence=bad_status)
    assert catalog.ready is False


def test_invalid_response_type_is_not_ready(write_jsonl, write_manifest, reference_data):
    def bad_response(evidence):
        evidence[0]["response"] = 200

    catalog, _, _ = _build(write_jsonl, write_manifest, reference_data, mutate_evidence=bad_response)
    assert catalog.ready is False


# --- Manifiesto inválido -----------------------------------------------------


def test_missing_required_selector_is_not_ready(write_jsonl, write_manifest, reference_data):
    def drop_health(cases):
        cases.pop(0)

    catalog, _, _ = _build(write_jsonl, write_manifest, reference_data, mutate_cases=drop_health)
    assert catalog.ready is False
    assert "falta el selector" in catalog.reason


def test_duplicate_selector_is_not_ready(write_jsonl, write_manifest, reference_data):
    def duplicate_case(cases):
        cases.append(dict(cases[0]))

    catalog, _, _ = _build(write_jsonl, write_manifest, reference_data, mutate_cases=duplicate_case)
    assert catalog.ready is False
    assert "repite el selector" in catalog.reason


def test_invalid_auth_mode_is_not_ready(write_jsonl, write_manifest, reference_data):
    def bad_auth(cases):
        cases[0]["auth"] = "otro"

    catalog, _, _ = _build(write_jsonl, write_manifest, reference_data, mutate_cases=bad_auth)
    assert catalog.ready is False


def test_unknown_evidence_id_is_not_ready(write_jsonl, write_manifest, reference_data):
    def bad_id(cases):
        cases[0]["evidence_id"] = 999

    catalog, _, _ = _build(write_jsonl, write_manifest, reference_data, mutate_cases=bad_id)
    assert catalog.ready is False
    assert "no existe en la evidencia" in catalog.reason


def test_invalid_manifest_json_is_not_ready(write_jsonl, reference_data, tmp_path):
    evidence_path = write_jsonl(reference_data["evidence"])
    manifest_path = tmp_path / "reference_cases.json"
    manifest_path.write_text("{no-json", encoding="utf-8")
    catalog = load_catalog(_settings(evidence_path), str(manifest_path))
    assert catalog.ready is False


# --- Solo lectura ------------------------------------------------------------


def test_evidence_is_read_only(write_jsonl, write_manifest, reference_data):
    catalog, evidence_path, _ = _build(write_jsonl, write_manifest, reference_data)
    assert catalog.ready is True

    before = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    # Una segunda carga no debe modificar el archivo.
    load_catalog(_settings(evidence_path), str(evidence_path.parent / "reference_cases.json"))
    after = hashlib.sha256(evidence_path.read_bytes()).hexdigest()

    assert before == after
