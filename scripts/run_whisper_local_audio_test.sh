#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Uso:
  bash scripts/run_whisper_local_audio_test.sh --audio /caminho/audio.ogg [--model base] [--language pt] [--output /caminho/transcricao.txt]

Este script transcreve audio ficticio localmente. Nao chama WhatsApp/Meta, nao altera .env e nao faz deploy.
EOF
}

AUDIO=""
MODEL="base"
LANGUAGE="pt"
OUTPUT=""
MAX_AUDIO_BYTES=$((25 * 1024 * 1024))

while [[ $# -gt 0 ]]; do
  case "$1" in
    --audio)
      AUDIO="${2:-}"
      shift 2
      ;;
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    --language)
      LANGUAGE="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Argumento desconhecido: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$AUDIO" ]]; then
  echo "Informe --audio /caminho/audio.ogg" >&2
  usage
  exit 1
fi

if [[ ! -f "$AUDIO" ]]; then
  echo "Arquivo de audio nao encontrado: $AUDIO" >&2
  exit 1
fi

extension="${AUDIO##*.}"
extension="${extension,,}"
case "$extension" in
  ogg|opus|mp3|m4a|wav) ;;
  *)
    echo "Extensao nao suportada. Use: .ogg, .opus, .mp3, .m4a, .wav" >&2
    exit 1
    ;;
esac

audio_bytes=$(wc -c < "$AUDIO")
if [[ "$audio_bytes" -gt "$MAX_AUDIO_BYTES" ]]; then
  echo "Arquivo muito grande. Use audio ficticio de ate 25 MB." >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg nao encontrado no PATH." >&2
  echo "Para instalar no Ubuntu:" >&2
  echo "sudo apt-get update" >&2
  echo "sudo apt-get install -y ffmpeg" >&2
  exit 1
fi

cat <<'EOF'

AVISO DE PRIVACIDADE
- Use apenas audio ficticio.
- Nao use cliente real.
- Nao use CPF, valor sensivel, nome completo, nem dados reais de fazenda ou obra.
- Este teste nao chama WhatsApp, nao chama Meta API, nao altera .env e nao faz deploy.

EOF

read -r -p "Digite TESTAR para transcrever este audio localmente: " CONFIRMATION
if [[ "$CONFIRMATION" != "TESTAR" ]]; then
  echo "Transcricao cancelada."
  exit 0
fi

args=(
  scripts/test_whisper_transcricao.py
  --audio "$AUDIO"
  --model "$MODEL"
  --language "$LANGUAGE"
)

if [[ -n "$OUTPUT" ]]; then
  args+=(--output "$OUTPUT")
fi

python "${args[@]}"
