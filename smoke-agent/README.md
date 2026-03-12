# Smoke Agent

Minimal Vivaria agent for verifying that DeltaMLBench tasks upload and start correctly.

It does not use any model provider keys. The agent logs a startup message, waits for 180 seconds so the
run stays visible as `running` in Vivaria, and then submits a fixed string.

Use it to smoke-test a fresh install on the locally supported CPU-safe task family:

```bash
./run_tasks.sh --agent ./smoke-agent start ai_rd_rust_codecontests_inference
```
