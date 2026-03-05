import asyncio
import logging
import sys
from typing import Dict, Optional
from agent.utils.general import remove_ascii, logger

# Import the tool definitions from the original module
bash_tool_definitions = [
    {
        "name": "run_bash",
        "description": "Run a bash script on the server. Doesn't support interactive commands. MUST use non-interactive flags: unzip -o, apt-get -y, pip install --yes, cp -f, rm -f, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "The bash script to run.",
                },
            },
            "required": ["script"],
        },
    },
]

class AsyncBashRunnerActor:
    def __init__(self, timeout: Optional[int] = None):
        # Use configured timeout or fallback to default
        if timeout is None:
            try:
                from agent.config import get_bash_timeout
                self.timeout = get_bash_timeout()
            except ImportError:
                self.timeout = 1000000  # Fallback
        else:
            self.timeout = timeout

    async def run_async(self, command: str) -> Dict[str, Optional[str]]:
        """Async method to execute a bash command and return the results."""
        logger.info(f"Executing command: {command}", extra={'custom_tags': {'phase': 'agent'}})

        result = {
            "tool": "run_bash",
            "status": "failure",
            "returncode": None,
            "attempt": command,
            "stdout": "",
            "stderr": "",
        }

        try:
            # Create subprocess asynchronously
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024*1024  # 1MB buffer limit
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
                except Exception as e:
                    logger.error(f"Error reading stdout: {e}")

            async def read_stderr():
                """Async function to read stderr"""
                try:
                    async for line in process.stderr:
                        line_str = line.decode('utf-8', errors='replace')
                        print(line_str, end='', file=sys.stderr)  # Print errors to stderr
                        stderr_lines.append(line_str)
                except Exception as e:
                    logger.error(f"Error reading stderr: {e}")

            # Start reading stdout and stderr concurrently
            read_tasks = [
                asyncio.create_task(read_stdout()),
                asyncio.create_task(read_stderr())
            ]

            try:
                # Wait for process to finish with timeout
                returncode = await asyncio.wait_for(process.wait(), timeout=self.timeout)
                
                # Wait for all read tasks to complete
                await asyncio.gather(*read_tasks, return_exceptions=True)
                
                result['returncode'] = returncode
                result["stdout"] = ''.join(stdout_lines)
                result["stderr"] = ''.join(stderr_lines)

                if returncode == 0:
                    result["status"] = "success"
                else:
                    result["status"] = "failure"
                    logging.error(f"Command failed with returncode: {returncode}")
                    logging.error(f"Command stderr:\n{result['stderr']}")

            except asyncio.TimeoutError:
                # Kill the process if it times out
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                
                # Cancel read tasks
                for task in read_tasks:
                    task.cancel()
                
                result["stderr"] = f"Command timed out after {self.timeout} seconds"
                logging.error(result["stderr"])

            return result

        except Exception as e:
            # Handle unexpected errors
            result["stderr"] = f"Unexpected error: {str(e)}"
            logging.exception(result["stderr"])
            return result


async def run_bash_async(arguments: dict) -> Dict[str, Optional[str]]:
    """
    Async version of run_bash function.
    This function is used to run a bash script on the server asynchronously.
    """
    if isinstance(arguments, dict):
        command = arguments["script"]
    else:
        command = arguments

    runner_actor = AsyncBashRunnerActor()
    result = await runner_actor.run_async(command)
    
    # Remove ASCII characters asynchronously
    loop = asyncio.get_event_loop()
    result["stdout"] = await loop.run_in_executor(
        None, remove_ascii, result["stdout"]
    )
    
    return result 