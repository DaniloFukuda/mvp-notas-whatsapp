#!/usr/bin/env python3
"""Validate one local audio file with the application's Whisper service.

The transcript is never printed. No WhatsApp, Meta, storage, or remote
transcription boundary is used by this utility.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.audio_transcription_service import AudioTranscriptionService


def probe_audio(path: Path) -> dict[str, object] | None:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name,duration",
                "-show_entries",
                "stream=codec_name,codec_type",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        payload = json.loads(completed.stdout)
        audio_stream = next(
            stream
            for stream in payload.get("streams", [])
            if stream.get("codec_type") == "audio"
        )
        duration = float(payload.get("format", {}).get("duration") or 0)
        if duration <= 0:
            return None
        return {
            "duration": duration,
            "container": str(payload.get("format", {}).get("format_name") or "unknown"),
            "codec": str(audio_stream.get("codec_name") or "unknown"),
        }
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration, json.JSONDecodeError):
        return None


def validate(path: Path, service: AudioTranscriptionService | None = None) -> int:
    metadata = probe_audio(path) if path.is_file() else None
    print(f"audio_valid={str(metadata is not None).lower()}")
    if metadata is None:
        print("duration_seconds=0")
        print("mime/container=unknown")
        print("codec=unknown")
        print("transcription_success=false")
        print("transcript_non_empty=false")
        print("transcript_length=0")
        print("error_code=INVALID_AUDIO")
        return 2

    print(f"duration_seconds={float(metadata['duration']):.3f}")
    print(f"mime/container={metadata['container']}")
    print(f"codec={metadata['codec']}")
    started = time.perf_counter()
    try:
        result = (service or AudioTranscriptionService.from_env()).transcrever_com_resultado(
            str(path)
        )
    except Exception as exc:
        print("transcription_success=false")
        print("transcript_non_empty=false")
        print("transcript_length=0")
        print(f"error_code={type(exc).__name__}")
        print(f"transcription_seconds={time.perf_counter() - started:.3f}")
        return 1

    text = str(result.raw_text or "").strip()
    print(f"transcription_success={str(bool(result.ok)).lower()}")
    print(f"transcript_non_empty={str(bool(text)).lower()}")
    print(f"transcript_length={len(text)}")
    print(f"error_code={result.error_code or 'none'}")
    print(f"transcription_seconds={time.perf_counter() - started:.3f}")
    return 0 if result.ok and text else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate local audio without printing its transcript")
    parser.add_argument("audio_path", type=Path)
    args = parser.parse_args(argv)
    return validate(args.audio_path.expanduser().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
