# DeltaMLBench

DeltaMLBench is now an Inspect-native benchmark for the complete `pwc_*` task families in [`deltamlbench/`](/Users/arg/Desktop/PUBLIC/deltaml-bench-public/deltamlbench).

## Supported Scope

- Supported runtime: Inspect
- Supported benchmark families: 49 complete `pwc_*` families, exposed as 98 task variants (`main` and `hidden_score`)
- Archived from the Inspect runtime: `pwc_fb15k_237_dabr`, `pwc_food_101_mano_tiny`, `pwc_hme100k_ical`, `pwc_imagenet_10_dpac`, `pwc_istd_rasm`
- Not supported by the new runtime: `ai_rd_*`

Legacy Vivaria code is still present in the repo for reference, but the supported local workflow is the Inspect path below.

## Prerequisites

- Python 3.12
- `uv`
- Docker
- Optional provider key for real agent runs:
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`
  - `GOOGLE_API_KEY`

## Quick Start

1. Create the repo-local Inspect environment.

```bash
./scripts/bootstrap_inspect.sh
```

2. List the registered PWC tasks.

```bash
./run_benchmark.sh list
```

3. Run a no-model smoke test that validates task import, Docker sandboxing, setup, and scoring.

```bash
.inspect-venv/bin/inspect eval \
  deltamlbench_inspect/tasks/pwc.py@pwc_cnn_main \
  --solver deltamlbench_inspect/solvers.py@baseline_submit \
  --limit 1 \
  --no-sandbox-cleanup
```

4. Run a real agent-backed task.

```bash
export ANTHROPIC_API_KEY=...
./run_benchmark.sh run pwc_cnn_main anthropic/claude-sonnet-4-5
```

Use an alternate Inspect agent preset:

```bash
./run_benchmark.sh run \
  pwc_cnn_main \
  anthropic/claude-sonnet-4-5 \
  "$(pwd)/deltamlbench_inspect/agents.py@modular_public_bridge"
```

## Repo Layout

- [`deltamlbench/`](/Users/arg/Desktop/PUBLIC/deltaml-bench-public/deltamlbench): source task families and assets
- [`deltamlbench_inspect/`](/Users/arg/Desktop/PUBLIC/deltaml-bench-public/deltamlbench_inspect): Inspect-native runtime, scorers, task wrappers, sandbox image, and agent presets
- [`metr/`](/Users/arg/Desktop/PUBLIC/deltaml-bench-public/metr): compatibility shim for legacy task/scoring imports
- [`run_benchmark.sh`](/Users/arg/Desktop/PUBLIC/deltaml-bench-public/run_benchmark.sh): simple launcher for listing and running Inspect tasks
- [`scripts/bootstrap_inspect.sh`](/Users/arg/Desktop/PUBLIC/deltaml-bench-public/scripts/bootstrap_inspect.sh): first-run local setup

## Notes

- `main` task variants expose a score tool to the agent.
- `hidden_score` variants run the same scorer but do not expose intermediate score feedback.
- Most PWC tasks still require substantial compute and may require GPUs to be practical; the smoke solver is intended only to validate the runtime path.
- The new runtime keeps the existing `assets/score.py`, `anti_cheat_validation`, and task setup logic rather than rewriting each task by hand.

## Troubleshooting

- `inspect` not found: rerun `./scripts/bootstrap_inspect.sh`
- Docker build errors: verify `docker ps` works before launching a task
- Docker containers cannot resolve `pypi.org`, `github.com`, or the GCS artifact buckets: fix Docker Desktop / OrbStack container DNS first. On this machine the Inspect runtime reached task setup successfully, but container-side DNS resolution failed during `pip install` and artifact download.
- Provider auth failures: export the matching provider key in your shell before running `inspect eval`
- A task directory is missing from `./run_benchmark.sh list`: it is probably one of the five archived incomplete `pwc_*` imports
