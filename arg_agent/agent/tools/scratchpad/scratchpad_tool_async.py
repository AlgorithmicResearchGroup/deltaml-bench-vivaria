import os
import asyncio
import aiofiles
from typing import Dict, Any
from agent.utils.general import logger

scratchpad_tool_definitions = [
    {
        "name": "scratchpad",
        "description": "Write and read important findings to and from a scratchpad file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the scratchpad file.",
                },
                "note": {
                    "type": "string",
                    "description": "The note to write to the scratchpad file. If action is 'read', pass an empty string.",
                },
                "action": {
                    "type": "string",
                    "description": "The action to perform. Either 'write' or 'read'.",
                },
            },
            "required": ["path", "note", "action"],
        },
    },
]

async def use_scratchpad_async(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Async version of use_scratchpad function.
    This function is used to manage notes in a scratchpad file asynchronously.
    """
    if isinstance(arguments, dict):
        path = arguments["path"]
        note = arguments["note"]
        action = arguments["action"]
    else:
        path = arguments[0]
        note = arguments[1]
        action = arguments[2]

    try:
        # Ensure the directory exists
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, os.makedirs, directory, True)

        if action == "write":
            # Write to scratchpad
            async with aiofiles.open(path, "w") as file:
                await file.write(note)
            
            logger.info(f"Scratchpad written: {path}", extra={'custom_tags': {'phase': 'agent'}})
            return {
                "tool": "scratchpad",
                "status": "success",
                "attempt": f"You wrote to the scratchpad at {path}",
                "stdout": f"Note written: {note}",
                "stderr": "",
            }

        elif action == "append":
            # Append to scratchpad
            async with aiofiles.open(path, "a") as file:
                await file.write(f"\n{note}")
            
            logger.info(f"Scratchpad appended: {path}", extra={'custom_tags': {'phase': 'agent'}})
            return {
                "tool": "scratchpad",
                "status": "success",
                "attempt": f"You appended to the scratchpad at {path}",
                "stdout": f"Note appended: {note}",
                "stderr": "",
            }

        elif action == "read":
            # Read from scratchpad
            try:
                async with aiofiles.open(path, "r") as file:
                    content = await file.read()
                
                logger.info(f"Scratchpad read: {path}", extra={'custom_tags': {'phase': 'agent'}})
                return {
                    "tool": "scratchpad",
                    "status": "success",
                    "attempt": f"You read from the scratchpad at {path}",
                    "stdout": f"Content: {content}",
                    "stderr": "",
                }
            except FileNotFoundError:
                return {
                    "tool": "scratchpad",
                    "status": "failure",
                    "attempt": f"You tried to read from the scratchpad at {path}",
                    "stdout": "",
                    "stderr": f"File not found: {path}",
                }

        elif action == "clear":
            # Clear scratchpad
            async with aiofiles.open(path, "w") as file:
                await file.write("")
            
            logger.info(f"Scratchpad cleared: {path}", extra={'custom_tags': {'phase': 'agent'}})
            return {
                "tool": "scratchpad",
                "status": "success",
                "attempt": f"You cleared the scratchpad at {path}",
                "stdout": "Scratchpad cleared",
                "stderr": "",
            }

        else:
            return {
                "tool": "scratchpad",
                "status": "failure",
                "attempt": f"You tried to perform action '{action}' on scratchpad",
                "stdout": "",
                "stderr": f"Invalid action: {action}. Supported actions: write, append, read, clear",
            }

    except Exception as e:
        logger.error(f"Error in scratchpad operation: {e}", extra={'custom_tags': {'phase': 'agent'}})
        return {
            "tool": "scratchpad",
            "status": "failure",
            "attempt": f"You tried to {action} the scratchpad at {path}",
            "stdout": "",
            "stderr": str(e),
        } 