#!/usr/bin/env bash

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vctresenha}"
BRANCH="${1:-${DEPLOY_BRANCH:-main}}"

echo "[deploy] app dir: ${APP_DIR}"
echo "[deploy] branch: ${BRANCH}"

if [[ ! -d "${APP_DIR}" ]]; then
    echo "[deploy] diretorio nao encontrado: ${APP_DIR}" >&2
    exit 1
fi

cd "${APP_DIR}"

if [[ ! -d .git ]]; then
    echo "[deploy] este diretorio nao e um clone git: ${APP_DIR}" >&2
    exit 1
fi

git fetch --all --prune
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

if [[ ! -d .venv ]]; then
    python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

systemctl daemon-reload
systemctl restart vctresenha-portal

if systemctl list-unit-files | grep -q '^vctresenha-discord-bot.service'; then
    systemctl restart vctresenha-discord-bot
fi

systemctl --no-pager --full status vctresenha-portal

if systemctl list-unit-files | grep -q '^vctresenha-discord-bot.service'; then
    systemctl --no-pager --full status vctresenha-discord-bot
fi

echo "[deploy] concluido com sucesso"