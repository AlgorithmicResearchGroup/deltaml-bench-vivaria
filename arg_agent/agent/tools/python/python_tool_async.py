import sys
import os
import asyncio
from typing import Dict, Optional
from agent.utils.general import remove_ascii, logger
import tempfile
import hashlib
import time
# from agent.core.tool_executor import ToolExecutor  # Temporarily disabled to fix circular import
 
python_tool_definitions = [
    {
        "name": "run_python",
        "description": "Run python code on the server. You must print the output",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "The path to a python file.",
                },
            },
            "required": ["filepath"],
        },
    },
]

class AsyncPythonRunnerActor:
    def __init__(self):
        pass

    async def execute_python_code_async(self, script_input: str, timeout: Optional[float] = None, working_directory: Optional[str] = None) -> Dict[str, str]:
        """Async method to execute Python code from file path OR direct code content"""
        
        # Validate Python code doesn't contain tool calling syntax
        if any(invalid_syntax in script_input for invalid_syntax in [
            '<function_calls>', '<invoke', '<parameter', 'function_calls>'
        ]):
            logger.error("❌ Invalid Python code: Contains tool calling syntax")
            return {
                "tool": "run_python",
                "status": "failure",
                "attempt": script_input[:100] + "..." if len(script_input) > 100 else script_input,
                "stdout": "",
                "stderr": "ERROR: Python code contains invalid tool calling syntax like <function_calls>. Python code must be pure Python only. Use print() statements and call return_fn separately after execution."
            }
        
        result = {
            "tool": "run_python",
            "status": "failure", 
            "attempt": script_input[:100] + "..." if len(script_input) > 100 else script_input,
            "stdout": "",
            "stderr": "",
        }
        
        temp_file_path = None
        
        try:
            # Determine if input is a file path or direct code
            if '\n' in script_input or len(script_input) > 255:
                # It's likely direct Python code content
                logger.info("🐍 Executing Python code content")
                
                # Check for tool calls and process them
                if "TOOL." in script_input:
                    logger.info("🔧 Tool calls in code detected but ToolExecutor disabled due to circular import")
                    # TODO: Fix circular import with ToolExecutor
                    # tool_executor = ToolExecutor()
                    # modified_code, tool_results = await tool_executor.execute_mixed_code(script_input, None)
                    # script_input = modified_code
                    # logger.info(f"✅ Processed {len(tool_results)} tool calls")
                
                # Create a temporary file in the working directory if specified
                script_hash = hashlib.md5(script_input.encode()).hexdigest()[:8]
                timestamp = int(time.time() * 1000000)  # microsecond precision
                if working_directory:
                    temp_file_path = os.path.join(working_directory, f"temp_script_{script_hash}_{timestamp}.py")
                else:
                    temp_file_path = f"/tmp/temp_script_{script_hash}_{timestamp}.py"
                
                # Write code to temporary file
                with open(temp_file_path, 'w') as f:
                    f.write(script_input)
                
                filepath_to_execute = temp_file_path
                
            elif os.path.isfile(script_input):
                # It's a file path
                logger.info(f"🐍 Executing Python file: {script_input}")
                filepath_to_execute = script_input
                
            else:
                # It's neither a valid file nor looks like code
                raise FileNotFoundError(f"Invalid input: Not a file path or Python code: {script_input[:100]}...")

            # Execute the Python file
            logger.info(f"🚀 Starting Python execution: {filepath_to_execute}")
            if working_directory:
                logger.info(f"📁 Working directory: {working_directory}")
            
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-u', filepath_to_execute,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024*1024,  # 1MB buffer limit
                cwd=working_directory  # 🔧 ADD THIS LINE - Execute in specified working directory
            )

            stdout_lines = []
            stderr_lines = []

            async def read_stdout():
                """Async function to read stdout"""
                try:
                    async for line in process.stdout:
                        line_str = line.decode('utf-8', errors='replace')
                        print(line_str, end='')  # Print to console
                        stdout_lines.append(line_str)
                        logger.info(f"📤 Python stdout: {line_str.strip()}")
                except Exception as e:
                    logger.error(f"Error reading stdout: {e}")

            async def read_stderr():
                """Async function to read stderr"""
                try:
                    async for line in process.stderr:
                        line_str = line.decode('utf-8', errors='replace')
                        print(line_str, end='', file=sys.stderr)  # Print errors to stderr
                        stderr_lines.append(line_str)
                        logger.warning(f"📤 Python stderr: {line_str.strip()}")
                except Exception as e:
                    logger.error(f"Error reading stderr: {e}")

            # Start reading stdout and stderr concurrently
            read_tasks = [
                asyncio.create_task(read_stdout()),
                asyncio.create_task(read_stderr())
            ]

            try:
                # Wait for the process to finish with timeout
                # Use configured timeout or fallback to default
                try:
                    from agent.config import get_python_timeout
                    default_timeout = get_python_timeout()
                except ImportError:
                    default_timeout = 18000  # Fallback
                timeout_duration = timeout or default_timeout
                logger.info(f"⏱️ Waiting for Python execution (timeout: {timeout_duration}s)")
                
                returncode = await asyncio.wait_for(process.wait(), timeout=timeout_duration)
                
                # Wait for all read tasks to complete
                await asyncio.gather(*read_tasks, return_exceptions=True)

                result["stdout"] = ''.join(stdout_lines)
                result["stderr"] = ''.join(stderr_lines)

                if returncode == 0:
                    result["status"] = "success"
                    logger.info(f"✅ Python execution completed successfully")
                else:
                    result["status"] = "failure"
                    logger.error(f"❌ Python execution failed with return code: {returncode}")

            except asyncio.TimeoutError:
                # Kill the process if it times out
                logger.error(f"⏰ Python execution timed out after {timeout_duration}s")
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                
                # Cancel read tasks
                for task in read_tasks:
                    task.cancel()
                
                result["stderr"] = f"Python execution timed out after {timeout_duration} seconds"

        except Exception as e:
            logger.error(f"❌ Python execution error: {e}")
            result["stderr"] = str(e)

        # finally:
        #     # Clean up temporary file
        #     if temp_file_path and os.path.exists(temp_file_path):
        #         try:
        #             os.remove(temp_file_path)
        #             logger.info(f"🗑️ Cleaned up temporary file: {temp_file_path}")
        #         except Exception as e:
        #             logger.warning(f"Could not remove temp file {temp_file_path}: {e}")

        return result

    async def run_code_async(self, filepath: str, timeout: Optional[float] = None) -> Dict[str, str]:
        """Wrapper method to execute Python code asynchronously with an optional timeout."""
        return await self.execute_python_code_async(filepath, timeout)


async def run_python_async(arguments) -> Dict[str, str]:
    """
    Async version of run_python function.
    This function is used to run python code asynchronously.
    Use this function to run the code you need to complete the task.
    """
    if isinstance(arguments, dict):
        script = arguments["filepath"]
    else:
        script = arguments

    python_runner_actor = AsyncPythonRunnerActor()
    result = await python_runner_actor.run_code_async(script)
    
    # Remove ASCII characters asynchronously
    loop = asyncio.get_event_loop()
    result["stdout"] = await loop.run_in_executor(
        None, remove_ascii, result["stdout"]
    )
    
    return result 