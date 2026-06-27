import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.audio_transcription_intelligence_service import (
    AudioTranscriptionIntelligenceService,
)


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
