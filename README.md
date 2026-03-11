# DeltaMLBench

Public monorepo for running DeltaMLBench tasks on Vivaria, with multiple agent implementations and grading utilities.

## What is in this repo

- `deltamlbench/`: Task families (`ai_rd_*`, `pwc_*`)
- `vivaria/`: Vivaria server/UI/CLI workspace
- `arg_agent/`: ARG agent wrapper for Vivaria
- `modular-public/`, `modular-public-claude/`, `modular-public-gpt4o/`: modular agent variants
- `run_tasks.sh`: primary task run/monitor utility
- `grade_run.py`: standalone run-log grading utility
- `scripts/grade_agent_logs.py`: API-based grading utility

## Prerequisites

- Python 3.11+
- Docker + Docker Compose
- `viv` CLI available in your shell
- API keys for models you use (`OPENAI_API_KEY`, optional `ANTHROPIC_API_KEY`)

## Quick start

1. Clone the repo.

```bash
git clone <repo-url>
cd deltaml-bench-public
```

2. Prepare environment files.

- Create repo `.env` used by `run_tasks.sh`
- Configure Vivaria env files in `vivaria/.env.server` and `vivaria/.env.db`

3. Start Vivaria services.

```bash
cd vivaria
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
cd ..
```

4. Verify run manager setup.

```bash
./run_tasks.sh help
./run_tasks.sh tasks
```

## Run tasks

Run with default agent (`modular-public`):

```bash
./run_tasks.sh start ai_rd_triton_cumsum
```

Run with a custom agent path:

```bash
./run_tasks.sh --agent ./arg_agent start ai_rd_fix_embedding
```

Useful commands:

```bash
./run_tasks.sh status
./run_tasks.sh status ai_rd_triton_cumsum
./run_tasks.sh logs ai_rd_triton_cumsum
./run_tasks.sh monitor ai_rd_triton_cumsum
./run_tasks.sh kill ai_rd_triton_cumsum
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

- `viv: command not found`: install/configure Vivaria CLI in current environment.
- Missing `.env`: create project `.env` at repo root (used by `run_tasks.sh`).
- Docker connectivity issues: check `docker ps` and Vivaria container health.
- Grading auth failures: verify Vivaria tokens and API keys are exported.

## Notes

- Legacy/internal migration docs were moved under `docs/archive/`.
- This repo keeps all agent variants; choose one with `--agent` when launching tasks.
