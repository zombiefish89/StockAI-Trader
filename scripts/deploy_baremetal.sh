#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/deploy_baremetal.sh [options]

Automates pulling the latest code, installing backend dependencies,
building the frontend, and restarting the systemd service on a bare-metal host.

Options:
  --branch <name>        Git branch to deploy (default: main or $DEPLOY_BRANCH)
  --remote <name>        Git remote to pull from (default: origin)
  --python <bin>         Python interpreter for the virtualenv (default: python3.10)
  --venv <path>          Virtualenv directory relative to repo root (default: .venv)
  --service <name>       systemd service name to restart (default: stockai-trader)
  --pip-extras <list>    Optional extras for pip install, comma separated (default: storage,china)
  --skip-git             Skip git fetch/checkout/pull steps
  --skip-frontend        Skip npm install/build (backend only)
  --skip-systemd         Don't restart systemd service after build
  -h, --help             Show this help message

Environment overrides:
  DEPLOY_BRANCH, DEPLOY_REMOTE, PYTHON_BIN, VENV_PATH, SERVICE_NAME,
  PIP_EXTRAS can be exported instead of using CLI flags.
EOF
}

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

REMOTE="${DEPLOY_REMOTE:-origin}"
BRANCH="${DEPLOY_BRANCH:-main}"
PYTHON_BIN="${PYTHON_BIN:-python3.10}"
VENV_PATH="${VENV_PATH:-.venv}"
SERVICE_NAME="${SERVICE_NAME:-stockai-trader}"
PIP_EXTRAS="${PIP_EXTRAS:-storage,china}"

PERFORM_GIT=1
BUILD_FRONTEND=1
RESTART_SYSTEMD=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --remote)
      REMOTE="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --venv)
      VENV_PATH="$2"
      shift 2
      ;;
    --service)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --pip-extras)
      PIP_EXTRAS="$2"
      shift 2
      ;;
    --skip-git)
      PERFORM_GIT=0
      shift 1
      ;;
    --skip-frontend)
      BUILD_FRONTEND=0
      shift 1
      ;;
    --skip-systemd)
      RESTART_SYSTEMD=0
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: '$1' command not found. Please install it first." >&2
    exit 1
  fi
}

require_cmd git
require_cmd "$PYTHON_BIN"

if [[ $BUILD_FRONTEND -eq 1 ]]; then
  require_cmd npm
fi

if [[ ! -d .git ]]; then
  echo "This script must be run from the project root (where .git lives)." >&2
  exit 1
fi

if [[ $PERFORM_GIT -eq 1 ]]; then
  if ! git diff --quiet --ignore-submodules HEAD; then
    echo "Working tree has uncommitted changes. Commit/stash before deploying." >&2
    exit 1
  fi
  git fetch "$REMOTE" "$BRANCH"
  git checkout "$BRANCH"
  git pull --ff-only "$REMOTE" "$BRANCH"
fi

if [[ ! -d "$VENV_PATH" ]]; then
  echo "Creating virtualenv at $VENV_PATH"
  "$PYTHON_BIN" -m venv "$VENV_PATH"
fi

source "$VENV_PATH/bin/activate"
python --version
pip install --upgrade pip setuptools wheel

if [[ -n "$PIP_EXTRAS" ]]; then
  TARGET=".[${PIP_EXTRAS}]"
else
  TARGET="."
fi

echo "Installing backend dependencies: $TARGET"
pip install -e "$TARGET"

if [[ $BUILD_FRONTEND -eq 1 ]]; then
  pushd frontend >/dev/null
  npm ci
  npm run build
  popd >/dev/null
fi

if [[ $RESTART_SYSTEMD -eq 1 ]]; then
  if command -v systemctl >/dev/null 2>&1; then
    SYSTEMCTL_PREFIX=""
    if command -v sudo >/dev/null 2>&1; then
      SYSTEMCTL_PREFIX="sudo"
    fi
    echo "Restarting systemd service: $SERVICE_NAME"
    $SYSTEMCTL_PREFIX systemctl daemon-reload
    $SYSTEMCTL_PREFIX systemctl restart "$SERVICE_NAME"
    $SYSTEMCTL_PREFIX systemctl status "$SERVICE_NAME" --no-pager --full
  else
    echo "systemctl not available; skipping service restart"
  fi
fi

echo "\nDeployment complete. Current git revision: $(git rev-parse --short HEAD)"
