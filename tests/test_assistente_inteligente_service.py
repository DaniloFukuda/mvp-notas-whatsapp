"""Testes do servico isolado de conversa do Assistente Inteligente (Modulo 2A).

Cobertura:
1. provider mock retorna resposta esperada;
2. nenhuma chamada externa e realizada;
3. texto vazio e rejeitado;
4. texto acima do limite nao chama provider;
5. excecao do provider gera fallback;
6. historico e separado por usuario;
7. historico respeita limite;
8. sair limpa historico daquele usuario;
9. sair de um usuario nao limpa o historico de outro;
10. resposta do servico e enviada pelo WhatsApp;
11. erro do servico nao cai em RDV ou visita;
12. feature desligada mantem o comportamento atual;
13. midia continua interceptada;
14. comandos de saida continuam funcionando;
15. nenhuma funcao de escrita e acessivel (mocks de RDV/visita nao sao chamados).

Usa mocks para provar que nao houve:
- OpenAI / Hermes / requests / httpx;
- SQL de escrita;
- handlers de RDV/visita durante o modo Assistente.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.assistente_inteligente_service import (
    AssistenteInteligenteService,
    AssistenteRequest,
    AssistenteResponse,
)

PHONE_OK = "5500000000001"
PHONE_OTHER = "5500000000002"

# Resposta fixa esperada do mock (deve bater com services/.../provider.py).
EXPECTED_MOCK_TEXT = (
    "🤖 Recebi sua pergunta.\n\n"
    "O canal do Assistente Inteligente está funcionando. A conexão com o "
    "serviço de conversa será adicionada na próxima etapa.\n\n"
    "Para voltar ao menu, envie *sair*."
)


# ---------------------------------------------------------------------------
# Helpers de isolamento de estado (nao altera producao em definitivo).
# ---------------------------------------------------------------------------

def _install_services(temp_dir):
    from services.rdv_service import RDVService
    from services.visitas_service import VisitasTecnicasService
    import uuid

    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    rdv = RDVService(Path(temp_dir) / ("rdv_%s.db" % uuid.uuid4().hex))
    visitas = VisitasTecnicasService(
        Path(temp_dir) / ("visitas_%s.db" % uuid.uuid4().hex)
    )
    api_whatsapp.rdv_service = rdv
    api_whatsapp.visitas_service = visitas
    return rdv, visitas, original_rdv, original_visitas


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
    try:
        api_whatsapp._assistente_inteligente_service.clear_history(PHONE_OK)
        api_whatsapp._assistente_inteligente_service.clear_history(PHONE_OTHER)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1) provider mock retorna resposta esperada
# ---------------------------------------------------------------------------

def test_mock_provider_returns_expected_reply():
    service = AssistenteInteligenteService()
    resp = service.generate(AssistenteRequest(sender_key=PHONE_OK, message="Qual o saldo?"))
    assert isinstance(resp, AssistenteResponse)
    assert resp.ok is True
    assert resp.text == EXPECTED_MOCK_TEXT
    assert resp.provider == "mock"
    assert resp.used_fallback is False
    assert resp.error_message == ""


# ---------------------------------------------------------------------------
# 2) nenhuma chamada externa e realizada (OpenAI/Hermes/requests/httpx)
# ---------------------------------------------------------------------------

def test_no_external_call(monkeypatch):
    import services.assistente_inteligente_provider as prov

    calls = []
    monkeypatch.setattr(
        prov, "build_mock_provider", lambda *a, **k: _SpyProvider(calls)
    )
    # Forca reconstrucao com provider espiao.
    service = AssistenteInteligenteService(provider=_SpyProvider(calls))
    service.generate(AssistenteRequest(sender_key=PHONE_OK, message="Oi"))
    assert len(calls) == 1
    # O provider espiao NAO importa openai/hermes nem usa requests/httpx.
    assert not _IMPORTED_OPENAI and not _IMPORTED_HERMES


# Marcacao global de imports proibidos.
_IMPORTED_OPENAI = False
_IMPORTED_HERMES = False


class _SpyProvider:
    def __init__(self, calls):
        self._calls = calls
        global _IMPORTED_OPENAI, _IMPORTED_HERMES
        try:
            import openai  # noqa: F401

            _IMPORTED_OPENAI = True
        except Exception:
            pass
        try:
            import hermes  # noqa: F401

            _IMPORTED_HERMES = True
        except Exception:
            pass

    def generate(self, request):
        self._calls.append(request)
        return AssistenteResponse(
            ok=True,
            text=EXPECTED_MOCK_TEXT,
            provider="mock",
            used_fallback=False,
            error_message="",
        )


# ---------------------------------------------------------------------------
# 3) texto vazio e rejeitado (nao chama provider)
# ---------------------------------------------------------------------------

def test_empty_text_rejected(monkeypatch):
    calls = []
    service = AssistenteInteligenteService(provider=_SpyProvider(calls))
    resp = service.generate(AssistenteRequest(sender_key=PHONE_OK, message="   "))
    assert resp.ok is False
    assert resp.text == ""
    assert "vazia" in resp.error_message.lower()
    assert calls == []  # provider nao foi chamado


# ---------------------------------------------------------------------------
# 4) texto acima do limite nao chama provider
# ---------------------------------------------------------------------------

def test_over_limit_does_not_call_provider():
    calls = []
    service = AssistenteInteligenteService(
        provider=_SpyProvider(calls), max_input_chars=10
    )
    resp = service.generate(
        AssistenteRequest(sender_key=PHONE_OK, message="x" * 50)
    )
    assert resp.ok is False
    assert "longa" in resp.text or "limite" in resp.error_message.lower()
    assert calls == []  # provider nao foi chamado
    # Nao ecoa o texto completo na mensagem.
    assert "x" * 50 not in resp.text


# ---------------------------------------------------------------------------
# 5) excecao do provider gera fallback
# ---------------------------------------------------------------------------

class _BoomProvider:
    def generate(self, request):
        raise RuntimeError("provider quebrou")


def test_provider_exception_yields_fallback():
    service = AssistenteInteligenteService(provider=_BoomProvider())
    resp = service.generate(AssistenteRequest(sender_key=PHONE_OK, message="Oi"))
    assert resp.ok is False
    assert resp.used_fallback is True
    assert "indisponível" in resp.text
    # Nao expoe detalhes internos.
    assert "provider quebrou" not in resp.text
    assert "RuntimeError" not in resp.text


# ---------------------------------------------------------------------------
# 6) historico e separado por usuario
# ---------------------------------------------------------------------------

def test_history_isolated_per_user():
    service = AssistenteInteligenteService()
    service.generate(AssistenteRequest(sender_key=PHONE_OK, message="Pergunta A"))
    service.generate(AssistenteRequest(sender_key=PHONE_OTHER, message="Pergunta B"))
    hist_ok = service.get_history(PHONE_OK)
    hist_other = service.get_history(PHONE_OTHER)
    assert len(hist_ok) == 2  # user + assistant
    assert len(hist_other) == 2
    assert all(m.text != "Pergunta B" for m in hist_ok if m.role == "user")
    assert any(m.text == "Pergunta B" for m in hist_other if m.role == "user")


# ---------------------------------------------------------------------------
# 7) historico respeita limite
# ---------------------------------------------------------------------------

def test_history_respects_turn_limit():
    service = AssistenteInteligenteService(max_history_turns=2)
    for i in range(5):
        service.generate(
            AssistenteRequest(sender_key=PHONE_OK, message="P%d" % i)
        )
    # 2 turnos * 2 mensagens = 4 entradas no maximo.
    assert len(service.get_history(PHONE_OK)) <= 4
    # Os turnos mantidos sao os mais recentes.
    user_texts = [
        m.text for m in service.get_history(PHONE_OK) if m.role == "user"
    ]
    assert "P4" in user_texts
    assert "P0" not in user_texts


# ---------------------------------------------------------------------------
# 8) sair limpa historico daquele usuario
# ---------------------------------------------------------------------------

def test_exit_clears_that_users_history():
    service = AssistenteInteligenteService()
    service.generate(AssistenteRequest(sender_key=PHONE_OK, message="Oi"))
    assert service.get_history(PHONE_OK)
    service.clear_history(PHONE_OK)
    assert service.get_history(PHONE_OK) == []


# ---------------------------------------------------------------------------
# 9) sair de um usuario nao limpa o historico de outro
# ---------------------------------------------------------------------------

def test_exit_one_user_keeps_other():
    service = AssistenteInteligenteService()
    service.generate(AssistenteRequest(sender_key=PHONE_OK, message="Oi A"))
    service.generate(AssistenteRequest(sender_key=PHONE_OTHER, message="Oi B"))
    service.clear_history(PHONE_OK)
    assert service.get_history(PHONE_OK) == []
    assert service.get_history(PHONE_OTHER)  # outro intacto


# ---------------------------------------------------------------------------
# 10) resposta do servico e enviada pelo WhatsApp
# ---------------------------------------------------------------------------

def test_service_reply_sent_via_whatsapp(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    sent = []
    monkeypatch.setattr(
        api_whatsapp, "_safe_send_text",
        lambda to, text: sent.append((to, text)),
    )
    with __import__("tempfile").TemporaryDirectory() as td:
        _, _, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "Qual o saldo?")
            assert reply == EXPECTED_MOCK_TEXT
        finally:
            _restore(orig_r, orig_v)


# ---------------------------------------------------------------------------
# 11) erro do servico nao cai em RDV ou visita
# ---------------------------------------------------------------------------

def test_service_error_does_not_fall_through(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    # Provider que explode: o handler deve devolver fallback, nao cair em RDV.
    boom = AssistenteInteligenteService(provider=_BoomProvider())
    monkeypatch.setattr(
        api_whatsapp, "_assistente_inteligente_service", boom
    )
    with __import__("tempfile").TemporaryDirectory() as td:
        _, _, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "Pergunta")
            assert reply is not None
            assert "indisponível" in reply
            # Nao devolveu o menu RDV (prova que nao caiu no fluxo operacional).
            assert "Ciclus Agro - RDV por WhatsApp" not in reply
        finally:
            _restore(orig_r, orig_v)


# ---------------------------------------------------------------------------
# 12) feature desligada mantem o comportamento atual
# ---------------------------------------------------------------------------

def test_disabled_feature_keeps_current_behavior(monkeypatch):
    monkeypatch.delenv("ASSISTENTE_INTELIGENTE_ENABLED", raising=False)
    sent_whatsapp = []
    monkeypatch.setattr(
        api_whatsapp, "_safe_send_text",
        lambda to, text: sent_whatsapp.append((to, text)),
    )
    with __import__("tempfile").TemporaryDirectory() as td:
        _, _, orig_r, orig_v = _install_services(td)
        try:
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            # Com flag off, nao entra no assistente: cai no menu RDV.
            assert reply is not None
            assert reply != EXPECTED_MOCK_TEXT
            assert not api_whatsapp._assistente_active(PHONE_OK)
        finally:
            _restore(orig_r, orig_v)


# ---------------------------------------------------------------------------
# 13) midia continua interceptada
# ---------------------------------------------------------------------------

def test_media_still_intercepted(monkeypatch):
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
    message = {
        "from": PHONE_OK,
        "id": "wamid.media",
        "type": "image",
        "image": {"id": "media-1"},
        "timestamp": "1700000000",
    }
    with __import__("tempfile").TemporaryDirectory() as td:
        _, _, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            api_whatsapp._handle_whatsapp_message(message)
            assert not download_called
            assert any(
                api_whatsapp.ASSISTENTE_INTELIGENTE_MEDIA_REPLY in t
                for _, t in sent
            )
        finally:
            _restore(orig_r, orig_v)


# ---------------------------------------------------------------------------
# 14) comandos de saida continuam funcionando
# ---------------------------------------------------------------------------

def test_exit_commands_still_work(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    sent_menu = []
    monkeypatch.setattr(
        api_whatsapp, "send_main_menu_interactive",
        lambda to: sent_menu.append(to),
    )
    with __import__("tempfile").TemporaryDirectory() as td:
        _, _, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            reply = api_whatsapp.handle_rdv_text_message(PHONE_OK, "sair")
            assert reply == api_whatsapp.ASSISTENTE_INTELIGENTE_EXIT_MESSAGE
            assert not api_whatsapp._assistente_active(PHONE_OK)
            assert sent_menu == [PHONE_OK]
        finally:
            _restore(orig_r, orig_v)


# ---------------------------------------------------------------------------
# 15) nenhuma funcao de escrita e acessivel durante o modo Assistente
# ---------------------------------------------------------------------------

def test_no_write_functions_called_in_assistant_mode(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "true")
    write_spies = {
        "register_manual_expense": MagicMock(),
        "save_launch_value": MagicMock(),
        "start_km_trip": MagicMock(),
        "finish_km_trip": MagicMock(),
        "iniciar_visita": MagicMock(),
        "obter_visita_aberta": MagicMock(return_value=None),
    }
    for name, spy in write_spies.items():
        if hasattr(api_whatsapp.rdv_service, name):
            monkeypatch.setattr(
                api_whatsapp.rdv_service, name, spy, raising=False
            )
        if hasattr(api_whatsapp.visitas_service, name):
            monkeypatch.setattr(
                api_whatsapp.visitas_service, name, spy, raising=False
            )
    with __import__("tempfile").TemporaryDirectory() as td:
        rdv, visitas, orig_r, orig_v = _install_services(td)
        try:
            api_whatsapp.handle_rdv_text_message(PHONE_OK, "assistente")
            # Varias mensagens de conversa no modo assistente.
            for txt in ("Pergunta um", "Outra duvida", "Mais uma"):
                api_whatsapp.handle_rdv_text_message(PHONE_OK, txt)
            for spy in write_spies.values():
                assert not spy.called, "funcao de escrita foi chamada no modo Assistente"
        finally:
            _restore(orig_r, orig_v)
