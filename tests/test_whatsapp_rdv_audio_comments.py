import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService


def _install_service(temp_dir: str):
    service = RDVService(Path(temp_dir) / "rdv.db")
    original_service = api_whatsapp.rdv_service
    api_whatsapp.rdv_service = service
    collaborator = service.get_collaborator_by_phone("5500000000001")
    sender = collaborator["telefone_whatsapp"]
    return service, original_service, collaborator, sender


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


def test_audio_received_with_transcription_disabled_does_not_break(monkeypatch):
    original_sender = api_whatsapp.send_whatsapp_text
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service, original_service, collaborator, sender = _install_service(temp_dir)
            sent = []
            api_whatsapp.send_whatsapp_text = lambda to, message: sent.append((to, message))
            monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "false")

            api_whatsapp._handle_whatsapp_message(
                {
                    "from": sender,
                    "id": "wamid.audio.disabled",
                    "timestamp": "1781900000",
                    "type": "audio",
                    "audio": {"id": "media-audio-1", "mime_type": "audio/ogg"},
                }
            )

            assert sent
            assert "transcricao esta desativada" in sent[-1][1] or "desativados" in sent[-1][1]
            assert service.list_launches() == []
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.send_whatsapp_text = original_sender
        api_whatsapp.rdv_comment_states.clear()


def test_audio_transcription_enabled_saves_pending_comment_and_removes_temp_file(monkeypatch, tmp_path):
    original_sender = api_whatsapp.send_whatsapp_text
    original_download = api_whatsapp.download_media
    original_transcriber = api_whatsapp._transcribe_audio_file
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service, original_service, collaborator, sender = _install_service(temp_dir)
            expense = _completed_expense(service, collaborator, sender)
            api_whatsapp._start_rdv_comment_state(sender, expense["id"])
            sent = []
            created_paths = []
            api_whatsapp.send_whatsapp_text = lambda to, message: sent.append((to, message))
            monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "true")
            monkeypatch.setenv("WHISPER_KEEP_AUDIO", "false")
            monkeypatch.setenv("WHISPER_TMP_DIR", str(tmp_path))

            def fake_download(media_id, destination):
                path = Path(destination)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fake-audio")
                created_paths.append(path)
                return path

            def fake_transcribe(path):
                assert Path(path).exists()
                return "Visita ao cliente antes do abastecimento."

            api_whatsapp.download_media = fake_download
            api_whatsapp._transcribe_audio_file = fake_transcribe

            api_whatsapp._handle_whatsapp_message(
                {
                    "from": sender,
                    "id": "wamid.audio.enabled",
                    "timestamp": "1781900000",
                    "type": "audio",
                    "audio": {"id": "media-audio-2", "mime_type": "audio/ogg"},
                }
            )

            assert sent
            assert "Transcrevi seu audio assim" in sent[-1][1]
            assert "Visita ao cliente" in api_whatsapp.rdv_comment_states[sender]["text"]
            assert created_paths and not created_paths[0].exists()
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.send_whatsapp_text = original_sender
        api_whatsapp.download_media = original_download
        api_whatsapp._transcribe_audio_file = original_transcriber
        api_whatsapp.rdv_comment_states.clear()


def test_confirming_transcribed_audio_saves_observation():
    with tempfile.TemporaryDirectory() as temp_dir:
        service, original_service, collaborator, sender = _install_service(temp_dir)
        try:
            expense = _completed_expense(service, collaborator, sender)
            api_whatsapp.rdv_comment_states[sender] = {
                "expense_id": expense["id"],
                "state": "awaiting_audio_confirmation",
                "text": "Comentario vindo do audio.",
            }

            reply = api_whatsapp.handle_rdv_text_message(sender, "1")

            saved = service.get_expense(expense["id"])
            assert "Comentario salvo no RDV" in reply
            assert saved["observacao"] == "Comentario vindo do audio."
            assert sender not in api_whatsapp.rdv_comment_states
        finally:
            api_whatsapp.rdv_service = original_service
            api_whatsapp.rdv_comment_states.clear()


def test_audio_comment_correction_text_saves_observation():
    with tempfile.TemporaryDirectory() as temp_dir:
        service, original_service, collaborator, sender = _install_service(temp_dir)
        try:
            expense = _completed_expense(service, collaborator, sender)
            api_whatsapp.rdv_comment_states[sender] = {
                "expense_id": expense["id"],
                "state": "awaiting_audio_confirmation",
                "text": "texto errado",
            }

            correction_prompt = api_whatsapp.handle_rdv_text_message(sender, "2")
            reply = api_whatsapp.handle_rdv_text_message(sender, "Texto corrigido")

            saved = service.get_expense(expense["id"])
            assert "Digite o comentario corrigido" in correction_prompt
            assert "Comentario salvo no RDV" in reply
            assert saved["observacao"] == "Texto corrigido"
        finally:
            api_whatsapp.rdv_service = original_service
            api_whatsapp.rdv_comment_states.clear()


def test_audio_comment_remove_option_keeps_observation_unchanged():
    with tempfile.TemporaryDirectory() as temp_dir:
        service, original_service, collaborator, sender = _install_service(temp_dir)
        try:
            expense = _completed_expense(service, collaborator, sender)
            api_whatsapp.rdv_comment_states[sender] = {
                "expense_id": expense["id"],
                "state": "awaiting_audio_confirmation",
                "text": "comentario descartado",
            }

            reply = api_whatsapp.handle_rdv_text_message(sender, "3")

            saved = service.get_expense(expense["id"])
            assert "Comentario removido" in reply
            assert saved["observacao"] in (None, "")
            assert sender not in api_whatsapp.rdv_comment_states
        finally:
            api_whatsapp.rdv_service = original_service
            api_whatsapp.rdv_comment_states.clear()
