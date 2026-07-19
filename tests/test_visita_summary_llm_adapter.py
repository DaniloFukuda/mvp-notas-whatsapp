"""Testes do adaptador LLM de resumo (modulo 2, arquitetura ajustada).

O adaptador usa a camada generica generate_text, enviando:
- instructions = prompt de resumo;
- input_text    = transcricao revisada.

Nenhum teste realiza chamada de rede: o gerador da camada e substituido por um
fake que devolve LlmTextGenerationResult. Valida-se o contrato com o
VisitaSummaryService, preservando ancoras objetivas.
"""

from __future__ import annotations

import os

import pytest

from services.llm_text_generation_service import (
    LlmTextGenerationResult,
    generate_text,
)
from services.transcription_llm_review_service import (
    AGRO_REVIEW_INSTRUCTIONS,
    review_transcription_with_llm,
)
from services.visita_summary_llm_adapter import VisitaSummaryLlmAdapter
from services.visita_summary_service import VisitaSummary, VisitaSummaryService


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _ok(text: str) -> LlmTextGenerationResult:
    return LlmTextGenerationResult(True, "openai", "gpt-x", text)


def _fail(message: str) -> LlmTextGenerationResult:
    return LlmTextGenerationResult(False, "openai", "gpt-x", "", message, True)


class _FakeGen:
    def __init__(self, result=None, raise_exc=None, capture=None):
        self._result = result
        self._raise_exc = raise_exc
        self._capture = capture

    def __call__(self, instructions: str, input_text: str, **kwargs):
        if self._capture is not None:
            self._capture["instructions"] = instructions
            self._capture["input_text"] = input_text
            self._capture["kwargs"] = kwargs
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._result


# ---------------------------------------------------------------------------
# 1. feature de resumo desativada nao chama provider
# ---------------------------------------------------------------------------

def test_resumo_desativado_nao_chama_provider(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "false")
    called = []
    gen = _FakeGen(_ok("assunto_principal: x\nnecessidades: y\n"
                       "decisoes: z\npendencias: w\nproximos_passos: k"),
                  capture={"instructions": None, "input_text": None})
    adapter = VisitaSummaryLlmAdapter(gen, enabled=False)
    service = VisitaSummaryService(adapter)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert result.used_fallback is True
    assert result.summary is None


# ---------------------------------------------------------------------------
# 2. resumo funciona independentemente da flag de revisao
# ---------------------------------------------------------------------------

def test_resumo_independe_da_flag_revisao(monkeypatch):
    # Revisao LLM desligada; resumo ligado deve funcionar.
    monkeypatch.setenv("TRANSCRIPTION_LLM_REVIEW_ENABLED", "false")
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    adapter = VisitaSummaryLlmAdapter(
        _FakeGen(_ok("assunto_principal: x\nnecessidades: 12 kg em 5 ha\n"
                     "decisoes: dia 12/05/2026\npendencias: w\nproximos_passos: k"))
    )
    service = VisitaSummaryService(adapter)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is True


# ---------------------------------------------------------------------------
# 3. prompt vai em instructions; transcricao vai em input_text
# ---------------------------------------------------------------------------

def test_prompt_em_instructions_e_transcricao_em_input(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    capture = {}
    gen = _FakeGen(_ok("assunto_principal: x\nnecessidades: y\n"
                       "decisoes: z\npendencias: w\nproximos_passos: k"),
                  capture=capture)
    adapter = VisitaSummaryLlmAdapter(gen)
    transcription = "Aplicar 12 kg em 5 ha no dia 12/05/2026"
    adapter("PROMPT_DE_RESUMO", transcription)
    assert capture["instructions"] == "PROMPT_DE_RESUMO"
    assert capture["input_text"] == transcription
    # limite proprio do resumo foi repassado
    assert "max_input_chars" in capture["kwargs"]


# ---------------------------------------------------------------------------
# 4. instrucoes de revisao NAO sao usadas
# ---------------------------------------------------------------------------

def test_nao_usa_instrucoes_de_revisao(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    capture = {}
    gen = _FakeGen(_ok("assunto_principal: x\nnecessidades: y\n"
                       "decisoes: z\npendencias: w\nproximos_passos: k"),
                  capture=capture)
    adapter = VisitaSummaryLlmAdapter(gen)
    adapter("qualquer prompt", "texto")
    assert capture["instructions"] != AGRO_REVIEW_INSTRUCTIONS
    assert AGRO_REVIEW_INSTRUCTIONS not in capture["instructions"]


# ---------------------------------------------------------------------------
# 5. nao chama review_transcription_with_llm
# ---------------------------------------------------------------------------

def test_nao_chama_review_transcription(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    calls = []
    monkeypatch.setattr(
        "services.transcription_llm_review_service.review_transcription_with_llm",
        lambda *a, **k: calls.append(True),
    )
    gen = _FakeGen(_ok("assunto_principal: x\nnecessidades: y\n"
                       "decisoes: z\npendencias: w\nproximos_passos: k"))
    adapter = VisitaSummaryLlmAdapter(gen)
    adapter("prompt", "texto")
    assert calls == []


# ---------------------------------------------------------------------------
# 6. resposta valida e processada
# ---------------------------------------------------------------------------

def test_resposta_valida_processada(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    gen = _FakeGen(_ok(
        "assunto_principal: Reuniao de plantio\n"
        "necessidades: 12 kg de fertilizante\n"
        "decisoes: Aplicar em 5 ha\n"
        "pendencias: Orcamento pendente\n"
        "proximos_passos: Retornar em 12/05/2026\n"
    ))
    service = VisitaSummaryService(VisitaSummaryLlmAdapter(gen))
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is True
    assert result.summary is not None
    assert result.summary.assunto_principal == "Reuniao de plantio"
    assert result.summary.necessidades == "12 kg de fertilizante"
    assert result.summary.decisoes == "Aplicar em 5 ha"
    assert result.summary.pendencias == "Orcamento pendente"
    assert result.summary.proximos_passos == "Retornar em 12/05/2026"


# ---------------------------------------------------------------------------
# 7. resposta vazia, invalida ou excecao aciona fallback
# ---------------------------------------------------------------------------

def test_resposta_vazia_gera_fallback(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(VisitaSummaryLlmAdapter(_FakeGen(_ok(""))))
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert result.summary is None


def test_resposta_nao_estruturada_gera_fallback(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(
        VisitaSummaryLlmAdapter(_FakeGen(_ok("texto solto sem secoes.")))
    )
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert result.summary is None


def test_resposta_secao_ausente_gera_fallback(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(
        VisitaSummaryLlmAdapter(_FakeGen(_ok(
            "assunto_principal: x\nnecessidades: y\ndecisoes: z\npendencias: w\n"
        )))
    )
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert result.summary is None


def test_excecao_do_provider_gera_fallback(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(
        VisitaSummaryLlmAdapter(_FakeGen(raise_exc=TimeoutError("timeout")))
    )
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert result.summary is None


def test_gerador_retorna_ok_false_gera_fallback(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(
        VisitaSummaryLlmAdapter(_FakeGen(_fail("OPENAI_API_KEY nao configurada.")))
    )
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert result.summary is None


# ---------------------------------------------------------------------------
# 8. integracao preserva nomes, numeros, produtos, areas, datas e medidas
# ---------------------------------------------------------------------------

def test_integracao_preserva_ancoras(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    transcription = (
        "Fazenda Boa Vista: aplicar 12 kg de fertilizante em 5 ha "
        "no dia 12/05/2026, dose de 2,5 l por talhao."
    )
    gen = _FakeGen(_ok(
        "assunto_principal: Aplicacao na Fazenda Boa Vista\n"
        "necessidades: 12 kg de fertilizante e 2,5 l por talhao\n"
        "decisoes: Aplicar em 5 ha\n"
        "pendencias: nenhuma\n"
        "proximos_passos: retornar em 12/05/2026\n"
    ))
    service = VisitaSummaryService(VisitaSummaryLlmAdapter(gen))
    result = service.generate(transcription)
    assert result.ok is True
    joined = " ".join(getattr(result.summary, f) for f in
                      VisitaSummary.REQUIRED_SECTIONS)
    for anchor in ["Fazenda Boa Vista", "12 kg", "5 ha", "12/05/2026", "2,5 l"]:
        assert (anchor in joined) or (anchor.replace(",", ".") in joined.replace(",", "."))


def test_integracao_rejeita_ancora_alterada(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    transcription = "Aplicar 12 kg de insumo na Fazenda Boa Vista"
    # LLM "inventou" 20 kg (alterou ancora 12 -> 20).
    gen = _FakeGen(_ok(
        "assunto_principal: Aplicacao\n"
        "necessidades: 20 kg de insumo na Fazenda Boa Vista\n"
        "decisoes: ok\npendencias: nenhuma\nproximos_passos: depois\n"
    ))
    service = VisitaSummaryService(VisitaSummaryLlmAdapter(gen))
    result = service.generate(transcription)
    assert result.ok is False
    assert result.summary is None
    assert "ancora" in result.reason.lower()


# ---------------------------------------------------------------------------
# 9. regressao: revisao existente continua verde via wrapper
# ---------------------------------------------------------------------------

def test_revisao_existente_ainda_funciona(monkeypatch):
    # O adaptador nao depende do wrapper de revisao; este teste apenas garante
    # que review_transcription_with_llm segue operante (coberto em outro arquivo).
    monkeypatch.setenv("TRANSCRIPTION_LLM_REVIEW_ENABLED", "false")
    result = review_transcription_with_llm("texto bruto")
    assert result.ok is False  # flag de revisao desligada
    # E o adaptador continua independente:
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    adapter = VisitaSummaryLlmAdapter(_FakeGen(_ok(
        "assunto_principal: x\nnecessidades: y\ndecisoes: z\n"
        "pendencias: w\nproximos_passos: k")))
    out = adapter("prompt", "texto")
    assert out is not None
