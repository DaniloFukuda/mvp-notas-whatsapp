"""Testes para o contrato de transcrição de áudio (Módulo A2.1)."""

from __future__ import annotations

import pytest

from services.audio_transcription_contract import (
    AudioMetadata,
    TranscriptionResult,
    validate_anchors,
    _ANCHOR_PATTERNS,
)


# ---------------------------------------------------------------------------
# AudioMetadata
# ---------------------------------------------------------------------------

def test_audio_metadata_defaults():
    meta = AudioMetadata()
    assert meta.provider == "whisper_local"
    assert meta.model_name == "base"
    assert meta.language == "pt"
    assert meta.duration_seconds == 0.0
    assert meta.size_bytes == 0
    assert meta.chunk_count == 1
    assert meta.preprocessed is False
    assert len(meta.request_id) == 12


def test_audio_metadata_custom():
    meta = AudioMetadata(
        provider="whisper_local",
        model_name="small",
        language="pt",
        duration_seconds=125.5,
        size_bytes=2_000_000,
        chunk_count=3,
        preprocessed=True,
        request_id="abc123def456",
    )
    assert meta.provider == "whisper_local"
    assert meta.model_name == "small"
    assert meta.duration_seconds == 125.5
    assert meta.size_bytes == 2_000_000
    assert meta.chunk_count == 3
    assert meta.preprocessed is True
    assert meta.size_mb == pytest.approx(1.907, rel=0.01)


def test_audio_metadata_immutable():
    meta = AudioMetadata()
    with pytest.raises(Exception):
        meta.provider = "other"


# ---------------------------------------------------------------------------
# TranscriptionResult
# ---------------------------------------------------------------------------

def test_transcription_result_success():
    meta = AudioMetadata()
    result = TranscriptionResult.success(
        raw_text="Olá mundo",
        reviewed_text="Olá, mundo.",
        metadata=meta,
        used_fallback=False,
        warnings=(),
    )
    assert result.ok is True
    assert result.raw_text == "Olá mundo"
    assert result.reviewed_text == "Olá, mundo."
    assert result.used_fallback is False
    assert result.warnings == ()
    assert result.error_code is None
    assert result.error_message is None


def test_transcription_result_failure():
    result = TranscriptionResult.failure(
        error_code="AUDIO_TOO_LONG",
        error_message="Áudio excede limite",
    )
    assert result.ok is False
    assert result.raw_text == ""
    assert result.reviewed_text == ""
    assert result.used_fallback is True
    assert result.error_code == "AUDIO_TOO_LONG"
    assert result.error_message == "Áudio excede limite"


def test_transcription_result_failure_with_metadata():
    meta = AudioMetadata(model_name="small", request_id="req123")
    result = TranscriptionResult.failure(
        error_code="TRANSCRIPTION_ERROR",
        error_message="Falha no Whisper",
        metadata=meta,
        raw_text="parcial",
    )
    assert result.ok is False
    assert result.metadata.model_name == "small"
    assert result.metadata.request_id == "req123"
    assert result.raw_text == "parcial"
    assert result.reviewed_text == "parcial"


def test_transcription_result_rejects_empty_raw_on_success():
    meta = AudioMetadata()
    with pytest.raises(ValueError, match="raw_text não vazio"):
        TranscriptionResult.success(
            raw_text="",
            reviewed_text="",
            metadata=meta,
        )


def test_transcription_result_warnings_normalized_to_tuple():
    meta = AudioMetadata()
    result = TranscriptionResult.success(
        raw_text="teste",
        reviewed_text="teste",
        metadata=meta,
        warnings=["warn1", "warn2"],
    )
    assert result.warnings == ("warn1", "warn2")


def test_transcription_result_immutable():
    meta = AudioMetadata()
    result = TranscriptionResult.success(
        raw_text="teste",
        reviewed_text="teste",
        metadata=meta,
    )
    with pytest.raises(Exception):
        result.ok = False
    with pytest.raises(Exception):
        result.raw_text = "outro"


def test_transcription_result_has_numeric_warning():
    meta = AudioMetadata()
    result = TranscriptionResult.success(
        raw_text="teste",
        reviewed_text="teste",
        metadata=meta,
        warnings=("suspicious_numeric_loss:currency",),
    )
    assert result.has_numeric_warning is True

    result2 = TranscriptionResult.success(
        raw_text="teste",
        reviewed_text="teste",
        metadata=meta,
        warnings=("other_warning",),
    )
    assert result2.has_numeric_warning is False


# ---------------------------------------------------------------------------
# validate_anchors
# ---------------------------------------------------------------------------

def test_validate_anchors_preserves_all():
    raw = "A área é 50 ha e custou R$ 10.000,00 em 15/03/2024."
    reviewed = "A área é 50 ha e custou R$ 10.000,00 em 15/03/2024."
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is True
    assert warnings == []


def test_validate_anchors_detects_loss():
    raw = "A área é 50 ha e custou R$ 10.000,00."
    reviewed = "A área é grande e custou caro."  # perdeu número e moeda
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is False
    assert "suspicious_anchor_loss:unit_ha" in warnings
    assert "suspicious_anchor_loss:currency" in warnings


def test_validate_anchors_detects_gain():
    raw = "A área é grande."
    reviewed = "A área é 50 ha e custou R$ 10.000,00."  # ganhou números
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is False
    assert "suspicious_anchor_gain:unit_ha" in warnings
    assert "suspicious_anchor_gain:currency" in warnings


def test_validate_anchors_allows_minor_text_changes():
    raw = "O plantio foi em 15/03/2024 na fazenda Boa Vista."
    reviewed = "O plantio ocorreu em 15/03/2024 na fazenda Boa Vista."
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is True
    assert warnings == []


def test_validate_anchors_percentage():
    raw = "Aplicação de 2.5% do produto."
    reviewed = "Aplicação de 2.5% do produto."
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is True


def test_validate_anchors_loses_percentage():
    raw = "Aplicação de 2.5% do produto."
    reviewed = "Aplicação do produto."
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is False
    assert "suspicious_anchor_loss:percentage" in warnings


def test_validate_anchors_time():
    raw = "Começou às 08:30 e terminou às 12:00."
    reviewed = "Começou às 08:30 e terminou às 12:00."
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is True


def test_validate_anchors_iso_date():
    raw = "Data: 2024-03-15."
    reviewed = "Data: 2024-03-15."
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is True


def test_validate_anchors_loses_iso_date():
    raw = "Data: 2024-03-15."
    reviewed = "Data não informada."
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is False
    assert "suspicious_anchor_loss:date_iso" in warnings


def test_validate_anchors_unit_kg():
    raw = "Produção de 500 kg de soja."
    reviewed = "Produção de 500 kg de soja."
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is True


def test_validate_anchors_gains_kg():
    raw = "Produção de soja."
    reviewed = "Produção de 500 kg de soja."
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is False
    assert "suspicious_anchor_gain:unit_kg" in warnings


def test_validate_anchors_currency_format_variants():
    raw = "Custou R$ 1.000,00."
    reviewed = "Custou R$ 1.000,00."
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is True


def test_validate_anchors_mixed_loss_and_gain():
    raw = "Custou R$ 1.000,00 em 15/03/2024."
    reviewed = "Custou R$ 2.000,00 em 20/03/2024."  # valores diferentes
    is_safe, warnings = validate_anchors(raw, reviewed)
    assert is_safe is False
    assert "suspicious_anchor_loss:currency" in warnings
    assert "suspicious_anchor_gain:currency" in warnings
    assert "suspicious_anchor_loss:date_br" in warnings
    assert "suspicious_anchor_gain:date_br" in warnings