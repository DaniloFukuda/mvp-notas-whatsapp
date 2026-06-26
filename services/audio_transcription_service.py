import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Protocol


AUDIO_TOO_LONG_MESSAGE = (
    "Esse áudio ficou muito longo para processar agora. "
    "Envie um áudio de até 30 minutos ou divida em partes menores."
)
TRANSCRIPTION_FAILED_MESSAGE = (
    "Não consegui entender esse áudio. "
    "Pode enviar novamente ou digitar a informação?"
)


class AudioLimitExceededError(ValueError):
    """Raised when an audio exceeds either configured safety limit."""


class _WhisperModel(Protocol):
    def transcribe(self, audio_path: str, language: str = "pt", fp16: bool = False) -> dict:
        ...


class AudioTranscriptionService:
    def __init__(
        self,
        model_name: str = "tiny",
        language: str = "pt",
        max_audio_mb: float | int | str | None = None,
        max_audio_seconds: float | int | str | None = None,
        chunk_seconds: float | int | str | None = None,
        model_loader: Callable[[str], _WhisperModel] | None = None,
        duration_probe: Callable[[str], float] | None = None,
        chunk_extractor: Callable[[str, str, float, float], None] | None = None,
    ) -> None:
        self.model_name = str(model_name or "tiny").strip() or "tiny"
        self.language = str(language or "pt").strip() or "pt"
        self.max_audio_mb = _to_positive_float(max_audio_mb, default=_env_max_audio_mb())
        self.max_audio_seconds = _to_positive_float(
            max_audio_seconds, default=_env_max_audio_seconds()
        )
        self.chunk_seconds = _to_positive_float(chunk_seconds, default=_env_chunk_seconds())
        self._model_loader = model_loader
        self._duration_probe = duration_probe or probe_audio_duration
        self._chunk_extractor = chunk_extractor or _extract_audio_chunk
        self._model: _WhisperModel | None = None

    @classmethod
    def from_env(
        cls,
        model_loader: Callable[[str], _WhisperModel] | None = None,
    ) -> "AudioTranscriptionService":
        return cls(
            model_name=os.getenv("WHISPER_MODEL", "tiny"),
            language=os.getenv("WHISPER_LANGUAGE", "pt"),
            max_audio_mb=os.getenv("WHISPER_MAX_AUDIO_MB"),
            max_audio_seconds=os.getenv("WHISPER_MAX_AUDIO_SECONDS"),
            chunk_seconds=os.getenv("WHISPER_CHUNK_SECONDS"),
            model_loader=model_loader,
        )

    def transcrever(self, audio_path: str) -> str:
        path = Path(audio_path)
        if not path.is_file():
            raise FileNotFoundError(f"Arquivo de audio nao encontrado: {path}")

        if path.stat().st_size > int(self.max_audio_mb * 1024 * 1024):
            raise AudioLimitExceededError(AUDIO_TOO_LONG_MESSAGE)

        duration = self._duration_probe(str(path))
        if duration <= 0:
            raise RuntimeError("Nao foi possivel determinar a duracao do audio.")
        if duration > self.max_audio_seconds:
            raise AudioLimitExceededError(AUDIO_TOO_LONG_MESSAGE)

        model = self._load_model()
        if duration <= self.chunk_seconds:
            return self._transcribe_path(model, path)

        texts: list[str] = []
        with tempfile.TemporaryDirectory(prefix="whisper_chunks_") as temp_dir:
            for index in range(math.ceil(duration / self.chunk_seconds)):
                start = index * self.chunk_seconds
                chunk_duration = min(self.chunk_seconds, duration - start)
                chunk_path = Path(temp_dir) / f"chunk_{index:04d}.wav"
                self._chunk_extractor(str(path), str(chunk_path), start, chunk_duration)
                text = self._transcribe_path(model, chunk_path)
                if text:
                    texts.append(text)
        return " ".join(texts).strip()

    def _transcribe_path(self, model: _WhisperModel, path: Path) -> str:
        result = model.transcribe(str(path), language=self.language, fp16=False)
        return " ".join(str((result or {}).get("text") or "").split())

    def _load_model(self) -> _WhisperModel:
        if self._model is None:
            loader = self._model_loader or _load_whisper_model
            self._model = loader(self.model_name)
        return self._model


def probe_audio_duration(audio_path: str) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return float(result.stdout.strip())
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as exc:
        raise RuntimeError(
            "Nao foi possivel determinar a duracao do audio com ffprobe."
        ) from exc


def _extract_audio_chunk(
    source_path: str, destination_path: str, start: float, duration: float
) -> None:
    try:
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}",
                "-i", source_path, "-t", f"{duration:.3f}",
                "-ac", "1", "-ar", "16000", destination_path,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise RuntimeError("Nao foi possivel dividir o audio com ffmpeg.") from exc


def whisper_enabled_from_env() -> bool:
    value = os.getenv("WHISPER_ENABLED")
    if value is None:
        value = os.getenv("AUDIO_TRANSCRIPTION_ENABLED")
    if value is not None:
        return value.strip().lower() in {"1", "true", "yes", "sim", "on"}

    environment = (
        os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("FASTAPI_ENV")
        or "local"
    ).strip().lower()
    return environment not in {"prod", "production", "staging"}


def _env_max_audio_mb() -> float:
    return _to_positive_float(os.getenv("WHISPER_MAX_AUDIO_MB"), default=50.0)


def _env_max_audio_seconds() -> float:
    return _to_positive_float(os.getenv("WHISPER_MAX_AUDIO_SECONDS"), default=1800.0)


def _env_chunk_seconds() -> float:
    return _to_positive_float(os.getenv("WHISPER_CHUNK_SECONDS"), default=60.0)


def _to_positive_float(value: float | int | str | None, default: float) -> float:
    try:
        parsed = float(value) if value not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)
    return parsed if parsed > 0 else float(default)


def _load_whisper_model(model_name: str) -> _WhisperModel:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "Dependencia openai-whisper nao instalada. "
            "Instale com: python -m pip install -r requirements-transcription.txt"
        ) from exc
    return whisper.load_model(model_name)
