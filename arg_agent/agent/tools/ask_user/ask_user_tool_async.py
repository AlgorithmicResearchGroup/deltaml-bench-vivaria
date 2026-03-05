import asyncio
import sys
from typing import Dict, Any, Optional
from agent.utils.general import logger, console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt

ask_user_tool_definitions = [
    {
        "name": "ask_user",
        "description": "Ask the user a question when you need clarification or are stuck",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user (be specific and concise)",
                },
                "context": {
                    "type": "string",
                    "description": "Brief context about why you're asking (optional)",
                },
            },
            "required": ["question"],
        },
    },
]


async def ask_user_async(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Async function to ask the user a question and wait for their response.
    This pauses agent execution until the user provides input.
    """
    if isinstance(arguments, dict):
        question = arguments.get("question", "")
        context = arguments.get("context", "")
    else:
        question = str(arguments)
        context = ""
    
    # Display the question prominently
    question_panel = Panel(
        question,
        title="🤔 Agent Question",
        title_align="left",
        border_style="yellow",
        padding=(1, 2),
    )
    
    # Add context if provided
    if context:
        context_text = Text()
        context_text.append("Context: ", style="dim")
        context_text.append(context, style="dim italic")
        console.print(context_text)
    
    console.print(question_panel)
    
    # Log the question
    logger.info(f"Agent asking user: {question}", extra={'custom_tags': {'phase': 'interaction'}})
    
    # Get user input using Rich's prompt
    # Run the synchronous input in a thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    
    try:
        # Use Rich's Prompt for better formatting
        user_response = await loop.run_in_executor(
            None, 
            lambda: Prompt.ask("[bold cyan]Your response[/bold cyan]")
        )
        
        # Display confirmation of received input
        confirm_text = Text()
        confirm_text.append("✓ ", style="green")
        confirm_text.append("Received: ", style="dim green")
        confirm_text.append(user_response, style="green")
        console.print(confirm_text)
        console.print()  # Add spacing
        
        # Log the response
        logger.info(f"User response: {user_response}", extra={'custom_tags': {'phase': 'interaction'}})
        
        return {
            "tool": "ask_user",
            "status": "success",
            "attempt": "Asked user for input",
            "subtask_result": user_response,
            "stdout": f"User responded: {user_response}",
            "stderr": "",
        }
        
    except Exception as e:
        error_msg = f"Failed to get user input: {str(e)}"
        logger.error(error_msg)
        
        return {
            "tool": "ask_user",
            "status": "failure",
            "attempt": "Failed to ask user",
            "subtask_result": error_msg,
            "stdout": "",
            "stderr": error_msg,
        }