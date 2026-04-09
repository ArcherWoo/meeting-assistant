#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/deploy/server.env"
VENV_PYTHON="${ROOT_DIR}/.server-venv/bin/python"
SERVICE_NAME="meeting-assistant"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
RENDERED_NGINX="${ROOT_DIR}/deploy/nginx/rendered/meeting-assistant.linux.rendered.conf"

info() { printf '[INFO] %s\n' "$1"; }
ok() { printf '[OK] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; }
err() { printf '[ERR] %s\n' "$1"; }

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh
  ./deploy.sh --foreground
  ./deploy.sh --prepare
  ./deploy.sh --stop
  ./deploy.sh --stop --stop-nginx
  ./deploy.sh --help
EOF
}

read_env_value() {
  local key="$1"
  local default_value="${2:-}"
  if [[ ! -f "${ENV_FILE}" ]]; then
    printf '%s' "${default_value}"
    return
  fi
  local line
  line="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n 1 || true)"
  if [[ -z "${line}" ]]; then
    printf '%s' "${default_value}"
  else
    printf '%s' "${line#*=}"
  fi
}

wait_health() {
  local url="$1"
  local timeout_sec="${2:-45}"
  local start_ts
  start_ts="$(date +%s)"
  while true; do
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS "${url}" >/dev/null 2>&1; then
        return 0
      fi
    elif command -v wget >/dev/null 2>&1; then
      if wget -qO- "${url}" >/dev/null 2>&1; then
        return 0
      fi
    fi
    if (( "$(date +%s)" - start_ts >= timeout_sec )); then
      return 1
    fi
    sleep 1
  done
}

get_network_ipv4_addresses() {
  if command -v ip >/dev/null 2>&1; then
    ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | awk '
      /^192\.168\./ { print "1 " $0; next }
      /^(172\.(1[6-9]|2[0-9]|3[0-1])\.|10\.)/ { print "2 " $0; next }
      { print "3 " $0 }
    ' | sort -k1,1 -k2,2 | cut -d' ' -f2-
    return
  fi

  if command -v hostname >/dev/null 2>&1; then
    hostname -I 2>/dev/null | tr ' ' '\n' | sed '/^$/d' | awk '
      /^192\.168\./ { print "1 " $0; next }
      /^(172\.(1[6-9]|2[0-9]|3[0-1])\.|10\.)/ { print "2 " $0; next }
      { print "3 " $0 }
    ' | sort -k1,1 -k2,2 | cut -d' ' -f2-
  fi
}

show_service_endpoints() {
  local host="$1"
  local port="$2"

  echo "智枢前端:"
  if [[ -z "${host}" || "${host}" == "0.0.0.0" || "${host}" == "*" ]]; then
    echo "  http://localhost:${port}/"
    while IFS= read -r ip; do
      [[ -z "${ip}" ]] && continue
      echo "  http://${ip}:${port}/"
    done < <(get_network_ipv4_addresses)
  else
    echo "  http://${host}:${port}/"
  fi

  echo "后端接口:"
  if [[ -z "${host}" || "${host}" == "0.0.0.0" || "${host}" == "*" ]]; then
    echo "  http://localhost:${port}/api"
    while IFS= read -r ip; do
      [[ -z "${ip}" ]] && continue
      echo "  http://${ip}:${port}/api"
    done < <(get_network_ipv4_addresses)
  else
    echo "  http://${host}:${port}/api"
  fi
}

detect_python_bin() {
  local candidate="${PYTHON_BIN:-python3}"
  if command -v "${candidate}" >/dev/null 2>&1; then
    printf '%s' "${candidate}"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s' "python"
    return
  fi
  err "未检测到可用的 Python，请先安装 Python 3.10+。"
  exit 1
}

MODE="service"
STOP_NGINX=0
for arg in "$@"; do
  case "${arg}" in
    --foreground)
      MODE="foreground"
      ;;
    --prepare)
      MODE="prepare"
      ;;
    --stop)
      MODE="stop"
      ;;
    --stop-nginx)
      STOP_NGINX=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      err "不支持的参数：${arg}"
      usage
      exit 1
      ;;
  esac
done

PYTHON_BIN="$(detect_python_bin)"

if [[ "${MODE}" == "foreground" ]]; then
  exec "${PYTHON_BIN}" "${ROOT_DIR}/deploy/deploy.py" foreground --env-file "${ENV_FILE}"
fi

if [[ "${MODE}" == "prepare" ]]; then
  exec "${PYTHON_BIN}" "${ROOT_DIR}/deploy/deploy.py" prepare --env-file "${ENV_FILE}"
fi

if [[ "${MODE}" == "stop" ]]; then
  if [[ "${EUID}" -ne 0 ]]; then
    SUDO="sudo"
  else
    SUDO=""
  fi
  ${SUDO} systemctl stop "${SERVICE_NAME}"
  ok "应用服务已优雅停止"
  if [[ "${STOP_NGINX}" -eq 1 ]]; then
    if command -v nginx >/dev/null 2>&1; then
      ${SUDO} nginx -s quit || true
      ok "Nginx 已优雅停止"
    else
      warn "未检测到 nginx 命令，已跳过 Nginx 停止步骤"
    fi
  fi
  exit 0
fi

info "准备生产环境"
"${PYTHON_BIN}" "${ROOT_DIR}/deploy/deploy.py" prepare --env-file "${ENV_FILE}"

if [[ "${EUID}" -ne 0 ]]; then
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

HOST_VALUE="$(read_env_value "MEETING_ASSISTANT_HOST" "0.0.0.0")"
PORT="$(read_env_value "MEETING_ASSISTANT_PORT" "5173")"
HEALTH_URL="http://127.0.0.1:${PORT}/api/health/live"
READY_URL="http://127.0.0.1:${PORT}/api/health/ready"

info "等待服务就绪：${HEALTH_URL}"
if ! wait_health "${HEALTH_URL}" 60; then
  err "服务没有在预期时间内启动成功。"
  ${SUDO} systemctl status "${SERVICE_NAME}" --no-pager || true
  ${SUDO} journalctl -u "${SERVICE_NAME}" -n 40 --no-pager || true
  exit 1
fi

if ! wait_health "${READY_URL}" 20; then
  warn "存活检查已通过，但就绪检查暂未通过。你可以稍后手动查看：${READY_URL}"
fi

echo ""
ok "Meeting Assistant 已完成 Linux 一键部署"
echo "服务名称:         ${SERVICE_NAME}"
echo "存活检查:         ${HEALTH_URL}"
echo "就绪检查:         ${READY_URL}"
echo "环境文件:         ${ENV_FILE}"
echo "Nginx 配置:       ${RENDERED_NGINX}"
echo ""
show_service_endpoints "${HOST_VALUE}" "${PORT}"
echo ""
echo "常用命令:"
echo "  查看状态: sudo systemctl status ${SERVICE_NAME}"
echo "  查看日志: sudo journalctl -u ${SERVICE_NAME} -f"
echo "  仅准备环境: ./deploy.sh --prepare"
echo "  前台启动: ./deploy.sh --foreground"
echo "  优雅停止应用: ./deploy.sh --stop"
echo "  优雅停止应用和 Nginx: ./deploy.sh --stop --stop-nginx"
