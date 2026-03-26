#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/deploy/server.env"
VENV_PYTHON="${ROOT_DIR}/.server-venv/bin/python"
SERVICE_NAME="meeting-assistant"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${1:-}" == "--foreground" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    PYTHON_BIN="python"
  fi
  "${PYTHON_BIN}" "${ROOT_DIR}/deploy/deploy.py" foreground --env-file "${ENV_FILE}"
  exit $?
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

"${PYTHON_BIN}" "${ROOT_DIR}/deploy/deploy.py" prepare --env-file "${ENV_FILE}"

if [[ $EUID -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

${SUDO} tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=Meeting Assistant Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${ROOT_DIR}
ExecStart=${VENV_PYTHON} ${ROOT_DIR}/deploy/service_runner.py --env-file ${ENV_FILE}
Restart=always
RestartSec=5
KillSignal=SIGINT
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

${SUDO} systemctl daemon-reload
${SUDO} systemctl enable --now "${SERVICE_NAME}"
${SUDO} systemctl restart "${SERVICE_NAME}"

echo ""
echo "Meeting Assistant has been deployed as a systemd service."
echo "Service name: ${SERVICE_NAME}"
echo "Status: sudo systemctl status ${SERVICE_NAME}"
echo "Logs:   journalctl -u ${SERVICE_NAME} -f"
