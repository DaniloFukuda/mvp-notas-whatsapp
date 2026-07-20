import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService

PHONE_OK = "5500000000001"        # Danilo, ja existente e ativo no DB local
PHONE_INACTIVE = "5500000000002"  # simulado inativo via mock
PHONE_UNKNOWN = "5500000000999"     # simulado nao cadastrado via mock


def _install_services(temp_dir: str, rdv_phone_override=None):
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

    base = rdv.get_collaborator_by_phone

    def fake_get(phone):
        if rdv_phone_override is not None:
            return rdv_phone_override(phone)
        return base(phone)

    rdv.get_collaborator_by_phone = fake_get
    return rdv, visitas, collab, original_rdv, original_visitas


def _restore(original_rdv, original_visitas):
    api_whatsapp.rdv_service = original_rdv
    api_whatsapp.visitas_service = original_visitas
    api_whatsapp.assistente_inteligente_states.clear()
    api_whatsapp.whatsapp_menu_states.clear()
    api_whatsapp.visita_edit_states.clear()
    api_whatsapp.visita_active_states.clear()
    api_whatsapp.visita_new_visit_states.clear()
    api_whatsapp.rdv_comment_states.clear()
    api_whatsapp.rdv_receipt_review_states.clear()
    api_whatsapp.visita_summary_confirmation_states.clear()
    api_whatsapp.standalone_transcription_modes.clear()


def _inactive_returns_none(phone):
    if phone == PHONE_INACTIVE:
        return None
    if phone == PHONE_UNKNOWN:
        return None
    return None if phone not in (PHONE_OK,) else {
        "id": 1,
        "nome": "Autorizado",
        "telefone_whatsapp": PHONE_OK,
        "ativo": 1,
        "criado_em": "2026-01-01T00:00:00",
    }


def test_flag_ausente_impede_entrada(monkeypatch):
    monkeypatch.delenv("ASSISTENTE_INTELIGENTE_ENABLED", raising=False)
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(td)
        try:
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            # Com a flag ausente, o comando "assistente" nao ativa o canal:
            # o usuario cai no menu do RDV (comportamento defensivo de prod)
            # e NAO entra no Assistente Inteligente.
            assert reply is not None
            assert reply != api_whatsapp.ASSISTENTE_INTELIGENTE_ENTRY_MESSAGE
            assert not api_whatsapp._assistente_active(PHONE_OK)
        finally:
            _restore(orig_r, orig_v)


def test_flag_false_impede_entrada(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "false")
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(td)
        try:
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            # Com a flag em "false", o comando "assistente" nao ativa o canal:
            # o usuario cai no menu do RDV e NAO entra no Assistente Inteligente.
            assert reply is not None
            assert reply != api_whatsapp.ASSISTENTE_INTELIGENTE_ENTRY_MESSAGE
            assert not api_whatsapp._assistente_active(PHONE_OK)
        finally:
            _restore(orig_r, orig_v)


def test_flag_true_ativa_por_comando(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(td)
        try:
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            assert reply == api_whatsapp.ASSISTENTE_INTELIGENTE_ENTRY_MESSAGE
            assert api_whatsapp._assistente_active(PHONE_OK)
        finally:
            _restore(orig_r, orig_v)


def test_id_interativo_ativa_por_comando(monkeypatch):
    # O comando textual que entra no Assistente Inteligente e o
    # equivalente ao item de menu "menu_assistente_inteligente" eh
    # "assistente" (ver INTERACTIVE_COMMAND_IDS / ASSISTENTE_INTELIGENTE_COMMANDS).
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(td)
        try:
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            assert reply == api_whatsapp.ASSISTENTE_INTELIGENTE_ENTRY_MESSAGE
            assert api_whatsapp._assistente_active(PHONE_OK)
        finally:
            _restore(orig_r, orig_v)


def test_resposta_textual_simulada_no_modo(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "Qual o saldo?")
            assert reply == api_whatsapp.ASSISTENTE_INTELIGENTE_SIMULATED_REPLY
            assert "saldo" not in reply
        finally:
            _restore(orig_r, orig_v)


def test_sair_remove_estado_e_volta_menu(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    sent = []
    monkeypatch.setattr(
        api_whatsapp, "send_main_menu_interactive",
        lambda to: sent.append(to),
    )
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "sair")
            assert reply == api_whatsapp.ASSISTENTE_INTELIGENTE_EXIT_MESSAGE
            assert not api_whatsapp._assistente_active(PHONE_OK)
            assert sent == [PHONE_OK]
        finally:
            _restore(orig_r, orig_v)


def test_menu_e_cancelar_e_voltar_saem(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    for comando in ("menu", "cancelar", "voltar"):
        with tempfile.TemporaryDirectory() as td:
            _, _, collab, orig_r, orig_v = _install_services(td)
            try:
                api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
                reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, comando)
                assert reply == api_whatsapp.ASSISTENTE_INTELIGENTE_EXIT_MESSAGE
                assert not api_whatsapp._assistente_active(PHONE_OK)
            finally:
                _restore(orig_r, orig_v)


def test_isolamento_entre_usuarios(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            assert api_whatsapp._assistente_active(PHONE_OK)
            assert not api_whatsapp._assistente_active(PHONE_UNKNOWN)
            api_whatsapp.handle_rdv_text_message(PHONE_UNKNOWN, "sair")
            assert api_whatsapp._assistente_active(PHONE_OK)
            assert not api_whatsapp._assistente_active(PHONE_UNKNOWN)
        finally:
            _restore(orig_r, orig_v)


def test_usuario_nao_autorizado_bloqueado(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    sent = []
    monkeypatch.setattr(
        api_whatsapp, "_safe_send_text",
        lambda to, text: sent.append((to, text)),
    )
    message = {
        "from": PHONE_UNKNOWN,
        "id": "wamid.x",
        "type": "text",
        "text": {"body": "assistente"},
        "timestamp": "1700000000",
    }
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(
            td, rdv_phone_override=_inactive_returns_none
        )
        try:
            api_whatsapp._handle_whatsapp_message(message)
            assert not api_whatsapp._assistente_active(PHONE_UNKNOWN)
            assert any("nao esta cadastrado no RDV" in t for _, t in sent)
        finally:
            _restore(orig_r, orig_v)


def test_colaborador_inativo_nao_entra(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    sent = []
    monkeypatch.setattr(
        api_whatsapp, "_safe_send_text",
        lambda to, text: sent.append((to, text)),
    )
    message = {
        "from": PHONE_INACTIVE,
        "id": "wamid.y",
        "type": "text",
        "text": {"body": "assistente"},
        "timestamp": "1700000000",
    }
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(
            td, rdv_phone_override=_inactive_returns_none
        )
        try:
            api_whatsapp._handle_whatsapp_message(message)
            assert not api_whatsapp._assistente_active(PHONE_INACTIVE)
            assert any("nao esta cadastrado no RDV" in t for _, t in sent)
        finally:
            _restore(orig_r, orig_v)


def test_entrada_bloqueada_durante_visita_ativa(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    with tempfile.TemporaryDirectory() as td:
        rdv, visitas, collab, orig_r, orig_v = _install_services(td)
        try:
            visitas.iniciar_visita(PHONE_OK, "Fazenda Teste")
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            assert reply == api_whatsapp.ASSISTENTE_INTELIGENTE_ENTRY_BLOCKED_MESSAGE
            assert not api_whatsapp._assistente_active(PHONE_OK)
            assert api_whatsapp._has_operational_flow(PHONE_OK)
        finally:
            _restore(orig_r, orig_v)


def test_entrada_bloqueada_durante_rdv_pendente(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    with tempfile.TemporaryDirectory() as td:
        rdv, visitas, collab, orig_r, orig_v = _install_services(td)
        try:
            rdv.register_manual_expense(
                telefone_origem=PHONE_OK,
                valor=None,
                status_fluxo="aguardando_valor",
            )
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            assert reply == api_whatsapp.ASSISTENTE_INTELIGENTE_ENTRY_BLOCKED_MESSAGE
            assert not api_whatsapp._assistente_active(PHONE_OK)
        finally:
            _restore(orig_r, orig_v)


def test_midia_no_modo_assistente_nao_chama_handlers(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    sent = []
    monkeypatch.setattr(
        api_whatsapp, "_safe_send_text",
        lambda to, text: sent.append((to, text)),
    )
    download_called = []
    monkeypatch.setattr(
        api_whatsapp, "download_media",
        lambda *a, **k: download_called.append(True),
    )
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            for mtype in ("audio", "voice", "image", "video", "document"):
                message = {
                    "from": PHONE_OK,
                    "id": "wamid." + mtype,
                    "type": mtype,
                    mtype: {"id": "media-" + mtype},
                    "timestamp": "1700000000",
                }
                api_whatsapp._handle_whatsapp_message(message)
            assert not download_called
            assert all(
                api_whatsapp.ASSISTENTE_INTELIGENTE_MEDIA_REPLY in t for _, t in sent
            )
        finally:
            _restore(orig_r, orig_v)


def test_modo_assistente_nao_chama_api_externa(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    externa = []
    if hasattr(api_whatsapp, "requests"):
        monkeypatch.setattr(
            "requests.post", lambda *a, **k: externa.append(True)
        )
    with tempfile.TemporaryDirectory() as td:
        _, _, collab, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "Pergunta qualquer")
            assert not externa
        finally:
            _restore(orig_r, orig_v)
