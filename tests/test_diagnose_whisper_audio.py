from pathlib import Path

from scripts import diagnose_whisper_audio


def test_collect_file_metadata(tmp_path):
    audio_path = tmp_path / "mensagem.ogg"
    audio_path.write_bytes(b"audio-falso")

    metadata = diagnose_whisper_audio.collect_file_metadata(audio_path)

    assert metadata == {
        "path": str(audio_path.resolve()),
        "size_bytes": 11,
        "extension": ".ogg",
        "mime_guess": "audio/ogg",
    }


def test_build_ffmpeg_command_converts_to_mono_16khz():
    command = diagnose_whisper_audio.build_ffmpeg_command(
        Path("entrada.ogg"),
        Path("saida.wav"),
    )

    assert command == [
        "ffmpeg",
        "-y",
        "-i",
        "entrada.ogg",
        "-ac",
        "1",
        "-ar",
        "16000",
        "saida.wav",
    ]


def test_parse_args_accepts_model_and_keep_wav():
    args = diagnose_whisper_audio.parse_args(
        ["audio.ogg", "--model", "base", "--keep-wav"]
    )

    assert args.audio_path == Path("audio.ogg")
    assert args.model == "base"
    assert args.keep_wav is True
