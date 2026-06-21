from pathlib import Path
from typing import Callable, Protocol


class _WhisperModel(Protocol):
    def transcribe(self, audio_path: str, language: str = "pt", fp16: bool = False) -> dict:
        ...


class AudioTranscriptionService:
    def __init__(
        self,
        model_name: str = "base",
        language: str = "pt",
        model_loader: Callable[[str], _WhisperModel] | None = None,
    ) -> None:
        self.model_name = str(model_name or "base").strip() or "base"
        self.language = str(language or "pt").strip() or "pt"
        self._model_loader = model_loader
        self._model: _WhisperModel | None = None

    def transcrever(self, audio_path: str) -> str:
        path = Path(audio_path)
        if not path.is_file():
            raise FileNotFoundError(f"Arquivo de audio nao encontrado: {path}")

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


def _load_whisper_model(model_name: str) -> _WhisperModel:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "Dependencia openai-whisper nao instalada. "
            "Instale com: python -m pip install -r requirements-transcription.txt"
        ) from exc
    return whisper.load_model(model_name)
