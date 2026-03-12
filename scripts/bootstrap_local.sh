#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VIVARIA_DIR="$PROJECT_DIR/vivaria"
VENV_DIR="$PROJECT_DIR/.venv-cli"
VIVARIA_COMPOSE_ENV="$VIVARIA_DIR/.env"

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

require_cmd uv
require_cmd python3.11
require_cmd docker

set_env_var() {
    local file="$1"
    local key="$2"
    local value="$3"

    if [[ -f "$file" ]] && rg -q "^${key}=" "$file"; then
        perl -0pi -e "s/^${key}=.*\$/${key}=${value}/m" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}

if [[ ! -f "$VIVARIA_DIR/.env.server" || ! -f "$VIVARIA_DIR/.env.db" ]]; then
    (cd "$VIVARIA_DIR" && ./scripts/setup-docker-compose.sh)
fi

if [[ "$(uname)" == "Darwin" ]]; then
    DOCKER_SOCKET_GID=0
else
    DOCKER_SOCKET_GID="$(stat -f '%g' /var/run/docker.sock)"
fi

MIDDLEMAN_TYPE="noop"
if rg -q '^(OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY)=.+' "$VIVARIA_DIR/.env.server"; then
    MIDDLEMAN_TYPE="builtin"
fi

RUN_INITIAL_SCORING="false"
if [[ "$MIDDLEMAN_TYPE" == "builtin" ]]; then
    RUN_INITIAL_SCORING="true"
fi

set_env_var "$VIVARIA_DIR/.env.server" VM_HOST_MAX_CPU 1.0
set_env_var "$VIVARIA_DIR/.env.server" VM_HOST_MAX_MEMORY 0.95
set_env_var "$VIVARIA_DIR/.env.server" VIVARIA_TASK_INSTALL_PLAYWRIGHT false
set_env_var "$VIVARIA_DIR/.env.server" VIVARIA_RUN_INITIAL_SCORING "$RUN_INITIAL_SCORING"
set_env_var "$VIVARIA_DIR/.env.server" VIVARIA_LOCAL_TASK_MAX_CPU 4
set_env_var "$VIVARIA_DIR/.env.server" VIVARIA_LOCAL_TASK_MAX_MEMORY_GB 8

cat > "$VIVARIA_COMPOSE_ENV" <<EOF
VIVARIA_DOCKER_GID=$DOCKER_SOCKET_GID
VIVARIA_MIDDLEMAN_TYPE=$MIDDLEMAN_TYPE
EOF

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    cat > "$PROJECT_DIR/.env" <<'EOF'
# Optional task-specific environment variables for DeltaMLBench task environments.
# Replace placeholders with real values when a task needs them.
EOF
fi

set_env_var "$PROJECT_DIR/.env" AI_RD_RUST_CODECONTESTS_INFERENCE_OPENAI_API_KEY smoke-test-placeholder

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    uv venv --python 3.11 "$VENV_DIR"
fi

uv pip install --python "$VENV_DIR/bin/python" -e "$VIVARIA_DIR/cli"

set -a
source "$VIVARIA_DIR/.env.server"
set +a

"$VENV_DIR/bin/viv" config set apiUrl http://localhost:4001
"$VENV_DIR/bin/viv" config set uiUrl http://localhost:4000
"$VENV_DIR/bin/viv" config set evalsToken "$ACCESS_TOKEN---$ID_TOKEN"
"$VENV_DIR/bin/viv" config set vmHostLogin None
"$VENV_DIR/bin/viv" config set vmHost None

cat <<EOF
Bootstrap complete.

Repo-local CLI:
  $VENV_DIR/bin/viv

Next steps:
  cd vivaria
  docker compose up --detach --wait

Smoke test without model keys:
  ./.venv-cli/bin/viv run ai_rd_rust_codecontests_inference/main --agent_path ./smoke-agent --task_family_path ./deltamlbench/ai_rd_rust_codecontests_inference --env_file_path ./.env --max_tokens 10000 --max_actions 50 --max_total_seconds 600 --yes --name smoke_rust

Real model-backed runs:
  Add OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY to vivaria/.env.server
  Set VIVARIA_TASK_INSTALL_PLAYWRIGHT=true only if you need browser tooling in task images
  Raise or remove VIVARIA_LOCAL_TASK_MAX_CPU / VIVARIA_LOCAL_TASK_MAX_MEMORY_GB for full-fidelity local runs
  Re-run ./scripts/bootstrap_local.sh
  Restart Vivaria with: (cd vivaria && docker compose up --detach --wait)
EOF
