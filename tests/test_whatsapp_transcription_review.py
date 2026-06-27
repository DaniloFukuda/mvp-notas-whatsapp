import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService


def _install_services(temp_dir):
    original = (api_whatsapp.rdv_service, api_whatsapp.visitas_service)
    rdv = RDVService(Path(temp_dir) / "rdv.db")
    visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
    api_whatsapp.rdv_service = rdv
    api_whatsapp.visitas_service = visitas
    api_whatsapp.visita_active_states.clear()
    sender = rdv.get_collaborator_by_phone("5500000000001")["telefone_whatsapp"]
    return original, visitas, sender


def test_audio_de_visita_salva_versao_revisada(monkeypatch, tmp_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        original, visitas, sender = _install_services(temp_dir)
        downloaded = tmp_path / "visita.ogg"
        downloaded.write_bytes(b"audio")
        visita = visitas.iniciar_visita(sender)
        visitas.atualizar_campo(
            visita["id"], "estado_fluxo", "aguardando_observacoes_gerais"
        )
        monkeypatch.setenv("WHISPER_ENABLED", "true")
        monkeypatch.setenv("TRANSCRIPTION_REVIEW_ENABLED", "true")
        monkeypatch.setattr(
            api_whatsapp, "download_media", lambda media_id, destination: downloaded
        )
        monkeypatch.setattr(
            api_whatsapp,
            "_transcribe_audio_file",
            lambda path: "o contitor está alugado e os botes disponíveis",
        )
        try:
            api_whatsapp.handle_whatsapp_audio_message(
                sender, "media-visita", "audio/ogg"
            )

            saved = visitas.obter_visita_aberta(sender)
            assert saved["observacoes_gerais"] == (
                "O contentor está alugado e os botões disponíveis."
            )
        finally:
            api_whatsapp.rdv_service, api_whatsapp.visitas_service = original
            api_whatsapp.visita_active_states.clear()


def test_falha_na_revisao_usa_transcricao_bruta(monkeypatch, tmp_path):
    downloaded = tmp_path / "fallback.ogg"
    downloaded.write_bytes(b"audio")
    received = []
    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", lambda media_id, destination: downloaded
    )
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_file", lambda path: "texto bruto original"
    )
    monkeypatch.setattr(
        api_whatsapp._audio_transcription_review_service,
        "review",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("falha")),
    )
    monkeypatch.setattr(
        api_whatsapp,
        "handle_rdv_text_message",
        lambda phone, text, **kwargs: received.append(text) or "ok",
    )

    assert (
        api_whatsapp.handle_whatsapp_audio_message(
            "5500000000001", "media-fallback", "audio/ogg"
        )
        == "ok"
    )
    assert received == ["texto bruto original"]


def test_audio_avulso_indica_transcricao_revisada(monkeypatch, tmp_path):
    downloaded = tmp_path / "standalone.ogg"
    downloaded.write_bytes(b"audio")
    sender = "5500000000001"
    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setenv("TRANSCRIPTION_REVIEW_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", lambda media_id, destination: downloaded
    )
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_file", lambda path: "usar o cadax"
    )
    api_whatsapp.whatsapp_menu_states[
        sender
    ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
    try:
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-standalone", "audio/ogg"
        )

        assert reply.startswith("🎙️ Transcrição revisada do áudio:")
        assert "Codex" in reply
    finally:
        api_whatsapp.whatsapp_menu_states.clear()
