# ARG Agent Vivaria Submission Flow Documentation

## Overview
This document explains how the ARG Agent submits solutions to Vivaria for DeltaMLBench tasks.

## Submission Architecture

### Components
1. **main.py** - Entry point that sets up Vivaria hooks and manages the agent
2. **vivaria_tool_patch.py** - Patches agent tools to use Vivaria execution
3. **return_fn_tool_async.py** - Original return function (gets patched)
4. **vivaria_return_fn_async** - Vivaria-compatible return function

## Normal Submission Flow

### Step 1: Initialization
```python
# main.py sets up Vivaria environment
os.environ["VIVARIA_MODE"] = "true"
vivaria_tool_patch.set_vivaria_hooks(hooks)
vivaria_tool_patch.apply_vivaria_tool_patches()
```

### Step 2: Agent Execution
1. Agent solves the task using various tools
2. Agent creates solution file (e.g., `solution.py`, `submission.txt`)
3. Agent calls `return_fn` tool to submit

### Step 3: Tool Patching
- `return_fn_async` is replaced with `vivaria_return_fn_async` via monkey patching
- This happens in `vivaria_tool_patch.apply_vivaria_tool_patches()`

### Step 4: Submission via return_fn
When agent calls return_fn:
1. `vivaria_return_fn_async` is executed (not the original)
2. Function reads the submission file
3. Sets `vivaria_submission_attempted = True` (global flag)
4. Sets `worker_context.submission_intercepted = True` (if available)
5. Logs submission details
6. Calls `await hooks.submit(submission_content)`
7. **Process terminates with exit(0)** - no code after submit executes

### Step 5: Fallback Mechanism
If submission doesn't occur (process continues):
1. main.py checks `submission_occurred = agent.submission_intercepted or vivaria_submission_attempted`
2. If false, triggers fallback submission
3. Searches for solution files (`solution.py`, `submission.txt`, etc.)
4. Submits best available solution via `hooks.submit()`

## Alternative Submission Path (TASK_COMPLETE Signal)

The agent also supports legacy submission via stdout signals:

1. Agent outputs: `TASK_COMPLETE: submission_path=<file> score=<score>`
2. `_handle_submission_output()` in main.py detects this
3. Reads the file and calls `hooks.submit()`
4. Sets `submission_intercepted = True`

## Common Issues and Solutions

### Issue 1: "Agent completed but didn't submit"
**Cause**: The return_fn tool wasn't properly patched or hooks weren't available
**Solution**: Ensure patching happens before tool imports

### Issue 2: Submission happens but agent doesn't know
**Cause**: `hooks.submit()` exits immediately, preventing flag updates
**Solution**: Set flags BEFORE calling submit, use global tracking

### Issue 3: Double submission
**Cause**: Both TASK_COMPLETE signal and return_fn submission
**Solution**: Check `submission_intercepted` flag before any submission

## Key Points to Remember

1. **`hooks.submit()` terminates the process** - plan accordingly
2. **Patching must happen early** - before tools are imported elsewhere
3. **Use multiple detection methods** - flags, signals, global vars
4. **Always have a fallback** - search for solution files if primary fails

## Testing Submission

To test if submission is working:
```bash
# Check logs for these messages:
"📤 Submitting to Vivaria via return_fn tool..."  # Good - proper path
"⚠️ Agent completed but didn't submit..."         # Bad - fallback triggered
"✅ Successfully submitted to Vivaria!"            # Good - submission successful
```

## Environment Variables

- `VIVARIA_MODE=true` - Enables Vivaria mode
- `RUN_ID` - Set by Vivaria, indicates running in platform

## Files Modified for Submission

1. `/arg_agent/vivaria_tool_patch.py` - Added logging and flag setting
2. `/arg_agent/main.py` - Added global flag check
3. This documentation file

## Future Improvements

1. Consider using a more robust IPC mechanism for submission tracking
2. Add telemetry to track which submission path is used
3. Implement retry logic for failed submissions
