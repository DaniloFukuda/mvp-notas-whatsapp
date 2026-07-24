import tempfile
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.audio_transcription_service import (
    AUDIO_TOO_LONG_MESSAGE,
    TRANSCRIPTION_FAILED_MESSAGE,
    AudioLimitExceededError,
)
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService


def _install_services(temp_dir: str):
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    rdv = RDVService(Path(temp_dir) / "rdv.db")
    visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
    api_whatsapp.rdv_service = rdv
    api_whatsapp.visitas_service = visitas
    collaborator = rdv.get_collaborator_by_phone("5500000000001")
    return rdv, visitas, collaborator["telefone_whatsapp"], original_rdv, original_visitas


def _restore_services(original_rdv, original_visitas):
    api_whatsapp.rdv_service = original_rdv
    api_whatsapp.visitas_service = original_visitas
    api_whatsapp.whatsapp_menu_states.clear()
    api_whatsapp.standalone_transcription_modes.clear()
    api_whatsapp.rdv_comment_states.clear()
    api_whatsapp.visita_active_states.clear()


def test_menu_texto_mostra_opcao_transcrever_audio():
    assert "🎙️ Transcrever áudio" in api_whatsapp.MAIN_MENU_MESSAGE
    assert "* transcrever áudio" in api_whatsapp.MAIN_MENU_MESSAGE


def test_escolher_transcricao_avulsa_coloca_sessao_aguardando_audio():
    with tempfile.TemporaryDirectory() as temp_dir:
        _, _, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            reply = api_whatsapp.handle_rdv_text_message(sender, "transcrever áudio")

            assert reply == api_whatsapp.STANDALONE_TRANSCRIPTION_PROMPT
            assert "1. Literal" in reply
            assert "2. Revisada" in reply
            assert "Codex" not in reply
            assert "Relatório" not in reply
            assert (
                api_whatsapp.whatsapp_menu_states[sender]
                == api_whatsapp.STANDALONE_TRANSCRIPTION_MODE_STATE
            )
        finally:
            _restore_services(original_rdv, original_visitas)


def test_texto_normal_no_modo_avulso_pede_audio():
    with tempfile.TemporaryDirectory() as temp_dir:
        _, _, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            api_whatsapp.whatsapp_menu_states[
                sender
            ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE

            reply = api_whatsapp.handle_rdv_text_message(sender, "texto qualquer")

            assert reply == api_whatsapp.STANDALONE_TRANSCRIPTION_TEXT_PROMPT
            assert sender in api_whatsapp.whatsapp_menu_states
        finally:
            _restore_services(original_rdv, original_visitas)


@pytest.mark.parametrize(
    ("option", "mode"),
    [("1", "literal"), ("2", "revisada")],
)
def test_escolher_modo_salva_sessao(option, mode):
    with tempfile.TemporaryDirectory() as temp_dir:
        _, _, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            api_whatsapp.handle_rdv_text_message(sender, "transcrever áudio")
            reply = api_whatsapp.handle_rdv_text_message(sender, option)

            assert reply == api_whatsapp.STANDALONE_TRANSCRIPTION_AUDIO_PROMPT
            assert (
                api_whatsapp.whatsapp_menu_states[sender]
                == api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
            )
            assert api_whatsapp.standalone_transcription_modes[sender] == mode
        finally:
            _restore_services(original_rdv, original_visitas)


@pytest.mark.parametrize("invalid_option", ["3", "codex", "para codex"])
def test_opcao_de_transcricao_invalida_mostra_apenas_modos_publicos(
    invalid_option,
):
    with tempfile.TemporaryDirectory() as temp_dir:
        _, _, sender, original_rdv, original_visitas = _install_services(temp_dir)
        try:
            api_whatsapp.handle_rdv_text_message(sender, "transcrever áudio")

            reply = api_whatsapp.handle_rdv_text_message(sender, invalid_option)

            assert reply == api_whatsapp.STANDALONE_TRANSCRIPTION_INVALID_MODE_PROMPT
            assert "1. Literal" in reply
            assert "2. Revisada" in reply
            assert "Codex" not in reply
            assert "Relatório" not in reply
            assert (
                api_whatsapp.whatsapp_menu_states[sender]
                == api_whatsapp.STANDALONE_TRANSCRIPTION_MODE_STATE
            )
        finally:
            _restore_services(original_rdv, original_visitas)


@ pytest.mark.parametrize(
    ("mode", "heading"),
    [
        ("literal", "🎙️ Transcrição literal:"),
        ("revisada", "📝 Transcrição revisada:"),
    ],
)
def test_audio_avulso_usa_titulo_do_modo(monkeypatch, tmp_path, mode, heading):
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    downloaded = tmp_path / f"{mode}.ogg"
    downloaded.write_bytes(b"audio")
    sender = "5500000000001"
    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", lambda media_id, destination: downloaded
    )
    mock_result = TranscriptionResult.success(
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
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_with_result", lambda path: mock_result
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    api_whatsapp.standalone_transcription_modes[sender] = mode
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, f"media-{mode}", "audio/ogg"
        )

        assert reply.startswith(heading)
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()


def test_cancelar_ou_menu_sai_do_modo_avulso(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        _, _, sender, original_rdv, original_visitas = _install_services(temp_dir)
        sent = []
        monkeypatch.setattr(
            api_whatsapp, "send_main_menu_interactive", lambda phone: sent.append(phone)
        )
        try:
            for command in ("cancelar", "menu", "sair", "voltar"):
                api_whatsapp.whatsapp_menu_states[
                    sender
                ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE

                reply = api_whatsapp.handle_rdv_text_message(sender, command)

                assert reply is None
                assert sender not in api_whatsapp.whatsapp_menu_states
            assert sent == [sender, sender, sender, sender]
        finally:
            _restore_services(original_rdv, original_visitas)


def test_audio_avulso_retorna_transcricao_sem_salvar_visita_ou_rdv(
    monkeypatch, tmp_path
):
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    with tempfile.TemporaryDirectory() as temp_dir:
        rdv, visitas, sender, original_rdv, original_visitas = _install_services(temp_dir)
        downloaded = tmp_path / "audio.ogg"
        downloaded.write_bytes(b"fake-audio")
        monkeypatch.setenv("WHISPER_ENABLED", "true")
        monkeypatch.setenv("WHISPER_KEEP_AUDIO", "false")
        monkeypatch.setattr(
            api_whatsapp, "download_media", lambda media_id, destination: downloaded
        )
        mock_result = TranscriptionResult.success(
            raw_text="Relatório falado transcrito com sucesso.",
            reviewed_text="Relatório falado transcrito com sucesso.",
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
        monkeypatch.setattr(
            api_whatsapp, "_transcribe_audio_with_result", lambda path: mock_result
        )
        try:
            api_whatsapp.whatsapp_menu_states[
                sender
            ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
            api_whatsapp.standalone_transcription_modes[sender] = "revisada"

            reply = api_whatsapp.handle_whatsapp_audio_message(
                sender, "media-audio", "audio/ogg"
            )

            assert reply == (
                "📝 Transcrição revisada:\n\n"
                "Relatório falado transcrito com sucesso.\n\n"
                "Você pode enviar outro áudio ou digitar menu para voltar."
            )
            assert sender in api_whatsapp.whatsapp_menu_states
            assert rdv.list_launches() == []
            assert visitas.listar_visitas()["visitas"] == []
            assert not downloaded.exists()
        finally:
            _restore_services(original_rdv, original_visitas)

def test_audio_longo_avulso_retorna_texto_unido(monkeypatch, tmp_path):
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    downloaded = tmp_path / "long.ogg"
    downloaded.write_bytes(b"fake-audio")
    sender = "5500000000001"
    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", lambda media_id, destination: downloaded
    )
    mock_result = TranscriptionResult.success(
        raw_text="parte um parte dois parte três",
        reviewed_text="parte um parte dois parte três",
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
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_with_result", lambda path: mock_result
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    api_whatsapp.standalone_transcription_modes[sender] = "revisada"
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-long", "audio/ogg"
        )

        assert "parte um parte dois parte três" in reply.lower()
        assert reply.lower().count("parte um") == 1
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()


def test_resposta_avulsa_muito_longa_e_enviada_em_partes(monkeypatch):
    sent = []
    monkeypatch.setattr(
        api_whatsapp, "send_whatsapp_text", lambda phone, text: sent.append(text)
    )

    api_whatsapp._safe_send_text_chunks("5500000000001", "palavra " * 1200)

    assert len(sent) > 1
    assert all(len(part) <= 4000 for part in sent)
    assert " ".join(" ".join(sent).split()) == " ".join(("palavra " * 1200).split())


def test_erro_de_transcricao_avulsa_retorna_mensagem_amigavel(
    monkeypatch, tmp_path
):
    from services.audio_transcription_contract import TranscriptionResult, AudioMetadata
    downloaded = tmp_path / "broken.ogg"
    downloaded.write_bytes(b"fake-audio")
    sender = "5500000000001"
    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", lambda media_id, destination: downloaded
    )
    mock_result = TranscriptionResult.failure(
        error_code="TRANSCRIPTION_FAILED",
        error_message="Falha na transcrição",
        raw_text="",
    )
    monkeypatch.setattr(
        api_whatsapp,
        "_transcribe_audio_with_result",
        lambda path: mock_result,
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-broken", "audio/ogg"
        )

        assert reply == TRANSCRIPTION_FAILED_MESSAGE
        assert sender in api_whatsapp.whatsapp_menu_states
    finally:
        api_whatsapp.whatsapp_menu_states.clear()


def test_audio_avulso_acima_do_limite_retorna_mensagem_existente(
    monkeypatch, tmp_path
):
    from services.audio_transcription_service import AudioLimitExceededError
    downloaded = tmp_path / "too-long.ogg"
    downloaded.write_bytes(b"fake-audio")
    sender = "5500000000001"
    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", lambda media_id, destination: downloaded
    )
    monkeypatch.setattr(
        api_whatsapp,
        "_transcribe_audio_with_result",
        lambda path: (_ for _ in ()).throw(
            AudioLimitExceededError(AUDIO_TOO_LONG_MESSAGE)
        ),
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-too-long", "audio/ogg"
        )

        assert reply == AUDIO_TOO_LONG_MESSAGE
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
