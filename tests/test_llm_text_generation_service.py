"""Testes da camada generica de geracao de texto via LLM (sem rede).

A camada e neutra: NAO conhece revisao, resumo, secoes agricolas ou heuristics.
Todos os cenarios usam um gerador injetado (fake) que devolve
LlmTextGenerationResult, sem tocar requests/rede.
"""

from __future__ import annotations

import os

import pytest

from services.llm_text_generation_service import (
    LlmTextGenerationResult,
    generate_text,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


# ---------------------------------------------------------------------------
# Gerador fake injetavel
# ---------------------------------------------------------------------------

def _ok(text: str):
    return LlmTextGenerationResult(True, "openai", "gpt-x", text)


def _fail(message: str):
    return LlmTextGenerationResult(False, "openai", "gpt-x", "", message, True)


class _FakeGen:
    def __init__(self, result=None, raise_exc=None, capture=None):
        self._result = result
        self._raise_exc = raise_exc
        self._capture = capture

    def __call__(self, instructions: str, input_text: str):
        if self._capture is not None:
            self._capture["instructions"] = instructions
            self._capture["input_text"] = input_text
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._result


# ---------------------------------------------------------------------------
# instrucoes e input enviados em campos separados
# ---------------------------------------------------------------------------

def test_instructions_e_input_separados():
    capture = {}
    gen = _FakeGen(_ok("ok"), capture=capture)
    generate_text("INSTRUCOES X", "TEXTO Y", generator=gen)
    assert capture["instructions"] == "INSTRUCOES X"
    assert capture["input_text"] == "TEXTO Y"


# ---------------------------------------------------------------------------
# resposta valida
# ---------------------------------------------------------------------------

def test_resposta_valida():
    result = generate_text("inst", "texto", generator=_FakeGen(_ok("resultado")))
    assert result.ok is True
    assert result.output_text == "resultado"
    assert result.used_fallback is False


# ---------------------------------------------------------------------------
# resposta vazia
# ---------------------------------------------------------------------------

def test_resposta_vazia():
    result = generate_text("inst", "texto", generator=_FakeGen(_ok("")))
    assert result.ok is False
    assert result.used_fallback is True
    assert "vazia" in result.error_message.lower()


# ---------------------------------------------------------------------------
# HTTP com erro (via gerador que simula falha de HTTP)
# ---------------------------------------------------------------------------

def test_falha_http_simulada():
    result = generate_text(
        "inst", "texto", generator=_FakeGen(_fail("HTTP 500"))
    )
    assert result.ok is False
    assert result.used_fallback is True


# ---------------------------------------------------------------------------
# excecao/timeout
# ---------------------------------------------------------------------------

def test_excecao_do_gerador():
    result = generate_text(
        "inst", "texto", generator=_FakeGen(raise_exc=TimeoutError("timeout"))
    )
    assert result.ok is False
    assert result.used_fallback is True
    assert "TimeoutError" in result.error_message


# ---------------------------------------------------------------------------
# JSON inesperado (payload sem output)
# ---------------------------------------------------------------------------

def test_json_inesperado():
    capture = {}
    gen = _FakeGen(_ok(""), capture=capture)
    # retorna ok mas vazio -> tratado como vazio
    result = generate_text("inst", "texto", generator=gen)
    assert result.ok is False


# ---------------------------------------------------------------------------
# ausencia de chave
# ---------------------------------------------------------------------------

def test_ausencia_de_api_key_sem_gerador(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Sem gerador injetado e sem api key -> fallback, sem rede.
    result = generate_text("inst", "texto")
    assert result.ok is False
    assert "OPENAI_API_KEY" in result.error_message


def test_provider_nao_suportado_sem_gerador(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("TRANSCRIPTION_LLM_PROVIDER", "anthropic")
    result = generate_text("inst", "texto")
    assert result.ok is False
    assert "nao suportado" in result.error_message.lower()


# ---------------------------------------------------------------------------
# nenhuma rede real
# ---------------------------------------------------------------------------

def test_nenhuma_rede_real_com_gerador(monkeypatch):
    network = []
    monkeypatch.setattr(
        "services.llm_text_generation_service.requests.post",
        lambda *a, **k: network.append(True),
    )
    generate_text("inst", "texto", generator=_FakeGen(_ok("x")))
    assert network == []  # gerador injetado substitui requests.post


# ---------------------------------------------------------------------------
# nenhum comportamento especifico de revisao
# ---------------------------------------------------------------------------

def test_camada_neutra_nao_aplica_heuristica_revisao():
    # A camada generica aceita qualquer texto, sem heuristica de "bad review".
    outcome = generate_text(
        "Gere um resumo", "texto curto com poucas palavras repetidas repetidas",
        generator=_FakeGen(_ok("qualquer coisa longa sem ancoras conhecidas")),
    )
    assert outcome.ok is True  # nao rejeita como a revisao faria


def test_nao_usa_ags_review_instructions():
    # A camada nao deve forcar AGRO_REVIEW_INSTRUCTIONS; usa o que recebe.
    capture = {}
    generate_text("MINHAS INSTRUCOES", "texto", generator=_FakeGen(_ok("x"), capture=capture))
    assert "MINHAS INSTRUCOES" == capture["instructions"]
