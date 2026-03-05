import asyncio
from typing import Dict, Any, Optional
from agent.utils.general import logger, console
from rich.panel import Panel
from rich.text import Text

thought_tool_definitions = [
    {
        "name": "thought",
        "description": "Share your reasoning and thought process",
        "input_schema": {
            "type": "object",
            "properties": {
                "thought": {
                    "type": "string",
                    "description": "Your current thinking, reasoning, or reflection",
                },
            },
            "required": ["thought"],
        },
    },
]


async def thought_async(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Async version of thought function.
    Displays the agent's thought process to improve transparency.
    """
    if isinstance(arguments, dict):
        thought = arguments.get("thought", "")
    else:
        thought = str(arguments)
    
    # Display thought in a subtle, inline way
    thought_text = Text()
    thought_text.append("💭 ", style="cyan")
    thought_text.append(thought, style="dim cyan")
    console.print(thought_text)
    
    # Log the thought
    logger.info(f"Agent thought: {thought}", extra={'custom_tags': {'phase': 'thought'}})
    
    return {
        "tool": "thought",
        "status": "success",
        "attempt": "Shared thought process",
        "subtask_result": f"Thought recorded: {thought[:100]}...",
        "stdout": thought,
        "stderr": "",
    }