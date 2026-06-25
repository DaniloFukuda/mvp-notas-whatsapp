import os
from pathlib import Path
from typing import Callable, Protocol


class _WhisperModel(Protocol):
    def transcribe(self, audio_path: str, language: str = "pt", fp16: bool = False) -> dict:
        ...


class AudioTranscriptionService:
    def __init__(
        self,
        model_name: str = "tiny",
        language: str = "pt",
        max_audio_mb: float | int | str | None = None,
        model_loader: Callable[[str], _WhisperModel] | None = None,
    ) -> None:
        self.model_name = str(model_name or "tiny").strip() or "tiny"
        self.language = str(language or "pt").strip() or "pt"
        self.max_audio_mb = _to_positive_float(max_audio_mb, default=_env_max_audio_mb())
        self._model_loader = model_loader
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
            model_loader=model_loader,
        )

    def transcrever(self, audio_path: str) -> str:
        path = Path(audio_path)
        if not path.is_file():
            raise FileNotFoundError(f"Arquivo de audio nao encontrado: {path}")
        max_bytes = int(self.max_audio_mb * 1024 * 1024)
        if max_bytes > 0 and path.stat().st_size > max_bytes:
            raise ValueError(
                f"Arquivo de audio excede o limite de {self.max_audio_mb:g} MB."
            )

        model = self._load_model()
        result = model.transcribe(
            str(path),
            language=self.language,
            fp16=False,
        )
        return str((result or {}).get("text") or "").strip()

    def _load_model(self) -> _WhisperModel:
        if self._model is not None:
            return self._model

        loader = self._model_loader or _load_whisper_model
        self._model = loader(self.model_name)
        return self._model


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
    return _to_positive_float(os.getenv("WHISPER_MAX_AUDIO_MB"), default=25.0)


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
