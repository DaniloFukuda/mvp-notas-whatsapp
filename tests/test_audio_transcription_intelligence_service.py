import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.audio_transcription_intelligence_service import (
    AudioTranscriptionIntelligenceService,
)
from services.transcription_llm_review_service import LlmReviewResult


def test_modo_codex_organiza_texto_confuso_sem_perder_glossario():
    service = AudioTranscriptionIntelligenceService()

    result = service.process(
        "usar cadax com botes sim não e contitor de 1 a 99 sem zero à esquerda",
        mode="codex",
        provider="local",
    )

    assert result.ok is True
    assert result.provider == "local"
    assert "Codex" in result.output_text
    assert "botões" in result.output_text
    assert "contentor" in result.output_text
    assert "Ajustes necessários:" in result.output_text
    assert "Critérios de aceite:" in result.output_text
    assert "1" in result.output_text
    assert "99" in result.output_text


def test_provider_externo_com_falha_cai_para_local():
    service = AudioTranscriptionIntelligenceService(
        external_providers={
            "openai": lambda raw, mode: (_ for _ in ()).throw(
                RuntimeError("indisponível")
            )
        }
    )

    result = service.process("usar cadax nos botes", mode="revisada", provider="openai")

    assert result.ok is True
    assert result.provider == "local"
    assert result.used_fallback is True
    assert "Codex" in result.output_text
    assert "botões" in result.output_text


def test_provider_externo_nao_configurado_tambem_usa_fallback_local():
    result = AudioTranscriptionIntelligenceService().process(
        "o contitor está alugado",
        mode="relatorio",
        provider="gemini",
    )

    assert result.provider == "local"
    assert result.used_fallback is True
    assert "contentor" in result.output_text


def test_flag_desabilitada_nao_organiza_nem_chama_provider(monkeypatch):
    called = []
    service = AudioTranscriptionIntelligenceService(
        external_providers={
            "openai": lambda raw, mode: called.append((raw, mode)) or "externo"
        }
    )
    monkeypatch.setenv("TRANSCRIPTION_REVIEW_ENABLED", "false")
    raw = "usar cadax nos botes"

    result = service.process(raw, mode="codex", provider="openai")

    assert result.output_text == raw
    assert result.provider == "local"
    assert called == []


def test_literal_nunca_chama_llm(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_LLM_REVIEW_ENABLED", "true")
    called = []
    service = AudioTranscriptionIntelligenceService(
        llm_reviewer=lambda raw, context: called.append((raw, context))
    )

    result = service.process("texto literal", mode="literal")

    assert result.provider == "local"
    assert called == []


def test_revisada_retorna_resultado_da_llm_quando_habilitada(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_LLM_REVIEW_ENABLED", "true")
    called = []

    def reviewer(raw, context):
        called.append((raw, context))
        return LlmReviewResult(True, "openai", "gpt-5.4-mini", "Texto revisado.")

    result = AudioTranscriptionIntelligenceService(llm_reviewer=reviewer).process(
        "texto bruto",
        mode="revisada",
        context="visita_observacao",
    )

    assert result.provider == "openai"
    assert result.output_text == "Texto revisado."
    assert called == [("texto bruto", "visita_observacao")]


def test_revisada_com_falha_da_llm_usa_revisao_local(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_LLM_REVIEW_ENABLED", "true")
    service = AudioTranscriptionIntelligenceService(
        llm_reviewer=lambda raw, context: LlmReviewResult(
            False, "openai", "gpt-5.4-mini", "", "falha", True
        )
    )

    result = service.process("usar cadax nos botes", mode="revisada")

    assert result.provider == "local"
    assert result.used_fallback is True
    assert "Codex" in result.output_text
