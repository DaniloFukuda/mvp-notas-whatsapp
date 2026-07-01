#!/usr/bin/env python3
"""Diagnostica a transcrição Whisper de um áudio sem passar pelo webhook."""

from __future__ import annotations

import argparse
import mimetypes
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.audio_transcription_service import AudioTranscriptionService


WHISPER_ENV_VARS = (
    "WHISPER_MODEL",
    "WHISPER_LANGUAGE",
    "WHISPER_CHUNK_SECONDS",
    "WHISPER_MAX_AUDIO_SECONDS",
    "WHISPER_MAX_AUDIO_MB",
)
SUPPORTED_MODELS = ("tiny", "base", "small")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compara a transcrição Whisper do áudio original com uma cópia WAV "
            "mono em 16 kHz."
        )
    )
    parser.add_argument("audio_path", type=Path, help="Caminho do arquivo de áudio")
    parser.add_argument(
        "--model",
        choices=SUPPORTED_MODELS,
        help="Sobrescreve WHISPER_MODEL somente neste processo",
    )
    parser.add_argument(
        "--keep-wav",
        action="store_true",
        help="Mantém o WAV convertido após o diagnóstico",
    )
    return parser.parse_args(argv)


def collect_file_metadata(path: Path) -> dict[str, str | int | None]:
    absolute_path = path.expanduser().resolve()
    mime_type, _ = mimetypes.guess_type(absolute_path.name)
    return {
        "path": str(absolute_path),
        "size_bytes": absolute_path.stat().st_size,
        "extension": absolute_path.suffix.lower() or "(sem extensão)",
        "mime_guess": mime_type,
    }


def build_ffprobe_command(path: Path) -> list[str]:
    return [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        build_ffprobe_command(path),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return float(result.stdout.strip())


def build_ffmpeg_command(source: Path, destination: Path) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(destination),
    ]


def convert_to_wav(source: Path, destination: Path) -> None:
    subprocess.run(
        build_ffmpeg_command(source, destination),
        check=True,
        timeout=300,
    )


def print_file_diagnostics(label: str, path: Path) -> bool:
    print(f"\n{label}:")
    try:
        metadata = collect_file_metadata(path)
        print(f"- caminho absoluto: {metadata['path']}")
        print(f"- tamanho em bytes: {metadata['size_bytes']}")
        print(f"- extensão: {metadata['extension']}")
        print(f"- mime guess: {metadata['mime_guess'] or 'desconhecido'}")
        print(f"- duração via ffprobe: {probe_duration(path):.3f} segundos")
        return True
    except Exception:
        print("- FALHA ao inspecionar o arquivo:", file=sys.stderr)
        traceback.print_exc()
        return False


def transcribe_with_diagnostics(
    service: AudioTranscriptionService,
    label: str,
    path: Path,
) -> bool:
    print(f"\nTranscrição do {label}:")
    try:
        text = service.transcrever(str(path))
        print("- status: sucesso")
        print(f"- texto: {text if text else '(vazio)'}")
        return True
    except Exception:
        print("- status: falha", file=sys.stderr)
        traceback.print_exc()
        return False


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    source = args.audio_path.expanduser().resolve()
    if not source.is_file():
        print(f"Arquivo de áudio não encontrado: {source}", file=sys.stderr)
        return 1

    if args.model:
        os.environ["WHISPER_MODEL"] = args.model

    service = AudioTranscriptionService.from_env()

    print("Configuração Whisper:")
    for name in WHISPER_ENV_VARS:
        print(f"- {name}: {os.getenv(name, '(não definida)')}")
    print(f"- modelo usado: {service.model_name}")
    print(f"- idioma usado: {service.language}")

    print_file_diagnostics("Áudio original", source)

    temporary = tempfile.NamedTemporaryFile(
        prefix="whisper_diagnostico_",
        suffix=".wav",
        delete=False,
    )
    wav_path = Path(temporary.name)
    temporary.close()
    wav_ready = False

    try:
        print("\nConversão ffmpeg:")
        print(f"- comando: {' '.join(build_ffmpeg_command(source, wav_path))}")
        try:
            convert_to_wav(source, wav_path)
            wav_ready = True
            print("- status: sucesso")
            print_file_diagnostics("WAV mono 16 kHz", wav_path)
        except Exception:
            print("- status: falha", file=sys.stderr)
            traceback.print_exc()

        original_ok = transcribe_with_diagnostics(service, "áudio original", source)
        wav_ok = (
            transcribe_with_diagnostics(service, "WAV convertido", wav_path)
            if wav_ready
            else False
        )
        return 0 if original_ok or wav_ok else 1
    finally:
        if args.keep_wav:
            print(f"\nWAV mantido em: {wav_path}")
        else:
            wav_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
