# DeltaMLBench

Public monorepo for running DeltaMLBench tasks on Vivaria, with multiple agent implementations and grading utilities.

## What is in this repo

- `deltamlbench/`: Task families (`ai_rd_*`, `pwc_*`)
- `vivaria/`: Vivaria server/UI/CLI workspace
- `arg_agent/`: ARG agent wrapper for Vivaria
- `modular-public/`, `modular-public-claude/`, `modular-public-gpt4o/`: modular agent variants
- `smoke-agent/`: minimal no-LLM agent for first-run validation
- `run_tasks.sh`: primary task run/monitor utility
- `grade_run.py`: standalone run-log grading utility
- `scripts/grade_agent_logs.py`: API-based grading utility

## Prerequisites

- Python 3.11
- `uv`
- Docker + Docker Compose
- Optional model API key for real agent runs (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`)

## Quick start

1. Clone the repo.

```bash
git clone <repo-url>
cd deltaml-bench-public
```

2. Bootstrap the local CLI and env files.

```bash
./scripts/bootstrap_local.sh
```

This creates:
- `vivaria/.env.server` and `vivaria/.env.db`
- `vivaria/.env` with the correct local Docker socket GID and middleman mode
- local smoke-test defaults in `vivaria/.env.server`:
  - `VIVARIA_TASK_INSTALL_PLAYWRIGHT=false`
  - `VIVARIA_RUN_INITIAL_SCORING=false` when no model key is configured
  - `VIVARIA_LOCAL_TASK_MAX_CPU=4`
  - `VIVARIA_LOCAL_TASK_MAX_MEMORY_GB=8`
- `.env` with a placeholder `AI_RD_RUST_CODECONTESTS_INFERENCE_OPENAI_API_KEY` for smoke tests
- `.venv-cli/` with a repo-local `viv` CLI

3. Add a model provider key to `vivaria/.env.server` if you want to run a real agent.

Example:

```bash
echo 'OPENAI_API_KEY=...' >> vivaria/.env.server
```

If you skip this, `./scripts/bootstrap_local.sh` puts Vivaria in `noop` middleman mode so smoke tests work without external model credentials.
Re-run `./scripts/bootstrap_local.sh` after adding keys so Vivaria switches back to `builtin` middleman mode and re-enables initial scoring.

4. Start Vivaria services.

```bash
cd vivaria
docker compose up --detach --wait
cd ..
```

Use `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --detach --wait` only on GPU hosts.

5. Verify run manager setup.

```bash
./run_tasks.sh help
./run_tasks.sh tasks
```

## Local smoke-tested path

The path below is what has been verified end to end on a first-time local install:

- CPU-only local smoke tests: `ai_rd_rust_codecontests_inference`
- GPU-required families such as `ai_rd_fix_embedding`, `ai_rd_triton_cumsum`, and most `pwc_*` tasks will not start on a CPU-only local Docker host
- `./scripts/bootstrap_local.sh` intentionally caps local task CPU/memory requests so laptop-class Docker setups can start the smoke task family

## Smoke test

Verify the install without any model keys:

```bash
./.venv-cli/bin/viv run ai_rd_rust_codecontests_inference/main --agent_path ./smoke-agent --task_family_path ./deltamlbench/ai_rd_rust_codecontests_inference --env_file_path ./.env --max_tokens 10000 --max_actions 50 --max_total_seconds 600 --yes --name smoke_rust_main_a
./.venv-cli/bin/viv run ai_rd_rust_codecontests_inference/main --agent_path ./smoke-agent --task_family_path ./deltamlbench/ai_rd_rust_codecontests_inference --env_file_path ./.env --max_tokens 10000 --max_actions 50 --max_total_seconds 600 --yes --name smoke_rust_main_b
./.venv-cli/bin/viv run ai_rd_rust_codecontests_inference/hidden_score --agent_path ./smoke-agent --task_family_path ./deltamlbench/ai_rd_rust_codecontests_inference --env_file_path ./.env --max_tokens 10000 --max_actions 50 --max_total_seconds 600 --yes --name smoke_rust_hidden
```

These runs stay active for about 3 minutes so they appear as `running` in Vivaria before submitting.

After you add a real provider key, rerun `./scripts/bootstrap_local.sh` so Vivaria switches back from `noop` to `builtin` middleman mode.
For full-fidelity local runs, raise or remove `VIVARIA_LOCAL_TASK_MAX_CPU` and `VIVARIA_LOCAL_TASK_MAX_MEMORY_GB` in `vivaria/.env.server`.

## Run tasks

Run with the default model-backed agent (`modular-public`):

```bash
./run_tasks.sh start ai_rd_rust_codecontests_inference
```

Run with a custom agent path:

```bash
./run_tasks.sh --agent ./arg_agent start ai_rd_rust_codecontests_inference
```

Useful commands:

```bash
./run_tasks.sh status
./run_tasks.sh status ai_rd_rust_codecontests_inference
./run_tasks.sh logs ai_rd_rust_codecontests_inference
./run_tasks.sh monitor ai_rd_rust_codecontests_inference
./run_tasks.sh kill ai_rd_rust_codecontests_inference
```

## Grade runs

Standalone DB-based grader:

```bash
python grade_run.py --run-id <RUN_ID> --openai-key "$OPENAI_API_KEY"
```

API-based grader:

```bash
python scripts/grade_agent_logs.py --run-id <RUN_ID>
```

Required env vars for API-based grader:

```bash
export VIVARIA_ACCESS_TOKEN="..."
export VIVARIA_ID_TOKEN="..."
export OPENAI_API_KEY="..."
```

## Common troubleshooting

- `viv` CLI problems: run `./scripts/bootstrap_local.sh` and use the repo-local CLI at `.venv-cli/bin/viv`.
- Docker daemon unavailable: start Docker Desktop / OrbStack first, then retry `docker compose up --detach --wait`.
- Vivaria server exits with Docker permission errors: rerun `./scripts/bootstrap_local.sh` so `vivaria/.env` picks up the correct `VIVARIA_DOCKER_GID`.
- Missing `.env`: rerun `./scripts/bootstrap_local.sh` or let `run_tasks.sh` create a default task env file with smoke-test placeholders.
- Docker connectivity issues: check `docker ps` and Vivaria container health.
- Local smoke run never starts on CPU-only Docker: use `ai_rd_rust_codecontests_inference`; most other DeltaMLBench families in this repo require GPUs.
- Task image build hangs on browser download: local bootstrap now disables Playwright in shared task images by default; set `VIVARIA_TASK_INSTALL_PLAYWRIGHT=true` only if a task actually needs browser tooling.
- Task start fails because requested CPU or memory is too large: local bootstrap now clamps task resources; raise `VIVARIA_LOCAL_TASK_MAX_CPU` / `VIVARIA_LOCAL_TASK_MAX_MEMORY_GB` if your machine can support more.
- No agent runs can start with a real model-backed task: add the required task-specific secrets to `.env` or `vivaria/.env.server`, then restart Vivaria.
- Grading auth failures: verify Vivaria tokens and API keys are exported.

## Notes

- Legacy/internal migration docs were moved under `docs/archive/`.
- This repo keeps all agent variants; choose one with `--agent` when launching tasks.
