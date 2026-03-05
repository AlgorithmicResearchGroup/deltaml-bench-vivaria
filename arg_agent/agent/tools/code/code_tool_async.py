import os
import asyncio
import aiofiles
from typing import Dict, Any
from agent.utils.general import logger

# Import the tool definitions from the original module
code_tool_definitions = [
    {
        "name": "write_code",
        "description": "Write code to a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to write",
                },
                "code": {
                    "type": "string",
                    "description": "The code to write to the file.",
                },
            },
            "required": ["path", "code"],
        },
    },
    {
        "name": "insert_code",
        "description": "Insert code into a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to insert code into.",
                },
                "target": {
                    "type": "string",
                    "description": "The existing code snippet after which you want to insert the new code.",
                },
                "new_code": {
                    "type": "string",
                    "description": "The new code snippet you want to insert.",
                },
            },
            "required": ["target", "new_code"],
        },
    },
    {
        "name": "replace_code",
        "description": "Replace code in a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to insert code into.",
                },
                "old_code": {
                    "type": "string",
                    "description": "The existing code snippet you want to replace.",
                },
                "new_code": {
                    "type": "string",
                    "description": "The new code snippet you want to replace the old code with.",
                },
            },
            "required": ["old_code", "new_code"],
        },
    },
    {
        "name": "delete_code",
        "description": "Delete code from a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to insert code into.",
                },
                "target": {
                    "type": "string",
                    "description": "The code snippet you want to delete.",
                },
            },
            "required": ["target"],
        },
    },
]

class AsyncPythonEditorActor:
    def __init__(self, file_path: str):
        self.file_path = file_path

    async def read_code_async(self) -> str:
        """Async method to read code from file"""
        try:
            async with aiofiles.open(self.file_path, "r") as file:
                code = await file.read()
        except FileNotFoundError:
            print(f"File not found: {self.file_path}")
            print(f"Creating file: {self.file_path}")
            async with aiofiles.open(self.file_path, "w") as file:
                await file.write("")
                code = ""
        return code

    async def write_code_async(self, code: str) -> Dict[str, Any]:
        """Async method to write code to file"""
        try:
            # Ensure directory exists
            directory = os.path.dirname(self.file_path)
            if directory and not os.path.exists(directory):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, os.makedirs, directory, True)

            async with aiofiles.open(self.file_path, "w") as file:
                await file.write(code)
            
            logger.info(f"File saved: {self.file_path}", extra={'custom_tags': {'phase': 'agent'}})
            return {
                "tool": "write_code",
                "status": "success",
                "attempt": f"You wrote code to {self.file_path}",
                "stdout": f"{code}",
                "stderr": "",
            }

        except IOError as e:
            logger.info(f"Error saving file: {self.file_path}", extra={'custom_tags': {'phase': 'agent'}})
            logger.info(f"Error details: {str(e)}", extra={'custom_tags': {'phase': 'agent'}})
            return {
                "tool": "write_code",
                "status": "failure",
                "attempt": f"You tried to write code to {self.file_path} but it failed",
                "stdout": "",
                "stderr": str(e),
            }

    async def insert_code_async(self, target: str, new_code: str) -> Dict[str, Any]:
        """Async method to insert code into file"""
        try:
            code = await self.read_code_async()
            
            if target in code:
                # Find the position to insert after the target
                target_pos = code.find(target) + len(target)
                
                # Insert new code after the target
                updated_code = code[:target_pos] + "\n" + new_code + "\n" + code[target_pos:]
                
                await self.write_code_async(updated_code)
                
                logger.info(f"Code inserted in file: {self.file_path}", extra={'custom_tags': {'phase': 'agent'}})
                return {
                    "tool": "insert_code",
                    "status": "success",
                    "attempt": f"You inserted code in {self.file_path} after '{target}'",
                    "stdout": f"Inserted:\n{new_code}",
                    "stderr": "",
                }
            else:
                return {
                    "tool": "insert_code",
                    "status": "failure",
                    "attempt": f"You tried to insert code in {self.file_path} after '{target}' but the target was not found",
                    "stdout": "",
                    "stderr": f"Target '{target}' not found in file",
                }

        except Exception as e:
            logger.info(f"Error inserting code in file: {self.file_path}", extra={'custom_tags': {'phase': 'agent'}})
            return {
                "tool": "insert_code",
                "status": "failure",
                "attempt": f"You tried to insert code in {self.file_path} but it failed",
                "stdout": "",
                "stderr": str(e),
            }

    async def replace_code_async(self, old_code: str, new_code: str) -> Dict[str, Any]:
        """Async method to replace code in file"""
        try:
            code = await self.read_code_async()
            
            if old_code in code:
                updated_code = code.replace(old_code, new_code)
                await self.write_code_async(updated_code)
                
                logger.info(f"Code replaced in file: {self.file_path}", extra={'custom_tags': {'phase': 'agent'}})
                return {
                    "tool": "replace_code",
                    "status": "success",
                    "attempt": f"You replaced code in {self.file_path}",
                    "stdout": f"Replaced '{old_code}' with '{new_code}'",
                    "stderr": "",
                }
            else:
                return {
                    "tool": "replace_code",
                    "status": "failure",
                    "attempt": f"You tried to replace code in {self.file_path} but the old code was not found",
                    "stdout": "",
                    "stderr": f"Old code '{old_code}' not found in file",
                }

        except Exception as e:
            logger.info(f"Error replacing code in file: {self.file_path}", extra={'custom_tags': {'phase': 'agent'}})
            return {
                "tool": "replace_code",
                "status": "failure",
                "attempt": f"You tried to replace code in {self.file_path} but it failed",
                "stdout": "",
                "stderr": str(e),
            }

    async def delete_code_async(self, target: str) -> Dict[str, Any]:
        """Async method to delete code from file"""
        try:
            code = await self.read_code_async()
            
            if target in code:
                updated_code = code.replace(target, "")
                await self.write_code_async(updated_code)
                
                logger.info(f"Code deleted from file: {self.file_path}", extra={'custom_tags': {'phase': 'agent'}})
                return {
                    "tool": "delete_code",
                    "status": "success",
                    "attempt": f"You deleted code from {self.file_path}",
                    "stdout": f"Deleted: {target}",
                    "stderr": "",
                }
            else:
                return {
                    "tool": "delete_code",
                    "status": "failure",
                    "attempt": f"You tried to delete code from {self.file_path} but the target was not found",
                    "stdout": "",
                    "stderr": f"Target '{target}' not found in file",
                }

        except Exception as e:
            logger.info(f"Error deleting code from file: {self.file_path}", extra={'custom_tags': {'phase': 'agent'}})
            return {
                "tool": "delete_code",
                "status": "failure",
                "attempt": f"You tried to delete code from {self.file_path} but it failed",
                "stdout": "",
                "stderr": str(e),
            }


# Async tool functions
async def write_code_async(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Async version of write_code function"""
    if isinstance(arguments, dict):
        path = arguments["path"]
        code = arguments["code"]
    else:
        path = arguments[0]
        code = arguments[1]

    editor_actor = AsyncPythonEditorActor(path)
    result = await editor_actor.write_code_async(code)
    return result


async def insert_code_async(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Async version of insert_code function"""
    if isinstance(arguments, dict):
        path = arguments["path"]
        target = arguments["target"]
        new_code = arguments["new_code"]
    else:
        path = arguments[0]
        target = arguments[1]
        new_code = arguments[2]

    editor_actor = AsyncPythonEditorActor(path)
    result = await editor_actor.insert_code_async(target, new_code)
    return result


async def replace_code_async(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Async version of replace_code function"""
    if isinstance(arguments, dict):
        path = arguments["path"]
        old_code = arguments["old_code"]
        new_code = arguments["new_code"]
    else:
        path = arguments[0]
        old_code = arguments[1]
        new_code = arguments[2]

    editor_actor = AsyncPythonEditorActor(path)
    result = await editor_actor.replace_code_async(old_code, new_code)
    return result


async def delete_code_async(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Async version of delete_code function"""
    if isinstance(arguments, dict):
        path = arguments["path"]
        target = arguments["target"]
    else:
        path = arguments[0]
        target = arguments[1]

    editor_actor = AsyncPythonEditorActor(path)
    result = await editor_actor.delete_code_async(target)
    return result 