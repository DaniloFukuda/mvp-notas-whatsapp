import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.audio_transcription_service import (
    AUDIO_TOO_LONG_MESSAGE,
    AudioLimitExceededError,
    AudioTranscriptionService,
    whisper_enabled_from_env,
)


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
        duration_probe=lambda path: 10,
    )

    text = service.transcrever(str(audio_path))

    assert text == "comentario transcrito"
    assert fake_model.calls == [(str(audio_path), "pt", False)]


def test_audio_transcription_service_caches_model(tmp_path):
    audio_path = tmp_path / "audio.ogg"
    audio_path.write_bytes(b"fake-audio")
    fake_model = FakeModel()
    loaded = []
    service = AudioTranscriptionService(
        model_name="tiny",
        language="pt",
        model_loader=lambda model_name: loaded.append(model_name) or fake_model,
        duration_probe=lambda path: 10,
    )

    assert service.transcrever(str(audio_path)) == "comentario transcrito"
    assert service.transcrever(str(audio_path)) == "comentario transcrito"

    assert loaded == ["tiny"]
    assert len(fake_model.calls) == 2


def test_audio_transcription_service_blocks_large_file(tmp_path):
    audio_path = tmp_path / "audio.ogg"
    audio_path.write_bytes(b"123456")
    service = AudioTranscriptionService(
        max_audio_mb=0.000001,
        model_loader=lambda model_name: FakeModel(),
        duration_probe=lambda path: 10,
    )

    try:
        service.transcrever(str(audio_path))
    except AudioLimitExceededError as exc:
        assert str(exc) == AUDIO_TOO_LONG_MESSAGE
    else:
        raise AssertionError("esperava ValueError")


def test_audio_transcription_service_missing_file_raises(tmp_path):
    service = AudioTranscriptionService(model_loader=lambda model_name: FakeModel())

    try:
        service.transcrever(str(tmp_path / "nao-existe.ogg"))
    except FileNotFoundError as exc:
        assert "Arquivo de audio nao encontrado" in str(exc)
    else:
        raise AssertionError("esperava FileNotFoundError")


def test_long_audio_is_chunked_joined_in_order_and_cleaned(tmp_path):
    audio_path = tmp_path / "audio.ogg"
    audio_path.write_bytes(b"fake-audio")
    extracted = []

    class OrderedModel:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio_path, language="pt", fp16=False):
            path = Path(audio_path)
            self.calls.append(path)
            return {"text": f" parte {int(path.stem.split('_')[1]) + 1} "}

    model = OrderedModel()

    def extract(source, destination, start, duration):
        path = Path(destination)
        path.write_bytes(b"chunk")
        extracted.append((path, start, duration))

    service = AudioTranscriptionService(
        chunk_seconds=60,
        duration_probe=lambda path: 125,
        chunk_extractor=extract,
        model_loader=lambda name: model,
    )

    assert service.transcrever(str(audio_path)) == "parte 1 parte 2 parte 3"
    assert [(start, duration) for _, start, duration in extracted] == [
        (0, 60),
        (60, 60),
        (120, 5),
    ]
    assert all(not path.exists() for path, _, _ in extracted)
    assert len({path.parent for path, _, _ in extracted}) == 1
    assert not extracted[0][0].parent.exists()


def test_audio_over_duration_limit_is_rejected_before_loading_model(tmp_path):
    audio_path = tmp_path / "audio.ogg"
    audio_path.write_bytes(b"fake-audio")
    loaded = []
    service = AudioTranscriptionService(
        max_audio_seconds=1800,
        duration_probe=lambda path: 1800.01,
        model_loader=lambda name: loaded.append(name) or FakeModel(),
    )

    try:
        service.transcrever(str(audio_path))
    except AudioLimitExceededError as exc:
        assert str(exc) == AUDIO_TOO_LONG_MESSAGE
    else:
        raise AssertionError("esperava AudioLimitExceededError")
    assert loaded == []


def test_chunk_files_are_cleaned_when_transcription_fails(tmp_path):
    audio_path = tmp_path / "audio.ogg"
    audio_path.write_bytes(b"fake-audio")
    extracted = []

    class BrokenModel:
        def transcribe(self, audio_path, language="pt", fp16=False):
            raise RuntimeError("falha simulada")

    def extract(source, destination, start, duration):
        path = Path(destination)
        path.write_bytes(b"chunk")
        extracted.append(path)

    service = AudioTranscriptionService(
        duration_probe=lambda path: 61,
        chunk_extractor=extract,
        model_loader=lambda name: BrokenModel(),
    )

    try:
        service.transcrever(str(audio_path))
    except RuntimeError as exc:
        assert "falha simulada" in str(exc)
    else:
        raise AssertionError("esperava RuntimeError")
    assert extracted and all(not path.exists() for path in extracted)
    assert not extracted[0].parent.exists()


def test_failed_audio_is_preserved_when_enabled(tmp_path, caplog):
    audio_path = tmp_path / "audio-original.ogg"
    audio_path.write_bytes(b"audio-com-problema")
    debug_dir = tmp_path / "data" / "debug_audio"

    class BrokenModel:
        def transcribe(self, audio_path, language="pt", fp16=False):
            raise RuntimeError("falha simulada do Whisper")

    service = AudioTranscriptionService(
        model_name="base",
        keep_failed_audio=True,
        failed_audio_dir=debug_dir,
        duration_probe=lambda path: 12.5,
        model_loader=lambda name: BrokenModel(),
    )

    try:
        service.transcrever(str(audio_path))
    except RuntimeError as exc:
        assert "falha simulada do Whisper" in str(exc)
    else:
        raise AssertionError("esperava RuntimeError")

    preserved = list(debug_dir.glob("*_audio-original.ogg"))
    assert len(preserved) == 1
    assert preserved[0].read_bytes() == b"audio-com-problema"
    assert "Audio preservado para diagnostico" in caplog.text
    assert "tamanho_bytes=18" in caplog.text
    assert "duracao_segundos=12.500" in caplog.text
    assert "modelo=base" in caplog.text
    assert "falha simulada do Whisper" in caplog.text


def test_failed_audio_is_not_preserved_when_disabled(tmp_path):
    audio_path = tmp_path / "audio-original.ogg"
    audio_path.write_bytes(b"audio-com-problema")
    debug_dir = tmp_path / "data" / "debug_audio"

    service = AudioTranscriptionService(
        keep_failed_audio=False,
        failed_audio_dir=debug_dir,
        duration_probe=lambda path: (_ for _ in ()).throw(
            RuntimeError("ffprobe falhou")
        ),
    )

    try:
        service.transcrever(str(audio_path))
    except RuntimeError as exc:
        assert "ffprobe falhou" in str(exc)
    else:
        raise AssertionError("esperava RuntimeError")

    assert not debug_dir.exists()


def test_from_env_uses_new_defaults_and_old_env_compatibility(monkeypatch):
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    monkeypatch.delenv("WHISPER_MAX_AUDIO_MB", raising=False)
    monkeypatch.delenv("WHISPER_MAX_AUDIO_SECONDS", raising=False)
    monkeypatch.delenv("WHISPER_CHUNK_SECONDS", raising=False)
    monkeypatch.delenv("WHISPER_KEEP_FAILED_AUDIO", raising=False)

    service = AudioTranscriptionService.from_env()

    assert service.max_audio_mb == 50
    assert service.max_audio_seconds == 1800
    assert service.chunk_seconds == 60
    assert service.model_name == "base"
    assert service.language == "pt"
    assert service.keep_failed_audio is True


def test_from_env_enables_failed_audio_preservation(monkeypatch):
    monkeypatch.setenv("WHISPER_KEEP_FAILED_AUDIO", "true")

    service = AudioTranscriptionService.from_env()

    assert service.keep_failed_audio is True


def test_whisper_model_env_override_is_preserved(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "small")

    service = AudioTranscriptionService.from_env()

    assert service.model_name == "small"


def test_whisper_enabled_from_env_defaults_local_on(monkeypatch):
    monkeypatch.delenv("WHISPER_ENABLED", raising=False)
    monkeypatch.delenv("AUDIO_TRANSCRIPTION_ENABLED", raising=False)
    monkeypatch.setenv("APP_ENV", "local")

    assert whisper_enabled_from_env() is True


def test_whisper_enabled_from_env_respects_flag(monkeypatch):
    monkeypatch.setenv("WHISPER_ENABLED", "false")
    monkeypatch.setenv("AUDIO_TRANSCRIPTION_ENABLED", "true")

    assert whisper_enabled_from_env() is False
