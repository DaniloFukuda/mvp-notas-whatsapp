#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/deploy/apps/ciclus-rdv"
VIRATEXTO_PHONE_VALUE="553172280540"

require_file() {
    local path="$1"
    local message="$2"
    if [[ ! -f "$path" ]]; then
        echo "ERRO: ${message}: ${path}" >&2
        exit 1
    fi
}

env_value() {
    local key="$1"
    awk -F= -v key="${key}" '$1 == key { value=$0; sub("^[^=]*=", "", value); print value }' .env | tail -n 1
}

if [[ "$(pwd -P)" != "${APP_DIR}" ]]; then
    echo "ERRO: execute este script dentro de ${APP_DIR}" >&2
    echo "Diretorio atual: $(pwd -P)" >&2
    exit 1
fi

require_file ".env" ".env nao encontrado"
require_file ".venv/bin/python" "Python do ambiente virtual nao encontrado"
require_file "scripts/test_viratexto_whatsapp.py" "script de envio ViraTexto nao encontrado"

test_mode="$(env_value "VIRATEXTO_TEST_MODE")"
viratexto_phone="$(env_value "VIRATEXTO_PHONE")"

if [[ "${test_mode}" != "true" ]]; then
    echo "ERRO: VIRATEXTO_TEST_MODE precisa estar true no .env." >&2
    exit 1
fi

if [[ "${viratexto_phone}" != "${VIRATEXTO_PHONE_VALUE}" ]]; then
    echo "ERRO: VIRATEXTO_PHONE precisa ser ${VIRATEXTO_PHONE_VALUE} no .env." >&2
    exit 1
fi

mkdir -p logs
touch logs/viratexto_test_log.jsonl

read -r -p "Digite ENVIAR para mandar texto real ao ViraTexto: " confirmation
if [[ "${confirmation}" != "ENVIAR" ]]; then
    echo "Envio cancelado."
    exit 0
fi

.venv/bin/python scripts/test_viratexto_whatsapp.py --to "${VIRATEXTO_PHONE_VALUE}" --text "Ola, teste de integracao"

echo ""
echo "Acompanhe a resposta com:"
echo "tail -f logs/viratexto_test_log.jsonl"
