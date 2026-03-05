"""
Simplified prompts for the agent - focusing on clarity and directness like the old_agent.
"""

from typing import Dict, Any, Optional


def get_submit_solution_spec() -> Dict[str, Any]:
    """
    Deprecated - not used in Vivaria environment.
    """
    return {
        "name": "vivaria_action",
        "description": "Execute Vivaria action (deprecated - not used)",
        "input_schema": {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "A step-by-step plan outlining the approach or the fix. This should explain the logic behind the code.",
                },
                "code": {
                    "type": "string",
                    "description": "The complete Python code to be executed. This must be a single, self-contained script with all necessary imports.",
                },
            },
            "required": ["plan", "code"],
        },
    }

def get_worker_system_prompt(run_number):
    """Simple, direct system prompt like old_agent."""
    return f"""You are a capable Machine Learning agent. Complete the given task efficiently.

KEY POINTS:
- You are ALREADY in your working directory
- ALL files are in your CURRENT directory - use 'ls' to see them
- Use RELATIVE paths only (e.g., 'python score.py', not '/path/to/score.py')
- Write and run code to solve problems
- PyTorch, pandas, numpy are pre-installed. Use run_bash for others.
- 🚨 PyTorch Models: Use torch.load(path, weights_only=False) to avoid unpickling errors
- Complete the task, then use return_fn with your score

🎯 PERFORMANCE GOAL:
- Treat existing solutions as baselines to beat, not copy
- Aim to significantly outperform any baseline you find

TOOLS: run_python, run_bash, write_code, scratchpad, return_fn

Remember:
- Execute plans immediately
- Try different approaches if stuck
- Save your work before using return_fn"""


def get_worker_prompt(
    user_query,
    plan,
    memories,
    working_dir,
    elapsed_time,
    previous_subtask_attempt,
    previous_subtask_output,
    previous_subtask_errors,
    success_metric=None,
    success_threshold=None,
):
    """Simple, direct worker prompt like old_agent."""
    elapsed_minutes = elapsed_time.total_seconds() / 60
    remaining_minutes = 24 * 60 - elapsed_minutes
    
    success_criteria = ""
    if success_metric and success_threshold is not None:
        success_criteria = f"\nTarget: {success_metric} >= {success_threshold:.4f}"
    
    return f"""Goal: {user_query}{success_criteria}

Working directory: {working_dir}
Time: {elapsed_minutes:.0f} min used, {remaining_minutes:.0f} min left

Recent actions:
{memories}

Previous output:
{previous_subtask_output}

Previous errors:
{previous_subtask_errors}

Instructions:
- START with 'ls' to see available files
- Complete the task efficiently
- Use return_fn when done with your score"""


def get_debug_prompt(task_desc: str, buggy_node_dict: Dict[str, Any], journal_summary: str = "") -> str:
    """Simple debug prompt."""
    error_text = buggy_node_dict.get('exec_error', buggy_node_dict.get('exec_stderr', 'No error'))
    code = buggy_node_dict.get('code', '# No code')
    
    return f"""DEBUG this failed code.

TASK: {task_desc}

FAILED CODE:
```python
{code}
```

ERROR:
{error_text}

Fix the error and save corrected code as solution.py in Vivaria environment."""


def get_draft_prompt(
    task_desc: str, journal_summary: str, data_overview: Optional[str] = None, approach_hint: Optional[str] = None
) -> str:
    """Simple draft prompt."""
    prompt = f"""Write Python code to solve this task.

TASK: {task_desc}
"""
    
    if data_overview:
        prompt += f"\nDATA INFO:\n{data_overview}\n"
    
    if approach_hint:
        prompt += f"\nHINT: {approach_hint}\n"
    
    prompt += "\nSave your solution as solution.py in the Vivaria environment."
    
    return prompt


def get_improve_prompt(
    task_desc: str,
    parent_node_dict: Dict[str, Any], 
    journal_summary: str,
    data_overview: Optional[str] = None,
) -> str:
    """Simple improve prompt."""
    prev_code = parent_node_dict.get('code', '# No code')
    prev_metric = parent_node_dict.get('metric_value', 'N/A')
    
    return f"""IMPROVE this solution.

TASK: {task_desc}

CURRENT CODE:
```python
{prev_code}
```

CURRENT SCORE: {prev_metric}

Make it significantly better. Try different approaches or algorithms that might work better. Save improved code as solution.py in Vivaria environment."""


def get_review_prompt(
    task_desc: str, code: str, stdout: str, stderr: str, error: str
) -> str:
    """Simple review prompt."""
    # Truncate long outputs
    max_lines = 50
    stdout_lines = stdout.split('\n')
    if len(stdout_lines) > max_lines:
        stdout = '\n'.join(stdout_lines[:max_lines]) + f"\n... ({len(stdout_lines) - max_lines} more lines)"
    
    stderr = stderr[:2000] if stderr else ""
    
    return f"""Review this code execution.

TASK: {task_desc}

CODE:
```python
{code[:2000]}
```

OUTPUT:
{stdout}

ERRORS:
{stderr}
{error}

Use submit_code_review to report if it's buggy, the metric value, and a summary."""


def get_review_function_spec(metric_name: str, metric_description: str) -> Dict[str, Any]:
    """Review function spec - unchanged as it's just metadata."""
    return {
        "name": "submit_code_review",
        "description": "Submit review of code execution",
        "input_schema": {
            "type": "object",
            "properties": {
                "is_buggy": {
                    "type": "boolean",
                    "description": "True if failed, False if successful",
                },
                "metric_value": {
                    "type": ["number", "null"],
                    "description": f"{metric_name} value, or null if failed",
                },
                "summary": {
                    "type": "string",
                    "description": "Brief summary of execution",
                },
            },
            "required": ["is_buggy", "metric_value", "summary"],
        },
    }


def get_solution_function_spec() -> Dict[str, Any]:
    """Solution submission spec - unchanged."""
    return {
        "name": "submit_solution",
        "description": "Submit your solution",
        "input_schema": {
            "type": "object", 
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Brief plan description",
                },
                "code": {
                    "type": "string", 
                    "description": "Complete Python code",
                },
            },
            "required": ["plan", "code"],
        },
    }


# No verbose common instructions - just be direct
def _common_code_generation_instructions() -> str:
    return ""