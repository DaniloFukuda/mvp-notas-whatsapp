#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/deploy/apps/ciclus-rdv"
BRANCH_NAME="test/viratexto-whatsapp-api"
SERVICE_NAME="ciclus-rdv"
VIRATEXTO_PHONE_VALUE="553172280540"
ROLLBACK_FILE="rollback_viratexto.txt"

require_file() {
    local path="$1"
    local message="$2"
    if [[ ! -f "$path" ]]; then
        echo "ERRO: ${message}: ${path}" >&2
        exit 1
    fi
}

require_dir() {
    local path="$1"
    local message="$2"
    if [[ ! -d "$path" ]]; then
        echo "ERRO: ${message}: ${path}" >&2
        exit 1
    fi
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

if [[ "$(pwd -P)" != "${APP_DIR}" ]]; then
    echo "ERRO: execute este script dentro de ${APP_DIR}" >&2
    echo "Diretorio atual: $(pwd -P)" >&2
    exit 1
fi

require_dir ".git" "repositorio Git nao encontrado"
require_file "data/app.db" "banco SQLite nao encontrado"
require_file ".venv/bin/python" "Python do ambiente virtual nao encontrado"
require_file ".env" ".env nao encontrado"

if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "ERRO: sqlite3 nao encontrado no servidor." >&2
    exit 1
fi

current_branch="$(git branch --show-current || true)"
if [[ -z "${current_branch}" ]]; then
    current_branch="DETACHED"
fi
current_commit="$(git rev-parse HEAD)"
timestamp="$(date +%Y%m%d_%H%M%S)"
backup_path="backups/manuais/app_pre_viratexto_${timestamp}.db"

{
    echo "BRANCH_ATUAL=${current_branch}"
    echo "COMMIT_ATUAL=${current_commit}"
    echo "DATA=$(date -Iseconds)"
} > "${ROLLBACK_FILE}"

mkdir -p backups/manuais
sqlite3 data/app.db ".backup '${backup_path}'"
integrity_result="$(sqlite3 "${backup_path}" "PRAGMA integrity_check;")"
if [[ "${integrity_result}" != "ok" ]]; then
    echo "ERRO: integrity_check do backup retornou: ${integrity_result}" >&2
    exit 1
fi

git fetch origin
git checkout "${BRANCH_NAME}"
git pull origin "${BRANCH_NAME}"

.venv/bin/python -m pip install -r requirements.txt

mkdir -p logs
touch logs/viratexto_test_log.jsonl

cp .env ".env.pre_viratexto_${timestamp}"
set_env_var "VIRATEXTO_TEST_MODE" "true"
set_env_var "VIRATEXTO_PHONE" "${VIRATEXTO_PHONE_VALUE}"

.venv/bin/python -m pytest tests/test_viratexto_whatsapp.py
.venv/bin/python -m compileall api_whatsapp.py scripts

sudo systemctl restart "${SERVICE_NAME}"
sudo systemctl status "${SERVICE_NAME}" --no-pager

curl -s http://127.0.0.1:8001/health || true
curl -I https://ciclus.fukudasistemas.com.br/ || true

echo ""
echo "Deploy controlado da POC ViraTexto concluido."
echo "Branch atual: $(git branch --show-current)"
echo "Commit atual: $(git rev-parse HEAD)"
echo "Backup criado: ${backup_path}"
echo "Rollback salvo em: ${ROLLBACK_FILE}"
echo ""
echo "Acompanhar log:"
echo "tail -f logs/viratexto_test_log.jsonl"
echo ""
echo "Teste de texto:"
echo "bash scripts/server_test_viratexto_text.sh"
echo ""
echo "Rollback:"
echo "bash scripts/server_rollback_viratexto.sh"
