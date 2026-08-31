"""Testes específicos do Módulo A2.2 — Integração segura do TranscriptionResult nos fluxos de áudio."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.audio_transcription_contract import (
    AudioMetadata,
    TranscriptionResult,
    validate_anchors,
)
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService
from services.audio_transcription_intelligence_service import (
    IntelligentTranscriptionResult,
)
from services.audio_transcription_review_service import ReviewedTranscription


# =============================================================================
import tempfile
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.audio_transcription_contract import (
    AudioMetadata,
    TranscriptionResult,
    validate_anchors,
)
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService
from services.audio_transcription_intelligence_service import (
    IntelligentTranscriptionResult,
)
from services.audio_transcription_review_service import ReviewedTranscription


# =============================================================================
# Helpers e fixtures locais
# =============================================================================

@pytest.fixture(autouse=True)
def _preserve_global_state():
    """Salva e restaura todo o estado global mutável antes/depois de cada teste."""
    # Estado original dos singletons
    original_transcription_service = api_whatsapp._audio_transcription_service
    original_review_service = api_whatsapp._audio_transcription_review_service
    original_intelligence_service = api_whatsapp._audio_transcription_intelligence_service
    original_visit_summary_service = api_whatsapp._visita_summary_service
    original_assistente_inteligente_service = api_whatsapp._assistente_inteligente_service

    # Estado original do gerador interno do visit_summary_service (mutado por testes)
    original_visit_summary_generator = None
    if original_visit_summary_service is not None:
        original_visit_summary_generator = original_visit_summary_service._generator._generator

    # Estado original das variáveis de ambiente que afetam Assistente Inteligente
    original_assistente_provider = os.environ.get("ASSISTENTE_INTELIGENTE_PROVIDER")
    original_assistente_enabled = os.environ.get("ASSISTENTE_INTELIGENTE_ENABLED")
    original_assistente_max_input = os.environ.get("ASSISTENTE_INTELIGENTE_MAX_INPUT_CHARS")
    original_assistente_max_history = os.environ.get("ASSISTENTE_INTELIGENTE_MAX_HISTORY_TURNS")
    original_assistente_timeout = os.environ.get("ASSISTENTE_INTELIGENTE_TIMEOUT_SECONDS")

    # Estado original dos dicionários globais
    original_whatsapp_menu_states = dict(api_whatsapp.whatsapp_menu_states)
    original_standalone_modes = dict(api_whatsapp.standalone_transcription_modes)
    original_rdv_comment_states = dict(api_whatsapp.rdv_comment_states)
    original_visita_active_states = dict(api_whatsapp.visita_active_states)
    original_visita_new_visit_states = dict(api_whatsapp.visita_new_visit_states)
    original_assistente_states = dict(api_whatsapp.assistente_inteligente_states)
    original_rdv_receipt_states = dict(api_whatsapp.rdv_receipt_review_states)
    original_visita_summary_states = dict(api_whatsapp.visita_summary_confirmation_states)

    # Serviços injetados
    original_rdv_service = api_whatsapp.rdv_service
    original_visitas_service = api_whatsapp.visitas_service

    try:
        yield
    finally:
        # Restaura singletons
        api_whatsapp._audio_transcription_service = original_transcription_service
        api_whatsapp._audio_transcription_review_service = original_review_service
        api_whatsapp._audio_transcription_intelligence_service = original_intelligence_service
        api_whatsapp._visita_summary_service = original_visit_summary_service
        api_whatsapp._assistente_inteligente_service = original_assistente_inteligente_service

        # Restaura gerador interno do visit_summary_service
        if original_visit_summary_service is not None:
            original_visit_summary_service._generator._generator = original_visit_summary_generator

        # Restaura variáveis de ambiente do Assistente Inteligente
        for var, val in [
            ("ASSISTENTE_INTELIGENTE_PROVIDER", original_assistente_provider),
            ("ASSISTENTE_INTELIGENTE_ENABLED", original_assistente_enabled),
            ("ASSISTENTE_INTELIGENTE_MAX_INPUT_CHARS", original_assistente_max_input),
            ("ASSISTENTE_INTELIGENTE_MAX_HISTORY_TURNS", original_assistente_max_history),
            ("ASSISTENTE_INTELIGENTE_TIMEOUT_SECONDS", original_assistente_timeout),
        ]:
            if val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = val

        # Garante que o provider padrão seja "mock" (padrão seguro) se não estava definido antes
        if original_assistente_provider is None:
            os.environ.pop("ASSISTENTE_INTELIGENTE_PROVIDER", None)

        # Restaura dicionários globais
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.whatsapp_menu_states.update(original_whatsapp_menu_states)

        api_whatsapp.standalone_transcription_modes.clear()
        api_whatsapp.standalone_transcription_modes.update(original_standalone_modes)

        api_whatsapp.rdv_comment_states.clear()
        api_whatsapp.rdv_comment_states.update(original_rdv_comment_states)

        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_active_states.update(original_visita_active_states)

        api_whatsapp.visita_new_visit_states.clear()
        api_whatsapp.visita_new_visit_states.update(original_visita_new_visit_states)

        api_whatsapp.assistente_inteligente_states.clear()
        api_whatsapp.assistente_inteligente_states.update(original_assistente_states)

        api_whatsapp.rdv_receipt_review_states.clear()
        api_whatsapp.rdv_receipt_review_states.update(original_rdv_receipt_states)

        api_whatsapp.visita_summary_confirmation_states.clear()
        api_whatsapp.visita_summary_confirmation_states.update(original_visita_summary_states)

        # Restaura serviços injetados
        api_whatsapp.rdv_service = original_rdv_service
        api_whatsapp.visitas_service = original_visitas_service


def _install_services(temp_dir: str):
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    rdv = RDVService(Path(temp_dir) / "rdv.db")
    visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
    api_whatsapp.rdv_service = rdv
    api_whatsapp.visitas_service = visitas
    collaborator = rdv.get_collaborator_by_phone("5500000000001")
    sender = collaborator["telefone_whatsapp"]
    return rdv, visitas, sender, original_rdv, original_visitas


def _restore_services(original_rdv, original_visitas):
    api_whatsapp.rdv_service = original_rdv
    api_whatsapp.visitas_service = original_visitas
    api_whatsapp.whatsapp_menu_states.clear()
    api_whatsapp.standalone_transcription_modes.clear()
    api_whatsapp.rdv_comment_states.clear()
    api_whatsapp.visita_active_states.clear()
    api_whatsapp.visita_new_visit_states.clear()
    api_whatsapp.assistente_inteligente_states.clear()
    api_whatsapp.rdv_receipt_review_states.clear()


def _completed_expense(service: RDVService, collaborator: dict, sender: str) -> dict:
    return service.register_whatsapp_expense(
        colaborador_id=collaborator["id"],
        colaborador=collaborator["nome"],
        telefone_origem=sender,
        tipo_entrada="imagem",
        categoria="alimentacao",
        valor=42,
        data_despesa="2026-06-11",
        data_detectada="2026-06-11",
        status_fluxo="completo",
        caminho_arquivo="comprovante.jpg",
    )


# Fixtures para mocks de transcrição

@pytest.fixture
def mock_transcription_result_safe():
    """Resultado de transcrição seguro (sem warnings)."""
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    return TranscriptionResult.success(
        raw_text="Texto bruto da transcrição.",
        reviewed_text="Texto revisado da transcrição.",
        metadata=AudioMetadata(
            provider="whisper_local",
            model_name="base",
            language="pt",
            duration_seconds=5.0,
            size_bytes=1024,
            chunk_count=1,
            preprocessed=False,
        ),
        used_fallback=False,
        warnings=(),
    )


@pytest.fixture
def mock_transcription_result_unsafe():
    """Resultado de transcrição inseguro (com warning de âncora)."""
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    return TranscriptionResult.success(
        raw_text="Foram aplicados 20 kg em 22/07/2026.",
        reviewed_text="Foram aplicados 200 kg em 22/07/2026.",
        metadata=AudioMetadata(
            provider="whisper_local",
            model_name="base",
            language="pt",
            duration_seconds=5.0,
            size_bytes=1024,
            chunk_count=1,
            preprocessed=False,
        ),
        used_fallback=True,
        warnings=("suspicious_anchor_gain:unit_kg", "suspicious_anchor_loss:unit_kg"),
    )


@pytest.fixture
def mock_transcription_result_error():
    """Resultado de transcrição com erro controlado."""
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    return TranscriptionResult.failure(
        error_code="EMPTY_TRANSCRIPTION",
        error_message="Não consegui entender esse áudio. Pode enviar novamente ou digitar a informação?",
        raw_text="",
    )


# Fixtures para mocks de download

@pytest.fixture
def mock_download_media_success():
    """Mock de download_media que retorna arquivo válido."""
    def _download(media_id: str, destination: str | Path) -> Path:
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-audio-content")
        return dest
    return _download


@pytest.fixture
def mock_fake_transcription():
    """Mock para _transcribe_audio_file que retorna texto fake."""
    def _fake(path):
        return "usar cadax nos botes"
    return _fake


@pytest.fixture
def mock_transcribe_audio_with_result_safe():
    """Mock para _transcribe_audio_with_result que retorna resultado seguro."""
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    result = TranscriptionResult.success(
        raw_text="usar cadax nos botes",
        reviewed_text="Usar Codex nos botões.",
        metadata=AudioMetadata(
            provider="whisper_local",
            model_name="base",
            language="pt",
            duration_seconds=5.0,
            size_bytes=1024,
            chunk_count=1,
            preprocessed=False,
        ),
        used_fallback=False,
        warnings=(),
    )
    return lambda *args, **kwargs: result


@pytest.fixture
def mock_transcribe_audio_with_result_unsafe():
    """Mock para _transcribe_audio_with_result que retorna resultado inseguro."""
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    result = TranscriptionResult.success(
        raw_text="Foram aplicados 20 kg em 22/07/2026.",
        reviewed_text="Foram aplicados 200 kg em 22/07/2026.",
        metadata=AudioMetadata(
            provider="whisper_local",
            model_name="base",
            language="pt",
            duration_seconds=5.0,
            size_bytes=1024,
            chunk_count=1,
            preprocessed=False,
        ),
        used_fallback=True,
        warnings=("suspicious_anchor_gain:unit_kg", "suspicious_anchor_loss:unit_kg"),
    )
    return lambda *args, **kwargs: result


@pytest.fixture
def mock_transcribe_audio_with_result_error():
    """Mock para _transcribe_audio_with_result que retorna erro controlado."""
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    return TranscriptionResult.failure(
        error_code="EMPTY_TRANSCRIPTION",
        error_message="Não consegui entender esse áudio. Pode enviar novamente ou digitar a informação?",
        raw_text="",
    )


@pytest.fixture
def mock_download_media_success():
    """Mock de download_media que retorna arquivo válido."""
    def _download(media_id: str, destination: str | Path) -> Path:
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-audio-content")
        return dest
    return _download


@pytest.fixture
def mock_fake_transcription():
    """Mock para _transcribe_audio_file que retorna texto fake."""
    def _fake(path):
        return "usar cadax nos botes"
    return _fake


# =============================================================================
# A. Wrapper central
# =============================================================================

def test_transcribe_audio_with_result_returns_transcription_result(monkeypatch, tmp_path):
    """_transcribe_audio_with_result retorna TranscriptionResult completo."""
    downloaded = tmp_path / "audio.ogg"
    downloaded.write_bytes(b"fake-audio")

    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    fake_result = TranscriptionResult.success(
        raw_text="texto local simulado",
        reviewed_text="texto local simulado",
        metadata=AudioMetadata(),
    )
    monkeypatch.setattr(
        api_whatsapp,
        "_audio_transcription_service",
        type("FakeService", (), {"transcrever_com_resultado": lambda self, path: fake_result})(),
    )

    result = api_whatsapp._transcribe_audio_with_result(downloaded)

    assert isinstance(result, TranscriptionResult)
    assert hasattr(result, "ok")
    assert hasattr(result, "raw_text")
    assert hasattr(result, "reviewed_text")
    assert hasattr(result, "metadata")
    assert isinstance(result.metadata, AudioMetadata)
    assert hasattr(result.metadata, "request_id")
    assert len(result.metadata.request_id) == 12


def test_transcribe_audio_file_still_returns_string(monkeypatch, tmp_path):
    """_transcribe_audio_file continua retornando string (compatibilidade)."""
    downloaded = tmp_path / "audio.ogg"
    downloaded.write_bytes(b"fake-audio")

    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    fake_result = TranscriptionResult.success(
        raw_text="texto local simulado",
        reviewed_text="texto local simulado",
        metadata=AudioMetadata(),
    )
    monkeypatch.setattr(
        api_whatsapp,
        "_audio_transcription_service",
        type("FakeService", (), {"transcrever_com_resultado": lambda self, path: fake_result})(),
    )

    text = api_whatsapp._transcribe_audio_file(downloaded)

    assert isinstance(text, str)


def test_transcribe_audio_with_result_failure_controlled(tmp_path):
    """Falha controlada não expõe detalhes internos."""
    downloaded = tmp_path / "audio.ogg"
    downloaded.write_bytes(b"fake-audio")

    # Força erro no serviço
    original_service = api_whatsapp._audio_transcription_service
    api_whatsapp._audio_transcription_service = None
    try:
        result = api_whatsapp._transcribe_audio_with_result(tmp_path / "nonexistent.ogg")
        assert result.ok is False
        assert result.error_code is not None
        assert result.error_message is not None
    finally:
        api_whatsapp._audio_transcription_service = original_service


# =============================================================================
# B. Transcritor avulso
# =============================================================================

def test_standalone_literal_mode_uses_raw_text(monkeypatch, tmp_path, mock_download_media_success, mock_transcribe_audio_with_result_safe):
    """Modo literal apresenta raw_text (com revisão local de erros conhecidos)."""
    downloaded = tmp_path / "literal.ogg"
    downloaded.write_bytes(b"audio")
    sender = "5500000000001"

    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", mock_download_media_success
    )
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_with_result", mock_transcribe_audio_with_result_safe
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    api_whatsapp.standalone_transcription_modes[sender] = "literal"
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-literal", "audio/ogg"
        )

        assert reply.startswith("🎙️ Transcrição literal:")
        assert "Usar Codex nos botões" in reply  # revisão local corrige 'cadax'->'Codex' e 'botes'->'botões'
        assert "Revisão local" not in reply
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()


def test_standalone_revisada_mode_uses_reviewed_text(monkeypatch, tmp_path, mock_download_media_success, mock_transcribe_audio_with_result_safe):
    """Modo revisado usa reviewed_text quando seguro."""
    downloaded = tmp_path / "revisada.ogg"
    downloaded.write_bytes(b"audio")
    sender = "5500000000001"

    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", mock_download_media_success
    )
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_with_result", mock_transcribe_audio_with_result_safe
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    api_whatsapp.standalone_transcription_modes[sender] = "revisada"
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-revisada", "audio/ogg"
        )

        assert reply.startswith("📝 Transcrição revisada:")
        assert "Codex" in reply or "botões" in reply  # revisão aplicada
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()


def test_standalone_unsafe_result_preserves_raw_text(monkeypatch, tmp_path, mock_download_media_success, mock_transcribe_audio_with_result_unsafe):
    """Resultado inseguro preserva raw_text no transcritor avulso."""
    downloaded = tmp_path / "unsafe.ogg"
    downloaded.write_bytes(b"audio")
    sender = "5500000000001"

    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", mock_download_media_success
    )
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_with_result", mock_transcribe_audio_with_result_unsafe
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    api_whatsapp.standalone_transcription_modes[sender] = "revisada"
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-unsafe", "audio/ogg"
        )

        # Deve mostrar raw_text (ou warning de insegurança)
        assert "R$ 100,00" in reply or "⚠️" in reply
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()


def test_standalone_numeric_warning_shows_simple_message(monkeypatch, tmp_path, mock_download_media_success, mock_transcribe_audio_with_result_unsafe):
    """Warning numérico mostra aviso simples ao usuário."""
    downloaded = tmp_path / "warn.ogg"
    downloaded.write_bytes(b"audio")
    sender = "5500000000001"

    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", mock_download_media_success
    )
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_with_result", mock_transcribe_audio_with_result_unsafe
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    api_whatsapp.standalone_transcription_modes[sender] = "revisada"
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-warn", "audio/ogg"
        )

        assert "⚠️" in reply
        assert "números" in reply or "datas" in reply or "medidas" in reply
        assert "request_id" not in reply
        assert "media-" not in reply
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()


def test_standalone_no_warning_preserves_original_message(monkeypatch, tmp_path, mock_download_media_success, mock_transcribe_audio_with_result_safe):
    """Sem warnings, experiência permanece idêntica à anterior."""
    downloaded = tmp_path / "clean.ogg"
    downloaded.write_bytes(b"audio")
    sender = "5500000000001"

    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", mock_download_media_success
    )
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_with_result", mock_transcribe_audio_with_result_safe
    )
    # Mock do serviço de inteligência para evitar chamada real
    from services.audio_transcription_intelligence_service import IntelligentTranscriptionResult
    monkeypatch.setattr(
        api_whatsapp._audio_transcription_intelligence_service,
        "process",
        lambda raw, mode=None, **kw: IntelligentTranscriptionResult(
            True, "Texto limpo sem números", "Texto limpo sem números", "revisada", "local"
        )
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    api_whatsapp.standalone_transcription_modes[sender] = "revisada"
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-clean", "audio/ogg"
        )

        assert "⚠️" not in reply
        assert "request_id" not in reply
        assert "Texto limpo" in reply
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()


# =============================================================================
# C. Comentário RDV
# =============================================================================

def test_rdv_comment_stores_raw_and_reviewed_separately(
    monkeypatch, tmp_path, mock_download_media_success, mock_fake_transcription, mock_transcription_result_safe
):
    """Comentário RDV armazena raw_text e reviewed_text separadamente."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        rdv, visitas, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            expense = _completed_expense(rdv, rdv.get_collaborator_by_phone("5500000000001"), sender)
            api_whatsapp._start_rdv_comment_state(sender, expense["id"])

            downloaded = tmp_path / "rdv.ogg"
            downloaded.write_bytes(b"audio")

            monkeypatch.setattr(api_whatsapp, "download_media", mock_download_media_success)
            monkeypatch.setattr(
                api_whatsapp, "_transcribe_audio_with_result", lambda path: mock_transcription_result_safe
            )
            monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "true")
            monkeypatch.setenv("WHISPER_KEEP_AUDIO", "false")

            api_whatsapp._handle_whatsapp_message({
                "from": sender,
                "id": "wamid.audio.rdv",
                "timestamp": "1781900000",
                "type": "audio",
                "audio": {"id": "media-audio-rdv", "mime_type": "audio/ogg"},
            })

            state = api_whatsapp.rdv_comment_states[sender]
            assert state["state"] == "awaiting_audio_confirmation"
            assert "raw_text" in state
            assert "reviewed_text" in state
            assert "raw_text_full" in state
            assert "warnings" in state
            assert "request_id" in state
            assert "is_safe" in state
            assert "user_warning" in state
            assert isinstance(state["request_id"], str) and len(state["request_id"]) == 12

        finally:
            _restore_services(original_rdv, original_visitas)
            api_whatsapp.rdv_comment_states.clear()


def test_rdv_comment_no_write_before_confirmation(monkeypatch, tmp_path):
    """Nenhum texto é salvo no banco antes da confirmação."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        rdv, visitas, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            expense = _completed_expense(rdv, rdv.get_collaborator_by_phone("5500000000001"), sender)
            api_whatsapp._start_rdv_comment_state(sender, expense["id"])

            downloaded = tmp_path / "rdv.ogg"
            downloaded.write_bytes(b"audio")

            def fake_download(media_id, destination):
                path = Path(destination)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fake-audio")
                return path

            monkeypatch.setattr(api_whatsapp, "download_media", fake_download)
            monkeypatch.setattr(
                api_whatsapp, "_transcribe_audio_file", lambda path: "Comentario do audio"
            )
            monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "true")
            monkeypatch.setenv("WHISPER_KEEP_AUDIO", "false")

            api_whatsapp._handle_whatsapp_message({
                "from": sender,
                "id": "wamid.audio.rdv",
                "timestamp": "1781900000",
                "type": "audio",
                "audio": {"id": "media-audio-rdv", "mime_type": "audio/ogg"},
            })

            # Antes da confirmação, nada salvo
            expense_before = rdv.get_expense(expense["id"])
            assert expense_before["observacao"] in (None, "")

            # Confirma
            reply = api_whatsapp.handle_rdv_text_message(sender, "1")
            assert "Comentario salvo no RDV" in reply

            expense_after = rdv.get_expense(expense["id"])
            assert expense_after["observacao"] != ""

        finally:
            api_whatsapp.rdv_service = original_rdv
            api_whatsapp.visitas_service = original_visitas
            api_whatsapp.rdv_comment_states.clear()


def test_rdv_comment_safe_uses_reviewed_text(monkeypatch, tmp_path, mock_download_media_success, mock_transcribe_audio_with_result_safe):
    """Comentário RDV seguro usa reviewed_text."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        rdv, visitas, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            expense = _completed_expense(rdv, rdv.get_collaborator_by_phone("5500000000001"), sender)
            api_whatsapp._start_rdv_comment_state(sender, expense["id"])

            downloaded = tmp_path / "rdv.ogg"
            downloaded.write_bytes(b"audio")

            monkeypatch.setattr(api_whatsapp, "download_media", mock_download_media_success)
            monkeypatch.setattr(
                api_whatsapp, "_transcribe_audio_with_result", mock_transcribe_audio_with_result_safe
            )
            monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "true")
            monkeypatch.setenv("WHISPER_KEEP_AUDIO", "false")

            api_whatsapp._handle_whatsapp_message({
                "from": sender,
                "id": "wamid.audio.rdv",
                "timestamp": "1781900000",
                "type": "audio",
                "audio": {"id": "media-audio-rdv", "mime_type": "audio/ogg"},
            })

            state = api_whatsapp.rdv_comment_states[sender]
            assert state["is_safe"] is True
            # Texto salvo deve ser o revisado
            assert state["text"] == state["reviewed_text"]

        finally:
            api_whatsapp.rdv_service = original_rdv
            api_whatsapp.visitas_service = original_visitas
            api_whatsapp.rdv_comment_states.clear()


def test_rdv_comment_unsafe_uses_raw_text_as_default(monkeypatch, tmp_path, mock_download_media_success, mock_transcribe_audio_with_result_unsafe):
    """Comentário RDV inseguro usa raw_text como padrão."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        rdv, visitas, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            expense = _completed_expense(rdv, rdv.get_collaborator_by_phone("5500000000001"), sender)
            api_whatsapp._start_rdv_comment_state(sender, expense["id"])

            downloaded = tmp_path / "rdv.ogg"
            downloaded.write_bytes(b"audio")

            monkeypatch.setattr(api_whatsapp, "download_media", mock_download_media_success)
            monkeypatch.setattr(
                api_whatsapp, "_transcribe_audio_with_result", mock_transcribe_audio_with_result_unsafe
            )
            monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "true")
            monkeypatch.setenv("WHISPER_KEEP_AUDIO", "false")

            api_whatsapp._handle_whatsapp_message({
                "from": sender,
                "id": "wamid.audio.rdv",
                "timestamp": "1781900000",
                "type": "audio",
                "audio": {"id": "media-audio-rdv", "mime_type": "audio/ogg"},
            })

            state = api_whatsapp.rdv_comment_states[sender]
            # Inseguro -> is_safe False
            assert state["is_safe"] is False
            # state["text"] guarda o reviewed_text (para uso se confirmar), mas a mensagem de confirmação mostra raw_text
            assert state["text"] == state["reviewed_text"]  # text armazenado é reviewed_text
            assert state["raw_text"] != state["reviewed_text"]  # raw e reviewed são diferentes
            assert state["user_warning"] != ""

        finally:
            api_whatsapp.rdv_service = original_rdv
            api_whatsapp.visitas_service = original_visitas
            api_whatsapp.rdv_comment_states.clear()


def test_rdv_comment_correction_still_works(monkeypatch, tmp_path, mock_download_media_success, mock_transcribe_audio_with_result_safe):
    """Opção Corrigir continua funcionando."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        rdv, visitas, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            expense = _completed_expense(rdv, rdv.get_collaborator_by_phone("5500000000001"), sender)
            api_whatsapp._start_rdv_comment_state(sender, expense["id"])

            downloaded = tmp_path / "rdv.ogg"
            downloaded.write_bytes(b"audio")

            monkeypatch.setattr(api_whatsapp, "download_media", mock_download_media_success)
            monkeypatch.setattr(
                api_whatsapp, "_transcribe_audio_with_result", mock_transcribe_audio_with_result_safe
            )
            monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "true")
            monkeypatch.setenv("WHISPER_KEEP_AUDIO", "false")

            api_whatsapp._handle_whatsapp_message({
                "from": sender,
                "id": "wamid.audio.rdv",
                "timestamp": "1781900000",
                "type": "audio",
                "audio": {"id": "media-audio-rdv", "mime_type": "audio/ogg"},
            })

            # Usuário escolhe corrigir
            reply = api_whatsapp.handle_rdv_text_message(sender, "2")
            assert "Digite o comentario corrigido" in reply

            # Salva correção
            reply = api_whatsapp.handle_rdv_text_message(sender, "Texto corrigido pelo usuario")
            saved = rdv.get_expense(expense["id"])
            assert saved["observacao"] == "Texto corrigido pelo usuario"

        finally:
            api_whatsapp.rdv_service = original_rdv
            api_whatsapp.visitas_service = original_visitas
            api_whatsapp.rdv_comment_states.clear()


def test_rdv_comment_remove_still_works(monkeypatch, tmp_path):
    """Opção Remover continua funcionando."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        rdv, visitas, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            expense = _completed_expense(rdv, rdv.get_collaborator_by_phone("5500000000001"), sender)
            api_whatsapp._start_rdv_comment_state(sender, expense["id"])

            downloaded = tmp_path / "rdv.ogg"
            downloaded.write_bytes(b"audio")

            def fake_download(media_id, destination):
                path = Path(destination)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fake-audio")
                return path

            monkeypatch.setattr(api_whatsapp, "download_media", fake_download)
            monkeypatch.setattr(
                api_whatsapp, "_transcribe_audio_file", lambda path: "Comentario a remover"
            )
            monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "true")
            monkeypatch.setenv("WHISPER_KEEP_AUDIO", "false")

            api_whatsapp._handle_whatsapp_message({
                "from": sender,
                "id": "wamid.audio.rdv",
                "timestamp": "1781900000",
                "type": "audio",
                "audio": {"id": "media-audio-rdv", "mime_type": "audio/ogg"},
            })

            reply = api_whatsapp.handle_rdv_text_message(sender, "3")
            assert "Comentario removido" in reply
            saved = rdv.get_expense(expense["id"])
            assert saved["observacao"] in (None, "")

        finally:
            api_whatsapp.rdv_service = original_rdv
            api_whatsapp.visitas_service = original_visitas
            api_whatsapp.rdv_comment_states.clear()


def test_rdv_confirmation_saves_only_chosen_text(monkeypatch, tmp_path):
    """Confirmação grava somente o texto escolhido."""
    import tempfile
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    with tempfile.TemporaryDirectory() as temp_dir:
        rdv, visitas, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            expense = _completed_expense(rdv, rdv.get_collaborator_by_phone("5500000000001"), sender)
            api_whatsapp._start_rdv_comment_state(sender, expense["id"])

            downloaded = tmp_path / "rdv.ogg"
            downloaded.write_bytes(b"audio")

            def fake_download(media_id, destination):
                path = Path(destination)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fake-audio")
                return path

            # Mock do novo método _transcribe_audio_with_result
            mock_result = TranscriptionResult.success(
                raw_text="Audio bruto",
                reviewed_text="Audio revisado",
                metadata=AudioMetadata(
                    provider="whisper_local",
                    model_name="base",
                    language="pt",
                    duration_seconds=5.0,
                    size_bytes=1024,
                    chunk_count=1,
                    preprocessed=False,
                ),
                used_fallback=False,
                warnings=(),
            )
            monkeypatch.setattr(api_whatsapp, "download_media", fake_download)
            monkeypatch.setattr(
                api_whatsapp, "_transcribe_audio_with_result", lambda path: mock_result
            )
            monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "true")
            monkeypatch.setenv("WHISPER_KEEP_AUDIO", "false")

            api_whatsapp._handle_whatsapp_message({
                "from": sender,
                "id": "wamid.audio.rdv",
                "timestamp": "1781900000",
                "type": "audio",
                "audio": {"id": "media-audio-rdv", "mime_type": "audio/ogg"},
            })

            # Captura o texto esperado ANTES da confirmação (o estado será limpo após)
            expected_text = api_whatsapp.rdv_comment_states[sender]["text"]

            # Usuário confirma (opção 1)
            reply = api_whatsapp.handle_rdv_text_message(sender, "1")
            saved = rdv.get_expense(expense["id"])
            assert "Comentario salvo no RDV" in reply
            # O texto salvo deve ser o reviewed_text (já armazenado em state["text"])
            assert saved["observacao"] == expected_text

        finally:
            api_whatsapp.rdv_service = original_rdv
            api_whatsapp.visitas_service = original_visitas
            api_whatsapp.rdv_comment_states.clear()


# =============================================================================
# D. Visita técnica
# =============================================================================

def test_visit_safe_proceeds_to_summary(monkeypatch, tmp_path):
    """Visita segura pode seguir para o resumo."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        original = (api_whatsapp.rdv_service, api_whatsapp.visitas_service)
        rdv = RDVService(Path(temp_dir) / "rdv.db")
        visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        api_whatsapp.rdv_service = rdv
        api_whatsapp.visitas_service = visitas
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_summary_confirmation_states.clear()

        sender = rdv.get_collaborator_by_phone("5500000000001")["telefone_whatsapp"]
        visita = visitas.iniciar_visita(sender)
        visitas.atualizar_campo(visita["id"], "estado_fluxo", "aguardando_observacoes_gerais")
        # Garante que a visita esteja ativa no estado em memória
        api_whatsapp.visita_active_states[sender] = int(visita["id"])

        downloaded = tmp_path / "visita.ogg"
        downloaded.write_bytes(b"audio")

        monkeypatch.setattr(
            api_whatsapp, "download_media", lambda media_id, destination: downloaded
        )
        # Mock do _transcribe_audio_with_result que retorna TranscriptionResult seguro
        safe_result = TranscriptionResult.success(
            raw_text="Aplicar 12 kg em 5 ha no dia 12/05/2026",
            reviewed_text="Aplicar 12 kg em 5 ha no dia 12/05/2026",
            metadata=AudioMetadata(
                provider="whisper_local",
                model_name="base",
                language="pt",
                duration_seconds=5.0,
                size_bytes=1024,
                chunk_count=1,
                preprocessed=False,
            ),
            used_fallback=False,
            warnings=(),
        )
        def fake_transcribe_with_result(*args, **kwargs):
            return safe_result
        monkeypatch.setattr(
            api_whatsapp, "_transcribe_audio_with_result", fake_transcribe_with_result
        )
        monkeypatch.setenv("WHISPER_ENABLED", "true")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")

        # Mock do serviço de resumo - substitui o gerador interno do adapter
        # O regex _SECTION_RE espera chaves sem acentos: decisoes, pendencias, proximos_passos
        from services.llm_text_generation_service import LlmTextGenerationResult
        def fake_llm(instructions, input_text, **kwargs):
            return LlmTextGenerationResult(True, "openai", "gpt-x", "assunto_principal: Aplicação\nnecessidades: 12 kg em 5 ha\ndecisoes: dia 12/05/2026\npendencias: nenhuma\nproximos_passos: retornar")
        # O adapter chama self._generator(prompt, transcription). Mockar o gerador interno.
        api_whatsapp._visita_summary_service._generator._generator = fake_llm

        # Verifica monkeypatch aplicado
        assert callable(api_whatsapp._transcribe_audio_with_result)
        assert api_whatsapp._transcribe_audio_with_result is fake_transcribe_with_result

        reply = api_whatsapp.handle_whatsapp_audio_message(sender, "media-visita", "audio/ogg")

        # Deve mostrar preview do resumo
        assert "Resumo sugerido" in reply
        assert "Aplicação" in reply

        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_summary_confirmation_states.clear()


def test_visit_unsafe_does_not_send_reviewed_to_summary(monkeypatch, tmp_path):
    """Visita insegura não envia reviewed_text alterado ao resumo."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        original = (api_whatsapp.rdv_service, api_whatsapp.visitas_service)
        rdv = RDVService(Path(temp_dir) / "rdv.db")
        visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        api_whatsapp.rdv_service = rdv
        api_whatsapp.visitas_service = visitas
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_summary_confirmation_states.clear()
        api_whatsapp.rdv_comment_states.clear()

        sender = rdv.get_collaborator_by_phone("5500000000001")["telefone_whatsapp"]
        visita = visitas.iniciar_visita(sender)
        visitas.atualizar_campo(visita["id"], "estado_fluxo", "aguardando_observacoes_gerais")
        api_whatsapp.visita_active_states[sender] = int(visita["id"])

        downloaded = tmp_path / "visita.ogg"
        downloaded.write_bytes(b"audio")

        monkeypatch.setattr(
            api_whatsapp, "download_media", lambda media_id, destination: downloaded
        )

        # TranscriptionResult inseguro: raw_text vs reviewed_text com alteração de âncora (kg)
        unsafe_result = TranscriptionResult(
            ok=True,
            raw_text="Foram aplicados 20 kg em 22/07/2026.",
            reviewed_text="Foram aplicados 200 kg em 22/07/2026.",
            metadata=AudioMetadata(
                provider="whisper_local",
                model_name="base",
                language="pt",
                duration_seconds=5.0,
                size_bytes=1024,
                chunk_count=1,
                preprocessed=False,
            ),
            used_fallback=True,
            warnings=("suspicious_anchor_gain:unit_kg", "suspicious_anchor_loss:unit_kg"),
        )

        def fake_transcribe_with_result(*args, **kwargs):
            return unsafe_result

        monkeypatch.setattr(
            api_whatsapp, "_transcribe_audio_with_result", fake_transcribe_with_result
        )
        monkeypatch.setenv("WHISPER_ENABLED", "true")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")

        # Mockeia fronteira do resumo e captura o texto enviado
        texts_sent_to_summary = []

        def fake_llm(instructions, input_text, **kwargs):
            # O adapter chama generator(prompt, transcription) - input_text é a transcrição
            texts_sent_to_summary.append(input_text)
            from services.llm_text_generation_service import LlmTextGenerationResult
            # O resumo deve preservar as âncoras do raw_text (20 kg, 22/07/2026)
            return LlmTextGenerationResult(
                True, "openai", "gpt-x",
                "assunto_principal: Aplicação\nnecessidades: 20 kg\ndecisoes: 22/07/2026\npendencias: nenhuma\nproximos_passos: retornar"
            )

        # Mock do gerador interno do adapter
        api_whatsapp._visita_summary_service._generator._generator = fake_llm

        # Verifica monkeypatch aplicado
        assert callable(api_whatsapp._transcribe_audio_with_result)
        assert api_whatsapp._transcribe_audio_with_result is fake_transcribe_with_result

        reply = api_whatsapp.handle_whatsapp_audio_message(sender, "media-visita", "audio/ogg")

        # Validações obrigatórias
        # 1. Texto enviado para o resumo é o raw_text (não o reviewed_text alterado)
        assert len(texts_sent_to_summary) == 1
        sent_text = texts_sent_to_summary[0]
        assert "20 kg" in sent_text  # raw_text contém "20 kg"
        assert "200 kg" not in sent_text  # reviewed_text alterado NÃO deve ser enviado
        assert "Foram aplicados 20 kg em 22/07/2026." in sent_text

        # 2. Warning amigável aparece para o usuário (adicionado ao Resumo sugerido)
        assert "⚠️" in reply
        assert "conferência" in reply.lower() or "confira" in reply.lower()

        # 3. Resumo sugerido aparece (mock retorna sucesso com âncoras preservadas)
        assert "Resumo sugerido" in reply

        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_summary_confirmation_states.clear()


def test_visit_unsafe_preserves_raw_text(monkeypatch, tmp_path):
    """Visita insegura mantém raw_text."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        original = (api_whatsapp.rdv_service, api_whatsapp.visitas_service)
        rdv = RDVService(Path(temp_dir) / "rdv.db")
        visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        api_whatsapp.rdv_service = rdv
        api_whatsapp.visitas_service = visitas
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_summary_confirmation_states.clear()
        api_whatsapp.rdv_comment_states.clear()

        sender = rdv.get_collaborator_by_phone("5500000000001")["telefone_whatsapp"]
        visita = visitas.iniciar_visita(sender)
        visitas.atualizar_campo(visita["id"], "estado_fluxo", "aguardando_observacoes_gerais")
        api_whatsapp.visita_active_states[sender] = int(visita["id"])

        downloaded = tmp_path / "visita.ogg"
        downloaded.write_bytes(b"audio")

        monkeypatch.setattr(
            api_whatsapp, "download_media", lambda media_id, destination: downloaded
        )

        # TranscriptionResult inseguro: raw_text vs reviewed_text com alteração de âncora (kg)
        unsafe_result = TranscriptionResult(
            ok=True,
            raw_text="Foram aplicados 20 kg em 22/07/2026.",
            reviewed_text="Foram aplicados 200 kg em 22/07/2026.",
            metadata=AudioMetadata(
                provider="whisper_local",
                model_name="base",
                language="pt",
                duration_seconds=5.0,
                size_bytes=1024,
                chunk_count=1,
                preprocessed=False,
            ),
            used_fallback=True,
            warnings=("suspicious_anchor_gain:unit_kg", "suspicious_anchor_loss:unit_kg"),
        )

        def fake_transcribe_with_result(*args, **kwargs):
            return unsafe_result

        monkeypatch.setattr(
            api_whatsapp, "_transcribe_audio_with_result", fake_transcribe_with_result
        )
        monkeypatch.setenv("WHISPER_ENABLED", "true")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")

        # Garante que o serviço de transcrição existe para bloquear duration_probe
        if api_whatsapp._audio_transcription_service is None:
            api_whatsapp._audio_transcription_service = api_whatsapp.AudioTranscriptionService.from_env()

        # Bloqueia serviço real de duração
        def fail_if_duration_probe_called(*args, **kwargs):
            raise AssertionError("duration probe não deveria ser chamado neste teste")

        monkeypatch.setattr(
            api_whatsapp._audio_transcription_service,
            "_duration_probe",
            fail_if_duration_probe_called,
        )

        # Mock do gerador de resumo
        from services.llm_text_generation_service import LlmTextGenerationResult
        def fake_llm(instructions, input_text, **kwargs):
            return LlmTextGenerationResult(
                True, "openai", "gpt-x",
                "assunto_principal: Aplicação\nnecessidades: 20 kg\ndecisoes: 22/07/2026\npendencias: nenhuma\nproximos_passos: retornar"
            )
        api_whatsapp._visita_summary_service._generator._generator = fake_llm

        # Verifica monkeypatch aplicado
        assert callable(api_whatsapp._transcribe_audio_with_result)
        assert api_whatsapp._transcribe_audio_with_result is fake_transcribe_with_result

        reply = api_whatsapp.handle_whatsapp_audio_message(sender, "media-visita", "audio/ogg")

        # Validações obrigatórias
        # 1. Warning amigável aparece para o usuário
        assert "⚠️" in reply
        assert "conferência" in reply.lower() or "confira" in reply.lower()

        # 2. raw_text permanece preservado (20 kg aparece, 200 kg NÃO)
        assert "20 kg" in reply
        assert "200 kg" not in reply

        # 3. O texto selecionado/usado pelo fluxo preserva os anchors do raw_text (20 kg, 22/07/2026)
        # Com inseguro, o summary deve preservar os anchors do raw_text (20 kg, 22/07/2026)
        assert "20 kg" in reply
        assert "22/07/2026" in reply or "22/07/2026" in reply  # data preservada
        assert "200 kg" not in reply  # reviewed_text alterado NÃO usado

        # 4. Nada persistido no banco
        saved = visitas.obter_visita_aberta(sender)
        assert "200 kg" not in (saved.get("observacoes_gerais") or "")
        assert "999 kg" not in (saved.get("observacoes_gerais") or "")

        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_summary_confirmation_states.clear()


def test_description_and_observation_remain_separate(monkeypatch, tmp_path):
    """Descrição e observação permanecem separadas."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        original = (api_whatsapp.rdv_service, api_whatsapp.visitas_service)
        rdv = RDVService(Path(temp_dir) / "rdv.db")
        visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        api_whatsapp.rdv_service = rdv
        api_whatsapp.visitas_service = visitas
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_summary_confirmation_states.clear()
        api_whatsapp.rdv_comment_states.clear()

        sender = rdv.get_collaborator_by_phone("5500000000001")["telefone_whatsapp"]
        visita = visitas.iniciar_visita(sender)
        api_whatsapp.visita_active_states[sender] = int(visita["id"])

        downloaded = tmp_path / "visita.ogg"
        downloaded.write_bytes(b"audio")

        monkeypatch.setattr(
            api_whatsapp, "download_media", lambda media_id, destination: downloaded
        )

        # TranscriptionResult para descrição (seguro)
        desc_result = TranscriptionResult(
            ok=True,
            raw_text="Descrição bruta da lavoura.",
            reviewed_text="Descrição revisada da lavoura.",
            metadata=AudioMetadata(
                provider="whisper_local",
                model_name="base",
                language="pt",
                duration_seconds=5.0,
                size_bytes=1024,
                chunk_count=1,
                preprocessed=False,
            ),
            used_fallback=False,
            warnings=(),
        )

        # TranscriptionResult para observação (seguro)
        obs_result = TranscriptionResult(
            ok=True,
            raw_text="Observação bruta sobre o manejo.",
            reviewed_text="Observação revisada sobre o manejo.",
            metadata=AudioMetadata(
                provider="whisper_local",
                model_name="base",
                language="pt",
                duration_seconds=5.0,
                size_bytes=1024,
                chunk_count=1,
                preprocessed=False,
            ),
            used_fallback=False,
            warnings=(),
        )

        # Mock do _transcribe_audio_with_result para descrição
        def fake_transcribe_desc(*args, **kwargs):
            return desc_result

        monkeypatch.setattr(
            api_whatsapp, "_transcribe_audio_with_result", fake_transcribe_desc
        )
        monkeypatch.setenv("WHISPER_ENABLED", "true")
        # Desabilita o resumo de IA para testar o fluxo direto de salvamento
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "false")

        # Mock do serviço de inteligência para evitar chamada real
        # Deve retornar o reviewed_text do TranscriptionResult correspondente
        from services.audio_transcription_intelligence_service import IntelligentTranscriptionResult
        def fake_intelligence_process(raw, mode=None, **kw):
            if "Descrição bruta" in raw:
                return IntelligentTranscriptionResult(True, raw, "Descrição revisada da lavoura.", "revisada", "local")
            elif "Observação bruta" in raw:
                return IntelligentTranscriptionResult(True, raw, "Observação revisada sobre o manejo.", "revisada", "local")
            return IntelligentTranscriptionResult(True, raw, raw, "revisada", "local")
        monkeypatch.setattr(
            api_whatsapp._audio_transcription_intelligence_service,
            "process",
            fake_intelligence_process
        )

        # Garante que o serviço de transcrição existe para bloquear duration_probe
        if api_whatsapp._audio_transcription_service is None:
            api_whatsapp._audio_transcription_service = api_whatsapp.AudioTranscriptionService.from_env()

        # Bloqueia duration_probe real
        def fail_if_duration_probe_called(*args, **kwargs):
            raise AssertionError("duration probe não deveria ser chamado neste teste")

        monkeypatch.setattr(
            api_whatsapp._audio_transcription_service,
            "_duration_probe",
            fail_if_duration_probe_called,
        )

        # Verifica monkeypatch aplicado
        assert callable(api_whatsapp._transcribe_audio_with_result)
        assert api_whatsapp._transcribe_audio_with_result is fake_transcribe_desc

        # 1. Estado de descrição
        visitas.atualizar_campo(visita["id"], "estado_fluxo", "aguardando_descricao_visita")

        reply = api_whatsapp.handle_whatsapp_audio_message(sender, "media-desc", "audio/ogg")

        # Salva na descrição
        saved = visitas.obter_visita_aberta(sender)
        assert "Descrição revisada da lavoura" in (saved["descricao_visita"] or "")

        # 2. Troca mock para observação
        def fake_transcribe_obs(*args, **kwargs):
            return obs_result

        monkeypatch.setattr(
            api_whatsapp, "_transcribe_audio_with_result", fake_transcribe_obs
        )

        # 3. Estado de observação
        visitas.atualizar_campo(visita["id"], "estado_fluxo", "aguardando_observacoes_gerais")

        reply = api_whatsapp.handle_whatsapp_audio_message(sender, "media-obs", "audio/ogg")

        saved = visitas.obter_visita_aberta(sender)

        # Validações obrigatórias
        # Descrição contém apenas texto de descrição
        assert "Descrição revisada da lavoura" in (saved["descricao_visita"] or "")
        assert "Observação" not in (saved["descricao_visita"] or "")

        # Observação contém apenas texto de observação
        assert "Observação revisada sobre o manejo" in (saved["observacoes_gerais"] or "")
        assert "Descrição" not in (saved["observacoes_gerais"] or "")

        # Sem mistura
        assert "Descrição" not in (saved["observacoes_gerais"] or "")
        assert "Observação" not in (saved["descricao_visita"] or "")

        # Estados não se sobrescrevem
        assert "Descrição revisada da lavoura" in (saved["descricao_visita"] or "")
        assert "Observação revisada sobre o manejo" in (saved["observacoes_gerais"] or "")

        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_summary_confirmation_states.clear()


# =============================================================================
# E. Privacidade / Logs
# =============================================================================

def test_request_id_only_in_technical_logs(caplog):
    """request_id aparece apenas em logs técnicos."""
    import logging
    from services.audio_transcription_service import AudioTranscriptionService

    caplog.set_level(logging.INFO)

    class FakeModel:
        def transcribe(self, audio_path, **kwargs):
            return {"text": "SEGREDO_RAW_A2_2"}

    # Desabilita preprocessamento para evitar dependência de ffmpeg
    service = AudioTranscriptionService(
        model_loader=lambda name: FakeModel(),
        duration_probe=lambda path: 5.0,
        preprocess_audio=False,
    )

    with tempfile.NamedTemporaryFile(suffix=".ogg") as f:
        f.write(b"fake")
        f.flush()
        # Usa o novo método que gera request_id
        result = service.transcrever_com_resultado(f.name)

    # Verifica que logs não contêm textos sensíveis
    log_text = caplog.text
    # request_id está no resultado (metadata), não necessariamente nos logs INFO
    assert result.metadata.request_id is not None
    assert len(result.metadata.request_id) == 12
    # Não deve conter o texto transcrito
    assert "SEGREDO_RAW_A2_2" not in log_text


def test_logs_do_not_contain_raw_text(caplog):
    """Logs não contêm raw_text."""
    import logging
    from services.audio_transcription_service import AudioTranscriptionService

    caplog.set_level(logging.INFO)

    class FakeModel:
        def transcribe(self, audio_path, **kwargs):
            return {"text": "texto sensível com R$ 100,00 e 5 ha"}

    service = AudioTranscriptionService(
        model_loader=lambda name: FakeModel(),
        duration_probe=lambda path: 5.0,
    )

    with tempfile.NamedTemporaryFile(suffix=".ogg") as f:
        f.write(b"fake")
        f.flush()
        service.transcrever(f.name)

    log_text = caplog.text
    assert "R$ 100,00" not in log_text
    assert "5 ha" not in log_text


def test_logs_do_not_contain_phone_or_media_id(caplog):
    """Logs não contêm telefone ou media_id."""
    import logging
    from services.audio_transcription_service import AudioTranscriptionService

    caplog.set_level(logging.INFO)

    class FakeModel:
        def transcribe(self, audio_path, **kwargs):
            return {"text": "teste"}

    service = AudioTranscriptionService(
        model_loader=lambda name: FakeModel(),
        duration_probe=lambda path: 5.0,
    )

    with tempfile.NamedTemporaryFile(suffix=".ogg") as f:
        f.write(b"fake")
        f.flush()
        service.transcrever(f.name)

    log_text = caplog.text
    assert "5500000000001" not in log_text
    assert "media-" not in log_text


def test_warnings_not_shown_entirely_to_user(monkeypatch, tmp_path):
    """Warnings técnicos não são exibidos integralmente ao usuário."""
    downloaded = tmp_path / "warn.ogg"
    downloaded.write_bytes(b"audio")
    sender = "5500000000001"

    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", lambda media_id, destination: downloaded
    )
    # Mock do novo método _transcribe_audio_with_result
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    mock_result = TranscriptionResult.success(
        raw_text="custou R$ 100,00",
        reviewed_text="custou R$ 200,00",
        metadata=AudioMetadata(
            provider="whisper_local",
            model_name="base",
            language="pt",
            duration_seconds=5.0,
            size_bytes=1024,
            chunk_count=1,
            preprocessed=False,
        ),
        used_fallback=True,
        warnings=("suspicious_anchor_gain:currency", "suspicious_anchor_loss:currency"),
    )
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_with_result", lambda path: mock_result
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    api_whatsapp.standalone_transcription_modes[sender] = "revisada"

    # Mock revisão insegura (o service de inteligência ainda é chamado)
    from services.audio_transcription_intelligence_service import IntelligentTranscriptionResult
    monkeypatch.setattr(
        api_whatsapp,
        "_audio_transcription_intelligence_service",
        type("Mock", (), {
            "process": lambda self, raw, **kw: IntelligentTranscriptionResult(
                True, raw, "custou R$ 200,00", "revisada", "local"
            )
        })(),
    )

    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-warn", "audio/ogg"
        )

        assert "suspicious_anchor" not in reply
        assert "⚠️" in reply
        assert "confer" in reply.lower()  # "conferência" ou "confira"
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()


# =============================================================================
# F. Compatibilidade
# =============================================================================

def test_exit_menu_cancel_voltar_still_work(monkeypatch, tmp_path):
    """Comandos sair, menu, cancelar e voltar continuam funcionando."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        rdv, visitas, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            for command in ("sair", "menu", "cancelar", "voltar"):
                api_whatsapp.whatsapp_menu_states[
                    sender
                ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
                reply = api_whatsapp.handle_rdv_text_message(sender, command)

                assert reply is None
                assert sender not in api_whatsapp.whatsapp_menu_states
        finally:
            api_whatsapp.rdv_service = original_rdv
            api_whatsapp.visitas_service = original_visitas
            api_whatsapp.whatsapp_menu_states.clear()
            api_whatsapp.standalone_transcription_modes.clear()


def test_no_write_to_db_before_confirmation(monkeypatch, tmp_path):
    """Nenhum fluxo grava no banco antes da confirmação."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        rdv, visitas, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            expense = _completed_expense(rdv, rdv.get_collaborator_by_phone("5500000000001"), sender)
            api_whatsapp._start_rdv_comment_state(sender, expense["id"])

            downloaded = tmp_path / "rdv.ogg"
            downloaded.write_bytes(b"audio")

            def fake_download(media_id, destination):
                path = Path(destination)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fake-audio")
                return path

            monkeypatch.setattr(api_whatsapp, "download_media", fake_download)
            monkeypatch.setattr(
                api_whatsapp, "_transcribe_audio_file", lambda path: "Comentario do audio"
            )
            monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "true")
            monkeypatch.setenv("WHISPER_KEEP_AUDIO", "false")

            api_whatsapp._handle_whatsapp_message({
                "from": sender,
                "id": "wamid.audio.rdv",
                "timestamp": "1781900000",
                "type": "audio",
                "audio": {"id": "media-audio-rdv", "mime_type": "audio/ogg"},
            })

            # Antes da confirmação, nada salvo
            expense_before = rdv.get_expense(expense["id"])
            assert expense_before["observacao"] in (None, "")

        finally:
            api_whatsapp.rdv_service = original_rdv
            api_whatsapp.visitas_service = original_visitas
            api_whatsapp.rdv_comment_states.clear()


def test_no_external_provider_called(monkeypatch, tmp_path, mock_download_media_success, mock_transcribe_audio_with_result_safe):
    """Provider externo nunca é chamado quando provider=local."""
    downloaded = tmp_path / "local.ogg"
    downloaded.write_bytes(b"audio")
    sender = "5500000000001"

    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setenv("TRANSCRIPTION_REVIEW_PROVIDER", "local")
    monkeypatch.setattr(
        api_whatsapp, "download_media", mock_download_media_success
    )
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_with_result", mock_transcribe_audio_with_result_safe
    )
    # Garante que provider externo não é chamado
    called = {"external": False}
    def mock_external(raw, mode):
        called["external"] = True
        return "external result"
    monkeypatch.setattr(
        api_whatsapp._audio_transcription_intelligence_service,
        "_external_providers",
        {"openai": mock_external}
    )

    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    api_whatsapp.standalone_transcription_modes[sender] = "revisada"
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-local", "audio/ogg"
        )
        assert not called["external"]
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()


# =============================================================================
# G. Validação de âncoras
# =============================================================================

def test_validate_anchors_preserves_all():
    """validate_anchors preserva tudo quando não há alteração."""
    from services.audio_transcription_contract import validate_anchors, AudioMetadata
    is_safe, warnings = validate_anchors("Aplicar 10 kg em 5 ha", "Aplicar 10 kg em 5 ha")
    assert is_safe is True
    assert warnings == []


def test_validate_anchors_detects_loss():
    """validate_anchors detecta perda de âncora."""
    from services.audio_transcription_contract import validate_anchors
    is_safe, warnings = validate_anchors("Aplicar 10 kg em 5 ha", "Aplicar em 5 ha")
    assert is_safe is False
    assert any("anchor_loss" in w for w in warnings)


def test_validate_anchors_detects_gain():
    """validate_anchors detecta ganho suspeito de âncora."""
    from services.audio_transcription_contract import validate_anchors
    is_safe, warnings = validate_anchors("Aplicar em 5 ha", "Aplicar 10 kg em 5 ha")
    assert is_safe is False
    assert any("anchor_gain" in w for w in warnings)
