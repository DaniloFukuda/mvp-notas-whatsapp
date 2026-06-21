#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/deploy/apps/ciclus-rdv"
SERVICE_NAME="ciclus-rdv"
ROLLBACK_FILE="rollback_viratexto.txt"

require_file() {
    local path="$1"
    local message="$2"
    if [[ ! -f "$path" ]]; then
        echo "ERRO: ${message}: ${path}" >&2
        exit 1
    fi
}

read_rollback_value() {
    local key="$1"
    awk -F= -v key="${key}" '$1 == key { value=$0; sub("^[^=]*=", "", value); print value }' "${ROLLBACK_FILE}" | tail -n 1
}

set_env_var() {
    local key="$1"
    local value="$2"
    local tmp_file
    tmp_file="$(mktemp)"
    awk -v key="${key}" 'index($0, key "=") != 1 { print }' .env > "${tmp_file}"
    printf "%s=%s\n" "${key}" "${value}" >> "${tmp_file}"
    cat "${tmp_file}" > .env
    rm -f "${tmp_file}"
}

remove_env_var() {
    local key="$1"
    local tmp_file
    tmp_file="$(mktemp)"
    awk -v key="${key}" 'index($0, key "=") != 1 { print }' .env > "${tmp_file}"
    cat "${tmp_file}" > .env
    rm -f "${tmp_file}"
}

if [[ "$(pwd -P)" != "${APP_DIR}" ]]; then
    echo "ERRO: execute este script dentro de ${APP_DIR}" >&2
    echo "Diretorio atual: $(pwd -P)" >&2
    exit 1
fi

require_file "${ROLLBACK_FILE}" "arquivo de rollback nao encontrado"
require_file ".env" ".env nao encontrado"

BRANCH_ATUAL="$(read_rollback_value "BRANCH_ATUAL")"
COMMIT_ATUAL="$(read_rollback_value "COMMIT_ATUAL")"

if [[ -z "${BRANCH_ATUAL}" || -z "${COMMIT_ATUAL}" ]]; then
    echo "ERRO: rollback_viratexto.txt nao contem BRANCH_ATUAL e COMMIT_ATUAL validos." >&2
    exit 1
fi

echo "Rollback preparado para:"
echo "Branch anterior: ${BRANCH_ATUAL}"
echo "Commit anterior: ${COMMIT_ATUAL}"
echo ""
read -r -p "Digite VOLTAR para executar rollback: " confirmation
if [[ "${confirmation}" != "VOLTAR" ]]; then
    echo "Rollback cancelado."
    exit 0
fi

if [[ "${BRANCH_ATUAL}" != "DETACHED" ]]; then
    git checkout "${BRANCH_ATUAL}"
fi
git reset --hard "${COMMIT_ATUAL}"

timestamp="$(date +%Y%m%d_%H%M%S)"
cp .env ".env.pre_rollback_viratexto_${timestamp}"
set_env_var "VIRATEXTO_TEST_MODE" "false"
remove_env_var "VIRATEXTO_PHONE"

sudo systemctl restart "${SERVICE_NAME}"
sudo systemctl status "${SERVICE_NAME}" --no-pager

curl -s http://127.0.0.1:8001/health || true
curl -I https://ciclus.fukudasistemas.com.br/ || true

echo ""
echo "Rollback concluido para commit ${COMMIT_ATUAL}."
echo "VIRATEXTO_TEST_MODE=false aplicado e VIRATEXTO_PHONE removido do .env."
