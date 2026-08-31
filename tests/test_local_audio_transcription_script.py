from pathlib import Path

from scripts import test_local_audio_transcription as local_audio
from services.audio_transcription_contract import AudioMetadata, TranscriptionResult


class _FakeService:
    def transcrever_com_resultado(self, path: str) -> TranscriptionResult:
        return TranscriptionResult.success(
            raw_text="conteudo que nao deve aparecer no output",
            reviewed_text="conteudo que nao deve aparecer no output",
            metadata=AudioMetadata(duration_seconds=1.5),
        )


def test_validate_reports_metadata_without_printing_transcript(monkeypatch, tmp_path, capsys):
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"fixture")
    monkeypatch.setattr(
        local_audio,
        "probe_audio",
        lambda path: {"duration": 1.5, "container": "ogg", "codec": "opus"},
    )

    exit_code = local_audio.validate(audio, service=_FakeService())
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "audio_valid=true" in output
    assert "mime/container=ogg" in output
    assert "codec=opus" in output
    assert "transcription_success=true" in output
    assert "transcript_non_empty=true" in output
    assert "transcript_length=40" in output
    assert "conteudo que nao deve aparecer" not in output


def test_validate_rejects_invalid_audio_without_loading_service(monkeypatch, tmp_path, capsys):
    audio = tmp_path / "invalid.ogg"
    audio.write_bytes(b"not-audio")
    monkeypatch.setattr(local_audio, "probe_audio", lambda path: None)

    exit_code = local_audio.validate(audio)
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "audio_valid=false" in output
    assert "error_code=INVALID_AUDIO" in output
