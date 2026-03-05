"""Utility functions for the AsyncWorker."""

from typing import Dict, Any, Optional
from rich.panel import Panel
from rich.syntax import Syntax

from agent.core.solution_tree import SolutionNode
from agent.utils.general import console


def convert_node_to_dict_for_prompt(node: Optional[SolutionNode]) -> Dict[str, Any]:
    """Convert a SolutionNode to a dictionary for use in prompts."""
    if not node:
        return {}
    return {
        "id": node.id,
        "plan": node.plan,
        "code": node.code,
        "exec_stdout": node.exec_stdout,
        "exec_stderr": node.exec_stderr,
        "exec_error": node.exec_error,
        "analysis": node.analysis,
        "metric_name": node.metric_name,
        "metric_value": node.metric_value,
        "is_buggy": node.is_buggy,
        "stage": node.stage,  # Added stage as it might be useful context
        # Add other fields if they become relevant for prompts
    }


def log_with_panel(title: str, content: str, style: str = "white"):
    """Log content with a visual panel."""
    panel = Panel(
        content,
        title=title,
        style=style,
        padding=(1, 1)
    )
    console.print(panel)


def log_code_snippet(code: str, title: str = "Code"):
    """Log code with syntax highlighting."""
    syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
    code_panel = Panel(
        syntax,
        title=title,
        style="dim",
        padding=(0, 1)
    )
    console.print(code_panel)