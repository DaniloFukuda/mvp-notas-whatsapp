"""Regressões do dispatcher: uma mensagem possui um único contexto funcional."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import api_whatsapp
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService


PHONE = "5500000000001"


@pytest.fixture
def isolated_app(monkeypatch, tmp_path):
    rdv = RDVService(tmp_path / "rdv.db")
    visitas = VisitasTecnicasService(tmp_path / "visitas.db")
    monkeypatch.setattr(api_whatsapp, "rdv_service", rdv)
    monkeypatch.setattr(api_whatsapp, "visitas_service", visitas)
    for state in (
        api_whatsapp.whatsapp_menu_states,
        api_whatsapp.visita_active_states,
        api_whatsapp.visita_edit_states,
        api_whatsapp.rdv_comment_states,
        api_whatsapp.rdv_receipt_review_states,
    ):
        state.clear()
    api_whatsapp.visita_new_visit_states.clear()
    yield rdv, visitas
    api_whatsapp.whatsapp_menu_states.clear()
    api_whatsapp.visita_active_states.clear()
    api_whatsapp.visita_edit_states.clear()
    api_whatsapp.visita_new_visit_states.clear()
    api_whatsapp.rdv_comment_states.clear()
    api_whatsapp.rdv_receipt_review_states.clear()


def _visit_waiting_for_owner_phone(visitas):
    visit = visitas.iniciar_visita(PHONE, tecnico_nome="Danilo")
    visitas.atualizar_campo(visit["id"], "fazenda", "Fukuda")
    visitas.atualizar_campo(visit["id"], "proprietario", "Danilo teste")
    return visitas.atualizar_campo(
        visit["id"], "estado_fluxo", "aguardando_telefone_proprietario"
    )


def test_d09_continue_recovers_exact_persisted_question(isolated_app):
    _, visitas = isolated_app
    visit = _visit_waiting_for_owner_phone(visitas)

    menu = api_whatsapp.handle_rdv_text_message(PHONE, "menu")
    resumed = api_whatsapp.handle_rdv_text_message(
        PHONE, f"continuar visita {visit['id']}"
    )

    assert "Visita em andamento" in menu
    assert resumed == "Qual o telefone do proprietário?"
    assert visitas.obter_visita(visit["id"])["estado_fluxo"] == (
        "aguardando_telefone_proprietario"
    )

    advanced = api_whatsapp.handle_rdv_text_message(PHONE, "61999998888")
    saved = visitas.obter_visita(visit["id"])
    assert advanced == "Qual o nome do gerente ou responsável local pela propriedade?"
    assert saved["telefone_proprietario"] == "61999998888"
    assert saved["estado_fluxo"] == "aguardando_gerente"


def test_audio_during_phone_step_is_not_downloaded_or_transcribed(
    isolated_app, monkeypatch
):
    _, visitas = isolated_app
    visit = _visit_waiting_for_owner_phone(visitas)
    download = MagicMock()
    transcribe = MagicMock()
    sent = []
    monkeypatch.setattr(api_whatsapp, "download_media", download)
    monkeypatch.setattr(api_whatsapp, "_transcribe_audio_with_result", transcribe)
    monkeypatch.setattr(api_whatsapp, "_safe_send_text", lambda to, text: sent.append(text))

    api_whatsapp._handle_whatsapp_message(
        {
            "from": PHONE,
            "id": "wamid.audio-phone",
            "type": "audio",
            "timestamp": "1780000000",
            "audio": {"id": "audio-1", "mime_type": "audio/ogg"},
        }
    )

    download.assert_not_called()
    transcribe.assert_not_called()
    assert "aguardando o telefone do proprietário" in sent[-1]
    assert visitas.obter_visita(visit["id"])["estado_fluxo"] == (
        "aguardando_telefone_proprietario"
    )


def test_close_does_not_open_review_while_phone_is_pending(
    isolated_app, monkeypatch
):
    _, visitas = isolated_app
    visit = _visit_waiting_for_owner_phone(visitas)
    preview = MagicMock()
    monkeypatch.setattr(api_whatsapp, "_send_visita_pdf_data", preview)

    reply = api_whatsapp.handle_rdv_text_message(PHONE, "fechar visita")

    assert "Antes de revisar" in reply
    assert "telefone do proprietário" in reply
    assert "pular" in reply
    preview.assert_not_called()
    assert visitas.obter_visita(visit["id"])["estado_fluxo"] == (
        "aguardando_telefone_proprietario"
    )


def test_photo_during_visit_never_enters_rdv(isolated_app, monkeypatch, tmp_path):
    _, visitas = isolated_app
    visit = visitas.iniciar_visita(
        PHONE, tecnico_nome="Danilo", fazenda="Fukuda", estado_fluxo="visita_aberta"
    )
    downloaded = tmp_path / "foto.jpg"
    downloaded.write_bytes(b"fake-image")
    analyzer = MagicMock()
    sent = []
    monkeypatch.setattr(api_whatsapp, "download_media", lambda *args: downloaded)
    monkeypatch.setattr(api_whatsapp, "_analyze_rdv_receipt_file", analyzer)
    monkeypatch.setattr(api_whatsapp, "_safe_send_text", lambda to, text: sent.append(text))

    api_whatsapp._handle_whatsapp_message(
        {
            "from": PHONE,
            "id": "wamid.visit-photo",
            "type": "image",
            "timestamp": "1780000001",
            "image": {"id": "image-1", "mime_type": "image/jpeg"},
        }
    )

    analyzer.assert_not_called()
    assert len(visitas.obter_visita_completa(visit["id"])["midias"]) == 1
    assert "Foto" in sent[-1] and "visita" in sent[-1]
    assert "RDV" not in sent[-1] and "Valor: R$" not in sent[-1]


def test_photo_without_explicit_context_keeps_rdv_dormant(
    isolated_app, monkeypatch
):
    download = MagicMock()
    analyzer = MagicMock()
    sent = []
    monkeypatch.setattr(api_whatsapp, "download_media", download)
    monkeypatch.setattr(api_whatsapp, "_analyze_rdv_receipt_file", analyzer)
    monkeypatch.setattr(api_whatsapp, "_safe_send_text", lambda to, text: sent.append(text))

    api_whatsapp._handle_whatsapp_message(
        {
            "from": PHONE,
            "id": "wamid.orphan-photo",
            "type": "image",
            "timestamp": "1780000002",
            "image": {"id": "image-2", "mime_type": "image/jpeg"},
        }
    )

    download.assert_not_called()
    analyzer.assert_not_called()
    assert "não há uma visita ou lançamento de RDV" in sent[-1]
    assert PHONE not in api_whatsapp.rdv_receipt_review_states
