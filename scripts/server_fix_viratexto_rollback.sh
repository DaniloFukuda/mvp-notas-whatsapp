#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/deploy/apps/ciclus-rdv"
ROLLBACK_FILE="rollback_viratexto.txt"
TEST_BRANCH="test/viratexto-whatsapp-api"

require_dir() {
    local path="$1"
    local message="$2"
    if [[ ! -d "$path" ]]; then
        echo "ERRO: ${message}: ${path}" >&2
        exit 1
    fi
}

if [[ "$(pwd -P)" != "${APP_DIR}" ]]; then
    echo "ERRO: execute este script dentro de ${APP_DIR}" >&2
    echo "Diretorio atual: $(pwd -P)" >&2
    exit 1
fi

require_dir ".git" "repositorio Git nao encontrado"

echo "Estado atual:"
pwd
git branch --show-current
git rev-parse HEAD
git log --oneline -5
echo ""

if [[ -f "${ROLLBACK_FILE}" ]]; then
    echo "Conteudo atual de ${ROLLBACK_FILE}:"
    cat "${ROLLBACK_FILE}"
else
    echo "Arquivo ${ROLLBACK_FILE} ainda nao existe. A correcao criara um novo arquivo."
fi
echo ""

echo "Reflog recente para identificar a branch/commit anterior:"
git reflog --date=iso -20
echo ""
echo "Use o reflog acima para informar o estado real anterior ao checkout da branch ${TEST_BRANCH}."

read -r -p "Digite a BRANCH anterior para rollback: " BRANCH_ANTERIOR
read -r -p "Digite o COMMIT anterior para rollback: " COMMIT_ANTERIOR

BRANCH_ANTERIOR="$(printf "%s" "${BRANCH_ANTERIOR}" | xargs)"
COMMIT_ANTERIOR="$(printf "%s" "${COMMIT_ANTERIOR}" | xargs)"

if [[ -z "${BRANCH_ANTERIOR}" ]]; then
    echo "ERRO: branch anterior nao pode ficar vazia." >&2
    exit 1
fi

if [[ -z "${COMMIT_ANTERIOR}" ]]; then
    echo "ERRO: commit anterior nao pode ficar vazio." >&2
    exit 1
fi

git cat-file -e "${COMMIT_ANTERIOR}^{commit}"

timestamp="$(date +%Y%m%d_%H%M%S)"
if [[ -f "${ROLLBACK_FILE}" ]]; then
    cp "${ROLLBACK_FILE}" "${ROLLBACK_FILE}.bak_${timestamp}"
    echo "Backup criado: ${ROLLBACK_FILE}.bak_${timestamp}"
fi

current_test_commit="$(git rev-parse HEAD)"
{
    echo "BRANCH_ATUAL=${BRANCH_ANTERIOR}"
    echo "COMMIT_ATUAL=${COMMIT_ANTERIOR}"
    echo "DATA_CORRECAO=$(date -Iseconds)"
    echo "MOTIVO=Correcao manual pos-deploy POC ViraTexto"
    echo "BRANCH_TESTE_ATUAL=${TEST_BRANCH}"
    echo "COMMIT_TESTE_ATUAL=${current_test_commit}"
} > "${ROLLBACK_FILE}"

echo ""
echo "Arquivo ${ROLLBACK_FILE} corrigido:"
cat "${ROLLBACK_FILE}"
echo ""
echo "Comando de rollback disponivel, mas NAO executado por este script:"
echo "bash scripts/server_rollback_viratexto.sh"
