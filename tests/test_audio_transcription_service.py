import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.audio_transcription_service import AudioTranscriptionService


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio_path: str, language: str = "pt", fp16: bool = False) -> dict:
        self.calls.append((audio_path, language, fp16))
        return {"text": " comentario transcrito "}


def test_audio_transcription_service_uses_mocked_model(tmp_path):
    audio_path = tmp_path / "audio.ogg"
    audio_path.write_bytes(b"fake-audio")
    fake_model = FakeModel()
    service = AudioTranscriptionService(
        model_name="tiny",
        language="pt",
        model_loader=lambda model_name: fake_model,
    )

    text = service.transcrever(str(audio_path))

    assert text == "comentario transcrito"
    assert fake_model.calls == [(str(audio_path), "pt", False)]


def test_audio_transcription_service_missing_file_raises(tmp_path):
    service = AudioTranscriptionService(model_loader=lambda model_name: FakeModel())

    try:
        service.transcrever(str(tmp_path / "nao-existe.ogg"))
    except FileNotFoundError as exc:
        assert "Arquivo de audio nao encontrado" in str(exc)
    else:
        raise AssertionError("esperava FileNotFoundError")
