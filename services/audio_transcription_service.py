import logging
import math
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol


logger = logging.getLogger(__name__)

DEFAULT_WHISPER_MODEL = "base"
DEFAULT_WHISPER_INITIAL_PROMPT = (
    "Transcrição em português do Brasil. Termos possíveis: WhatsApp, Codex, "
    "OpenAI, ChatGPT, Python, Git, branch, commit, pull request, deploy, servidor, "
    "webhook, Ciclus, OLT, contentor, aluguer, RDV, visita técnica."
)
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
    def transcribe(self, audio_path: str, **kwargs) -> dict:
        ...


class AudioTranscriptionService:
    def __init__(
        self,
        model_name: str = DEFAULT_WHISPER_MODEL,
        language: str = "pt",
        max_audio_mb: float | int | str | None = None,
        max_audio_seconds: float | int | str | None = None,
        chunk_seconds: float | int | str | None = None,
        model_loader: Callable[[str], _WhisperModel] | None = None,
        duration_probe: Callable[[str], float] | None = None,
        chunk_extractor: Callable[[str, str, float, float], None] | None = None,
        audio_preprocessor: Callable[[str, str], None] | None = None,
        preprocess_audio: bool | str | None = None,
        temperature: float | int | str | None = None,
        initial_prompt: str | None = None,
        keep_failed_audio: bool | str | None = None,
        failed_audio_dir: str | Path = "data/debug_audio",
    ) -> None:
        self.model_name = str(model_name or DEFAULT_WHISPER_MODEL).strip() or DEFAULT_WHISPER_MODEL
        self.language = str(language or "pt").strip() or "pt"
        self.max_audio_mb = _to_positive_float(max_audio_mb, default=_env_max_audio_mb())
        self.max_audio_seconds = _to_positive_float(
            max_audio_seconds, default=_env_max_audio_seconds()
        )
        self.chunk_seconds = _to_positive_float(chunk_seconds, default=_env_chunk_seconds())
        self._model_loader = model_loader
        self._duration_probe = duration_probe or probe_audio_duration
        self._chunk_extractor = chunk_extractor or _extract_audio_chunk
        self._audio_preprocessor = audio_preprocessor or _preprocess_audio
        self.preprocess_audio = _to_bool(
            preprocess_audio,
            default=_env_preprocess_audio(),
        )
        self.temperature = _to_float(temperature, default=_env_temperature())
        self.initial_prompt = (
            DEFAULT_WHISPER_INITIAL_PROMPT
            if initial_prompt is None
            else str(initial_prompt).strip()
        )
        self.keep_failed_audio = _to_bool(
            keep_failed_audio,
            default=_env_keep_failed_audio(),
        )
        self.failed_audio_dir = Path(failed_audio_dir)
        self._model: _WhisperModel | None = None

    @classmethod
    def from_env(
        cls,
        model_loader: Callable[[str], _WhisperModel] | None = None,
    ) -> "AudioTranscriptionService":
        return cls(
            model_name=os.getenv("WHISPER_MODEL", DEFAULT_WHISPER_MODEL),
            language=os.getenv("WHISPER_LANGUAGE", "pt"),
            max_audio_mb=os.getenv("WHISPER_MAX_AUDIO_MB"),
            max_audio_seconds=os.getenv("WHISPER_MAX_AUDIO_SECONDS"),
            chunk_seconds=os.getenv("WHISPER_CHUNK_SECONDS"),
            preprocess_audio=os.getenv("WHISPER_PREPROCESS_AUDIO"),
            temperature=os.getenv("WHISPER_TEMPERATURE"),
            initial_prompt=os.getenv(
                "WHISPER_INITIAL_PROMPT",
                DEFAULT_WHISPER_INITIAL_PROMPT,
            ),
            keep_failed_audio=os.getenv("WHISPER_KEEP_FAILED_AUDIO"),
            model_loader=model_loader,
        )

    def transcrever(self, audio_path: str) -> str:
        path = Path(audio_path)
        duration_holder: list[float | None] = [None]
        try:
            return self._transcrever(path, duration_holder)
        except Exception:
            self._preserve_failed_audio(path, duration_holder[0])
            raise

    def _transcrever(self, path: Path, duration_holder: list[float | None]) -> str:
        if not path.is_file():
            raise FileNotFoundError(f"Arquivo de audio nao encontrado: {path}")

        size_bytes = path.stat().st_size
        if size_bytes > int(self.max_audio_mb * 1024 * 1024):
            raise AudioLimitExceededError(AUDIO_TOO_LONG_MESSAGE)

        duration = self._duration_probe(str(path))
        duration_holder[0] = duration
        logger.info(
            "Diagnostico Whisper: arquivo=%s tamanho_bytes=%s duracao_segundos=%.3f modelo=%s idioma=%s chunk_segundos=%.3f",
            path,
            size_bytes,
            duration,
            self.model_name,
            self.language,
            self.chunk_seconds,
        )
        if duration <= 0:
            raise RuntimeError("Nao foi possivel determinar a duracao do audio.")
        if duration > self.max_audio_seconds:
            raise AudioLimitExceededError(AUDIO_TOO_LONG_MESSAGE)

        model = self._load_model()
        logger.info(
            "Preprocessamento de audio Whisper: ativado=%s arquivo=%s",
            self.preprocess_audio,
            path,
        )
        if self.preprocess_audio:
            with tempfile.TemporaryDirectory(prefix="whisper_preprocess_") as temp_dir:
                wav_path = Path(temp_dir) / "audio_preprocessado.wav"
                try:
                    self._audio_preprocessor(str(path), str(wav_path))
                    wav_size_bytes = wav_path.stat().st_size
                    wav_duration = self._duration_probe(str(wav_path))
                    if wav_size_bytes <= 0 or wav_duration <= 0:
                        raise RuntimeError(
                            "WAV preprocessado vazio ou com duracao invalida."
                        )
                    logger.info(
                        "Audio Whisper preprocessado: caminho=%s "
                        "tamanho_bytes=%s duracao_segundos=%.3f",
                        wav_path,
                        wav_size_bytes,
                        wav_duration,
                    )
                except Exception as exc:
                    logger.exception(
                        "Falha no preprocessamento de audio Whisper; "
                        "usando arquivo original: arquivo=%s erro=%s",
                        path,
                        exc,
                    )
                else:
                    return self._transcribe_prepared(model, wav_path, wav_duration)
        return self._transcribe_prepared(model, path, duration)

    def _transcribe_prepared(
        self,
        model: _WhisperModel,
        path: Path,
        duration: float,
    ) -> str:
        if duration <= self.chunk_seconds:
            return self._transcribe_path(model, path)

        texts: list[str] = []
        with tempfile.TemporaryDirectory(prefix="whisper_chunks_") as temp_dir:
            for index in range(math.ceil(duration / self.chunk_seconds)):
                start = index * self.chunk_seconds
                chunk_duration = min(self.chunk_seconds, duration - start)
                chunk_path = Path(temp_dir) / f"chunk_{index:04d}.wav"
                self._chunk_extractor(str(path), str(chunk_path), start, chunk_duration)
                chunk_size_bytes = chunk_path.stat().st_size if chunk_path.exists() else 0
                logger.info(
                    "Diagnostico Whisper chunk: indice=%s arquivo=%s tamanho_bytes=%s inicio=%.3f duracao_segundos=%.3f modelo=%s",
                    index,
                    chunk_path,
                    chunk_size_bytes,
                    start,
                    chunk_duration,
                    self.model_name,
                )
                text = self._transcribe_path(model, chunk_path)
                if text:
                    texts.append(text)
        return " ".join(texts).strip()

    def _preserve_failed_audio(
        self,
        source_path: Path,
        duration: float | None,
    ) -> Path | None:
        if not self.keep_failed_audio or not source_path.is_file():
            return None

        try:
            self.failed_audio_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            destination = self.failed_audio_dir / f"{timestamp}_{source_path.name}"
            shutil.copy2(source_path, destination)
            size_bytes = destination.stat().st_size
            if duration is None:
                try:
                    duration = self._duration_probe(str(source_path))
                except Exception:
                    duration = None
            duration_text = f"{duration:.3f}" if duration is not None else "indisponivel"
            logger.exception(
                "Audio preservado para diagnostico: caminho=%s tamanho_bytes=%s "
                "duracao_segundos=%s modelo=%s",
                destination,
                size_bytes,
                duration_text,
                self.model_name,
            )
            return destination
        except Exception:
            logger.exception(
                "Falha ao preservar audio para diagnostico: arquivo=%s modelo=%s",
                source_path,
                self.model_name,
            )
            return None

    def _transcribe_path(self, model: _WhisperModel, path: Path) -> str:
        size_bytes = path.stat().st_size if path.exists() else 0
        try:
            logger.info(
                "Whisper transcribe iniciado: arquivo=%s tamanho_bytes=%s modelo=%s idioma=%s",
                path,
                size_bytes,
                self.model_name,
                self.language,
            )
            transcribe_options: dict[str, object] = {
                "language": self.language,
                "fp16": False,
                "temperature": self.temperature,
            }
            if self.initial_prompt:
                transcribe_options["initial_prompt"] = self.initial_prompt
            result = model.transcribe(str(path), **transcribe_options)
            text = " ".join(str((result or {}).get("text") or "").split())
            logger.info(
                "Whisper transcribe concluido: arquivo=%s tamanho_bytes=%s modelo=%s texto_chars=%s texto_vazio=%s",
                path,
                size_bytes,
                self.model_name,
                len(text),
                not bool(text),
            )
            return text
        except Exception:
            logger.exception(
                "Whisper transcribe falhou: arquivo=%s tamanho_bytes=%s modelo=%s idioma=%s",
                path,
                size_bytes,
                self.model_name,
                self.language,
            )
            raise

    def _load_model(self) -> _WhisperModel:
        if self._model is None:
            loader = self._model_loader or _load_whisper_model
            logger.info("Carregando modelo Whisper: modelo=%s", self.model_name)
            self._model = loader(self.model_name)
            logger.info("Modelo Whisper carregado: modelo=%s", self.model_name)
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


def _preprocess_audio(source_path: str, destination_path: str) -> None:
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                source_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-af",
                "highpass=f=80,lowpass=f=8000,dynaudnorm=f=150:g=15",
                destination_path,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=180,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise RuntimeError(
            "Nao foi possivel preprocessar o audio com ffmpeg."
        ) from exc


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


def _env_preprocess_audio() -> bool:
    return _to_bool(os.getenv("WHISPER_PREPROCESS_AUDIO"), default=True)


def _env_temperature() -> float:
    return _to_float(os.getenv("WHISPER_TEMPERATURE"), default=0.0)


def _env_keep_failed_audio() -> bool:
    return _to_bool(os.getenv("WHISPER_KEEP_FAILED_AUDIO"), default=True)


def _to_bool(value: bool | str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "sim", "on"}


def _to_positive_float(value: float | int | str | None, default: float) -> float:
    try:
        parsed = float(value) if value not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)
    return parsed if parsed > 0 else float(default)


def _to_float(value: float | int | str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def _load_whisper_model(model_name: str) -> _WhisperModel:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "Dependencia openai-whisper nao instalada. "
            "Instale com: python -m pip install -r requirements-transcription.txt"
        ) from exc
    return whisper.load_model(model_name)
