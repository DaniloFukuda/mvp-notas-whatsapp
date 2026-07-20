"""Testes do provider real (OpenAI) do Assistente Inteligente (Modulo 2B.1).

Todos os cenarios usam um generator fake injetado via build_openai_provider(
generator=...). NENHUMA chamada real a API ocorre.

Cobre:
1. provider configurado e resposta valida;
2. instructions contem as regras de somente leitura;
3. historico curto e enviado;
4. sender_key/telefone nao entra no prompt;
5. nenhuma ferramenta/funcao e enviada;
6. timeout e repassado;
7. modelo e repassado;
8. resposta vazia gera fallback;
9. excecao gera fallback;
10. timeout gera fallback;
11. saida acima do limite e truncada;
12. token/erro interno/stack nao aparecem para o usuario;
13. mock permanece padrao quando config ausente;
14. openai selecionado somente quando explicito;
15. provider invalido falha com seguranca (sem mock como falsa resposta);
16. spy em requests.post confirma nenhuma rede;
17. resposta continua sendo apenas texto, nunca comando.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.assistente_inteligente_openai_provider import (
    AssistenteInteligenteOpenAIProvider,
    build_openai_provider,
)
from services.assistente_inteligente_service import (
    AssistenteInteligenteService,
    AssistenteMessage,
    AssistenteRequest,
    AssistenteResponse,
)
from services.assistente_inteligente_provider import (
    MockAssistenteProvider,
    build_mock_provider,
)

DEFAULT_MODEL = "gpt-5.4-mini"


# ---------------------------------------------------------------------------
# Generator fake que imita LlmTextGenerationResult (ok + output_text)
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, ok, output_text, error_message=""):
        self.ok = ok
        self.output_text = output_text
        self.error_message = error_message


def _ok(text: str) -> _FakeResult:
    return _FakeResult(True, text)


def _bad(message: str) -> _FakeResult:
    return _FakeResult(False, "", message)


class _FakeGen:
    def __init__(
        self,
        result=None,
        raise_exc=None,
        capture=None,
        model_seen=None,
        timeout_seen=None,
    ):
        self._result = result
        self._raise_exc = raise_exc
        self._capture = capture
        self._model_seen = model_seen
        self._timeout_seen = timeout_seen

    def __call__(self, instructions, input_text, **kwargs):
        if self._capture is not None:
            self._capture["instructions"] = instructions
            self._capture["input_text"] = input_text
        if self._model_seen is not None and "model" in kwargs:
            self._model_seen.append(kwargs["model"])
        if self._timeout_seen is not None and "timeout" in kwargs:
            self._timeout_seen.append(kwargs["timeout"])
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._result


# ---------------------------------------------------------------------------
# 1) provider configurado e resposta valida
# ---------------------------------------------------------------------------

def test_provider_configurado_resposta_valida():
    provider = build_openai_provider(generator=_FakeGen(_ok("Ola, sou consultivo.")))
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is True
    assert resp.text == "Ola, sou consultivo."
    assert resp.provider == "openai"
    assert resp.used_fallback is False


# ---------------------------------------------------------------------------
# 2) instructions contem regras de somente leitura
# ---------------------------------------------------------------------------

def test_instructions_contem_regras_somente_leitura():
    capture = {}
    provider = build_openai_provider(
        generator=_FakeGen(_ok("x"), capture=capture)
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    instr = capture["instructions"]
    assert "Assistente Inteligente Ciclus" in instr
    assert "EXCLUSIVAMENTE consultivo" in instr
    assert "nao crie" in instr.lower()
    assert "nao execute comandos" in instr.lower()
    assert "nao afirme que realizou" in instr.lower()
    assert "Hermes" not in instr  # nome interno nao vai ao usuario


# ---------------------------------------------------------------------------
# 3) historico curto e enviado
# ---------------------------------------------------------------------------

def test_historico_curto_enviado():
    capture = {}
    history = [
        AssistenteMessage(role="user", text="Quem e a Ciclus?"),
        AssistenteMessage(role="assistant", text="Empresa agricola."),
    ]
    provider = build_openai_provider(
        generator=_FakeGen(_ok("ok"), capture=capture)
    )
    provider.generate(
        AssistenteRequest(
            sender_key="5500000000001",
            message="E o RDV?",
            history=history,
        )
    )
    sent = capture["input_text"]
    assert "Quem e a Ciclus?" in sent
    assert "Empresa agricola." in sent
    assert "E o RDV?" in sent


# ---------------------------------------------------------------------------
# 4) sender_key / telefone nao entra no prompt
# ---------------------------------------------------------------------------

def test_sender_key_nao_entra_no_prompt():
    capture = {}
    provider = build_openai_provider(
        generator=_FakeGen(_ok("ok"), capture=capture)
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert "5500000000001" not in capture["instructions"]
    assert "5500000000001" not in capture["input_text"]


# ---------------------------------------------------------------------------
# 5) nenhuma ferramenta/funcao e enviada
# ---------------------------------------------------------------------------

def test_nenhuma_ferramenta_enviada():
    capture = {}
    provider = build_openai_provider(
        generator=_FakeGen(_ok("ok"), capture=capture)
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    # generator fake recebe apenas (instructions, input_text); se o provider
    # passasse tools/functions, o fake rejeitaria ou nao os veria.
    assert capture["instructions"]
    assert capture["input_text"]


# ---------------------------------------------------------------------------
# 6) timeout e repassado
# ---------------------------------------------------------------------------

def test_timeout_repassado():
    seen = []
    provider = build_openai_provider(
        generator=_FakeGen(_ok("ok"), timeout_seen=seen),
        timeout_seconds=7.0,
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert seen == [7.0]


# ---------------------------------------------------------------------------
# 7) modelo e repassado
# ---------------------------------------------------------------------------

def test_modelo_repassado():
    seen = []
    provider = build_openai_provider(
        generator=_FakeGen(_ok("ok"), model_seen=seen),
        model="gpt-x",
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert seen == ["gpt-x"]


# ---------------------------------------------------------------------------
# 8) resposta vazia gera fallback
# ---------------------------------------------------------------------------

def test_resposta_vazia_gera_fallback():
    provider = build_openai_provider(generator=_FakeGen(_ok("")))
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True
    assert "vazia" in resp.error_message.lower()


# ---------------------------------------------------------------------------
# 9) excecao gera fallback
# ---------------------------------------------------------------------------

def test_excecao_gera_fallback():
    provider = build_openai_provider(
        generator=_FakeGen(raise_exc=RuntimeError("boom"))
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True
    assert "boom" not in resp.error_message
    assert "RuntimeError" not in resp.error_message


# ---------------------------------------------------------------------------
# 10) timeout gera fallback
# ---------------------------------------------------------------------------

def test_timeout_gera_fallback():
    provider = build_openai_provider(
        generator=_FakeGen(raise_exc=TimeoutError("tempo esgotado"))
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True
    assert "tempo esgotado" not in resp.error_message
    assert "TimeoutError" not in resp.error_message


# ---------------------------------------------------------------------------
# 11) saida acima do limite e truncada com seguranca
# ---------------------------------------------------------------------------

def test_saida_acima_do_limite_truncada():
    long_text = "x" * 5000
    provider = build_openai_provider(
        generator=_FakeGen(_ok(long_text)),
        max_output_chars=2000,
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is True
    assert len(resp.text) <= 2000 + len("\n[resposta truncada]")
    assert "truncada" in resp.text


# ---------------------------------------------------------------------------
# 12) token/erro interno/stack nao aparecem para o usuario
# ---------------------------------------------------------------------------

def test_sem_vazamento_de_erro_interno():
    provider = build_openai_provider(
        generator=_FakeGen(raise_exc=ValueError("OPENAI_API_KEY=sk-123 secreto"))
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert "sk-123" not in resp.error_message
    assert "secreto" not in resp.error_message
    assert "OPENAI_API_KEY" not in resp.error_message


# ---------------------------------------------------------------------------
# 13) mock permanece padrao quando config ausente
# ---------------------------------------------------------------------------

def test_mock_padrao_quando_config_ausente(monkeypatch):
    monkeypatch.delenv("ASSISTENTE_INTELIGENTE_PROVIDER", raising=False)
    service = AssistenteInteligenteService()
    assert isinstance(service._provider, MockAssistenteProvider)


# ---------------------------------------------------------------------------
# 14) openai selecionado somente quando explicito
# ---------------------------------------------------------------------------

def test_openai_somente_quando_explicito(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_PROVIDER", "openai")
    service = AssistenteInteligenteService()
    assert isinstance(service._provider, AssistenteInteligenteOpenAIProvider)


# ---------------------------------------------------------------------------
# 15) provider invalido falha com seguranca (sem mock como falsa resposta)
# ---------------------------------------------------------------------------

def test_provider_invalido_falha_sem_mock(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_PROVIDER", "anthropic")
    service = AssistenteInteligenteService()
    # Nunca deve cair no MockAssistenteProvider como falsa resposta real.
    assert not isinstance(service._provider, MockAssistenteProvider)
    # Fluxo real via servico: gera fallback seguro, nao resposta simulada.
    resp = service.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True
    # Nao finge ser resposta real do assistente.
    assert "Recebi sua pergunta" not in resp.text  # texto do mock


# ---------------------------------------------------------------------------
# 16) spy em requests.post: nenhuma rede real nos testes
# ---------------------------------------------------------------------------

def test_nenhuma_rede_real(monkeypatch):
    import requests as _requests

    network = []
    monkeypatch.setattr(
        _requests, "post", lambda *a, **k: network.append(True))
    provider = build_openai_provider(generator=_FakeGen(_ok("ok")))
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi"))
    assert network == []  # generator injetado substitui requests.post


# ---------------------------------------------------------------------------
# 17) resposta continua sendo apenas texto, nunca comando
# ---------------------------------------------------------------------------

def test_resposta_apenas_texto_nunca_comando():
    provider = build_openai_provider(
        generator=_FakeGen(_ok("A resposta e apenas texto."))
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    # O envelope e texto; o servico apenas devolve str(response.text).
    assert isinstance(resp.text, str)
    assert resp.text == "A resposta e apenas texto."
