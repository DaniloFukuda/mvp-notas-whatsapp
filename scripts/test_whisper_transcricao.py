import argparse
import os
import shutil
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from services.audio_transcription_service import AudioTranscriptionService


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()

    args = parse_args()
    audio_path = Path(args.audio)
    if not audio_path.is_file():
        print(f"Erro: arquivo de audio nao encontrado: {audio_path}")
        return 1

    if shutil.which("ffmpeg") is None:
        print("Aviso: ffmpeg nao encontrado no PATH. O Whisper pode falhar ao ler o audio.")

    model_name = args.model or os.getenv("WHISPER_MODEL", "").strip() or "tiny"
    language = args.language or os.getenv("WHISPER_LANGUAGE", "").strip() or "pt"

    started = time.perf_counter()
    try:
        text = AudioTranscriptionService(model_name=model_name, language=language).transcrever(
            str(audio_path)
        )
    except Exception as exc:
        print(f"Erro ao transcrever: {safe_error(exc)}")
        return 1
    elapsed = time.perf_counter() - started

    print(f"modelo: {model_name}")
    print(f"idioma: {language}")
    print(f"tempo_segundos: {elapsed:.2f}")
    print("texto_transcrito:")
    print(text)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        print(f"transcricao_salva_em: {output_path}")

    if not args.keep_audio:
        print("audio_original: preservado; o script local nao remove arquivos informados pelo usuario.")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcreve um audio local usando Whisper.")
    parser.add_argument("--audio", required=True, help="Caminho do arquivo de audio.")
    parser.add_argument("--model", default="", help="Modelo Whisper. Default: WHISPER_MODEL ou tiny.")
    parser.add_argument("--language", default="", help="Idioma. Default: WHISPER_LANGUAGE ou pt.")
    parser.add_argument("--keep-audio", action="store_true", help="Compatibilidade: nao remove audio local.")
    parser.add_argument("--output", default="", help="Arquivo .txt opcional para salvar a transcricao.")
    return parser.parse_args()


def safe_error(exc: Exception) -> str:
    return str(exc or exc.__class__.__name__).replace("\r", " ").replace("\n", " ")[:500]


if __name__ == "__main__":
    sys.exit(main())
