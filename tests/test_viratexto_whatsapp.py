import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp


def _viratexto_text_message() -> dict:
    return {
        "from": "5599999999999",
        "id": "wamid.HBgMNTU5OTk5OTk5OTk5ORUCABIYLongMessageId",
        "timestamp": "1781900000",
        "type": "text",
        "text": {"body": "Transcricao teste sem dados sensiveis."},
    }


def test_parse_viratexto_text_response():
    record = api_whatsapp._parse_viratexto_test_message(_viratexto_text_message())

    assert record["sender_phone"] == "5599999999999"
    assert record["message_type"] == "text"
    assert record["text"] == "Transcricao teste sem dados sensiveis."
    assert record["ids"]["message_id"].startswith("wamid.")
    assert record["raw_payload_sanitized"]["from"] == "***9999"


def test_parse_viratexto_interactive_response():
    message = {
        "from": "5599999999999",
        "id": "wamid.interactive.long",
        "timestamp": "1781900001",
        "type": "interactive",
        "interactive": {
            "type": "list_reply",
            "list_reply": {
                "id": "resumo",
                "title": "Resumo",
                "description": "Gerar resumo",
            },
        },
    }

    record = api_whatsapp._parse_viratexto_test_message(message)

    assert record["message_type"] == "interactive"
    assert record["text"] == "Resumo"
    assert record["interactive"] == {
        "type": "list_reply",
        "id": "resumo",
        "title": "Resumo",
        "description": "Gerar resumo",
    }


def test_viratexto_test_mode_does_not_enter_rdv_flow(monkeypatch, tmp_path):
    class FailingRDVService:
        def get_collaborator_by_phone(self, sender_phone):
            raise AssertionError("ViraTexto nao deveria entrar no fluxo RDV")

    original_rdv_service = api_whatsapp.rdv_service
    monkeypatch.setenv("VIRATEXTO_TEST_MODE", "true")
    monkeypatch.setenv("VIRATEXTO_PHONE", "5599999999999")
    monkeypatch.setattr(api_whatsapp, "VIRATEXTO_TEST_LOG_PATH", tmp_path / "viratexto.jsonl")
    api_whatsapp.rdv_service = FailingRDVService()
    try:
        api_whatsapp._handle_whatsapp_message(_viratexto_text_message())
    finally:
        api_whatsapp.rdv_service = original_rdv_service

    lines = (tmp_path / "viratexto.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["text"] == "Transcricao teste sem dados sensiveis."


def test_viratexto_log_is_generated_and_sanitized(monkeypatch, tmp_path):
    log_path = tmp_path / "viratexto.jsonl"
    monkeypatch.setattr(api_whatsapp, "VIRATEXTO_TEST_LOG_PATH", log_path)

    api_whatsapp._append_viratexto_test_log(
        api_whatsapp._parse_viratexto_test_message(_viratexto_text_message())
    )

    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["sender_phone"] == "5599999999999"
    assert record["raw_payload_sanitized"]["from"] == "***9999"
    assert record["raw_payload_sanitized"]["id"].startswith("wami")
    assert record["raw_payload_sanitized"]["id"].endswith("geId")
    assert record["raw_payload_sanitized"]["id"] != record["ids"]["message_id"]
