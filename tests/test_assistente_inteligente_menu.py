import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService

PHONE_OK = "5500000000001"
PHONE_INACTIVE = "5500000000002"


def _install_services(temp_dir: str):
    import uuid

    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    db_name = "rdv_%s.db" % uuid.uuid4().hex
    visitas_name = "visitas_%s.db" % uuid.uuid4().hex
    rdv = RDVService(Path(temp_dir) / db_name)
    visitas = VisitasTecnicasService(Path(temp_dir) / visitas_name)
    api_whatsapp.rdv_service = rdv
    api_whatsapp.visitas_service = visitas
    # O colaborador de teste (5500000000001) ja existe e esta ativo no
    # banco local de desenvolvimento reutilizado pelo ambiente de teste.
    collab = rdv.get_collaborator_by_phone(PHONE_OK)
    return rdv, visitas, collab, original_rdv, original_visitas


def _restore(original_rdv, original_visitas):
    api_whatsapp.rdv_service = original_rdv
    api_whatsapp.visitas_service = original_visitas
    api_whatsapp.assistente_inteligente_states.clear()


def _capture_list_rows(monkeypatch):
    captured = {}

    def fake_send(to=None, header=None, body=None, button_text=None,
                  sections=None, footer=None, **kwargs):
        captured["sections"] = sections

    monkeypatch.setattr(api_whatsapp, "send_whatsapp_list_message", fake_send)
    return captured


def test_menu_texto_base_expoe_somente_visitas():
    texto = api_whatsapp.MAIN_MENU_MESSAGE
    assert "🌱 Visitas técnicas" in texto
    assert "RDV" not in texto
    assert "Comprovantes" not in texto
    assert "KM / Viagens" not in texto
    assert "Transcrever áudio" not in texto
    assert "Assistente Inteligente" not in texto


def test_flag_ausente_nao_adiciona_item_interativo(monkeypatch):
    monkeypatch.delenv("ASSISTENTE_INTELIGENTE_ENABLED", raising=False)
    captured = _capture_list_rows(monkeypatch)
    with tempfile.TemporaryDirectory() as td:
        _, _, _, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.send_main_menu_interactive(PHONE_OK)
        finally:
            _restore(orig_r, orig_v)
    ids = [row["id"] for row in captured["sections"][0]["rows"]]
    assert "menu_assistente_inteligente" not in ids


def test_flag_false_nao_adiciona_item_interativo(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "false")
    captured = _capture_list_rows(monkeypatch)
    with tempfile.TemporaryDirectory() as td:
        _, _, _, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.send_main_menu_interactive(PHONE_OK)
        finally:
            _restore(orig_r, orig_v)
    ids = [row["id"] for row in captured["sections"][0]["rows"]]
    assert "menu_assistente_inteligente" not in ids


def test_flag_true_adiciona_item_interativo(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    captured = _capture_list_rows(monkeypatch)
    with tempfile.TemporaryDirectory() as td:
        _, _, _, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.send_main_menu_interactive(PHONE_OK)
        finally:
            _restore(orig_r, orig_v)
    ids = [row["id"] for row in captured["sections"][0]["rows"]]
    assert "menu_assistente_inteligente" in ids


def test_item_interativo_convertido_para_comando_assistente():
    assert (
        api_whatsapp.INTERACTIVE_COMMAND_IDS.get("menu_assistente_inteligente")
        == "assistente"
    )


def test_comando_textual_assistente_aceito():
    assert "assistente" in api_whatsapp.ASSISTENTE_INTELIGENTE_COMMANDS
    assert "assistente inteligente" in api_whatsapp.ASSISTENTE_INTELIGENTE_COMMANDS


def test_comandos_saida_assistente():
    saida = api_whatsapp.ASSISTENTE_INTELIGENTE_EXIT_COMMANDS
    assert {"sair", "menu", "cancelar", "voltar"}.issubset(saida)
