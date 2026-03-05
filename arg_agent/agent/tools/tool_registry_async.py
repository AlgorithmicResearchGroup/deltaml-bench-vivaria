import asyncio
import time
from typing import Dict, Any, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from rich.panel import Panel
from rich.text import Text
from agent.utils.general import logger, console
from agent.utils.worker_utils import log_with_panel
from rich.table import Table
from rich import box

# Import base tool classes
from agent.tools.base_tool import AsyncTool, Tool

# Import async versions of tools (we'll create these)
from agent.tools.bash.bash_tool_async import run_bash_async, bash_tool_definitions
from agent.tools.code.code_tool_async import (
    write_code_async,
    insert_code_async,
    replace_code_async,
    delete_code_async,
    code_tool_definitions,
)
from agent.tools.python.python_tool_async import run_python_async, python_tool_definitions
from agent.tools.scratchpad.scratchpad_tool_async import (
    use_scratchpad_async,
    scratchpad_tool_definitions,
)
from agent.tools.return_fn.return_fn_tool_async import return_fn_async, return_fn_tool_definitions
from agent.tools.cloud_storage.cloud_storage_tool_async import CloudStorageTool
from agent.tools.thought.thought_tool_async import thought_async, thought_tool_definitions
# from agent.tools.ask_user.ask_user_tool_async import ask_user_async, ask_user_tool_definitions
# GPU monitor and experiment tracker are now automatic utilities

# # Fallback to sync versions for tools that don't have async implementations yet
# from agent.tools.bash.bash_tool import run_bash
# from agent.tools.code.code_tool import write_code, insert_code, replace_code, delete_code
# from agent.tools.python.python_tool import run_python
# from agent.tools.scratchpad.scratchpad_tool import use_scratchpad
# from agent.tools.return_fn.return_fn_tool import return_fn, return_fn_tool_definitions


def collect_all_tools(*lists):
    """Collect all tool definitions"""
    merged_list = []
    for lst in lists:
        merged_list.extend(lst)
    return merged_list


# GPU monitor and experiment tracker are now automatic utilities, not tools

# Cloud storage tool definition
cloud_storage_tool_definitions = [{
    "name": "cloud_storage",
    "description": "Download/upload files and directories from/to cloud storage (GCS, S3)",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["download", "upload", "list", "delete", "exists", "metadata"],
                "description": "Action to perform"
            },
            "source_url": {
                "type": "string",
                "description": "Cloud storage URL for download/list/delete/exists/metadata actions (e.g., gs://bucket/path or s3://bucket/path)"
            },
            "source": {
                "type": "string",
                "description": "Local source path for upload action"
            },
            "destination": {
                "type": "string",
                "description": "Destination path (local for download, cloud URL for upload)"
            },
            "destination_url": {
                "type": "string",
                "description": "Cloud storage URL for upload action"
            },
            "url": {
                "type": "string",
                "description": "Cloud storage URL for list/delete/exists/metadata actions"
            },
            "recursive": {
                "type": "boolean",
                "description": "Whether to perform action recursively for directories",
                "default": False
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results for list action"
            }
        },
        "required": ["action"]
    }
}]

all_tools = collect_all_tools(
    bash_tool_definitions,
    code_tool_definitions,
    python_tool_definitions,
    return_fn_tool_definitions,
    cloud_storage_tool_definitions,
    thought_tool_definitions,
    # ask_user_tool_definitions,
    #scratchpad_tool_definitions,
)

worker_action_map = {
    "run_python": "filepath",
    "run_bash": "script",
    "write_code": ["path", "code"],
    "insert_code": ["path", "target", "new_code"],
    "replace_code": ["path", "old_code", "new_code"],
    "delete_code": ["path", "target"],
    "thought": "thought",
    # "ask_user": ["question", "context"],
    #"scratchpad": ["path", "note", "action"],
    "return_fn": ["score_path", "submission_path", "score"],
    "cloud_storage": ["action"],
}


class AsyncTool:
    def __init__(self, task: Dict[str, Any], worker_context: Optional[Any] = None):
        self.task = task
        self.worker_context = worker_context
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.cloud_storage_tool = None

    def print_human_readable(self, data: Any, action: str):
        """Rich-formatted tool execution logging"""
        # Create a visual representation of tool execution
        tool_table = Table(box=box.SIMPLE_HEAD)
        tool_table.add_column("🔧 Tool", style="bold magenta")
        tool_table.add_column("Parameters", style="white")
        
        if isinstance(data, dict):
            for key, value in data.items():
                # Truncate long values for readability
                display_value = str(value)
                if len(display_value) > 100:
                    display_value = display_value[:97] + "..."
                tool_table.add_row(key, display_value)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                display_item = str(item)
                if len(display_item) > 100:
                    display_item = display_item[:97] + "..."
                tool_table.add_row(f"param_{i}", display_item)
        else:
            display_data = str(data)
            if len(display_data) > 100:
                display_data = display_data[:97] + "..."
            tool_table.add_row("value", display_data)
        
        # Show tool execution in a panel
        panel = Panel(
            tool_table,
            title=f"🔧 {action.upper()}",
            style="magenta",
            border_style="magenta"
        )
        console.print(panel)

    async def run_async(self) -> Dict[str, Any]:
        """Async tool execution with performance monitoring"""
        start_time = time.time()
        
        # Async function mapping
        async_function_mapping = {
            "run_python": run_python_async,
            "run_bash": run_bash_async,
            "write_code": write_code_async,
            "insert_code": insert_code_async,
            "replace_code": replace_code_async,
            "delete_code": delete_code_async,
            "thought": thought_async,
            # "ask_user": ask_user_async,
            "return_fn": lambda args: return_fn_async(args, self.worker_context),
            "cloud_storage": self._run_cloud_storage,
        }

        if self.task["type"] == "function":
            function_name = self.task["function"]["name"]
            
            # Show tool execution start
            self.print_human_readable(
                self.task["function"]["parameters"], function_name
            )
            
            # Try async function first
            if function_name in async_function_mapping:
                try:
                    result = await async_function_mapping[function_name](
                        self.task["function"]["parameters"]
                    )
                    
                    # Show completion time with visual indicator
                    execution_time = time.time() - start_time
                    
                    completion_text = Text()
                    completion_text.append("✅ COMPLETED ", style="bold green")
                    completion_text.append(f"{function_name}", style="green")
                    completion_text.append(f" in {execution_time:.2f}s", style="dim")
                    console.print(completion_text)
                    
                    # Show result summary if available
                    if isinstance(result, dict):
                        if result.get('subtask_result'):
                            log_with_panel(
                                f"📤 {function_name.upper()} Result", 
                                str(result.get('subtask_result'))[:300] + ("..." if len(str(result.get('subtask_result'))) > 300 else ""),
                                "green"
                            )
                    
                    return result
                except Exception as e:
                    error_text = Text()
                    error_text.append("❌ FAILED ", style="bold red")
                    error_text.append(f"{function_name}: {str(e)[:100]}", style="red")
                    console.print(error_text)
                    
                    logger.warning(f"Tool {function_name} failed: {e}", 
                                 extra={'custom_tags': {'phase': 'agent', 'tool': function_name}})
                    
                    return {"subtask_result": f"Tool failed: {str(e)}", "attempted": "yes", "error": str(e)}
                    
            else:
                error_text = Text()
                error_text.append("❌ UNKNOWN TOOL ", style="bold red")
                error_text.append(f"{function_name}", style="red")
                console.print(error_text)
                
                logger.error(f"Unknown function: {function_name}", extra={'custom_tags': {'phase': 'agent'}})
                return {"subtask_result": "Invalid task", "attempted": "no"}
        else:
            error_text = Text()
            error_text.append("❌ INVALID TASK TYPE ", style="bold red")
            error_text.append(f"{self.task.get('type', 'unknown')}", style="red")
            console.print(error_text)
            
            logger.error(f"Invalid task type: {self.task.get('type', 'unknown')}", extra={'custom_tags': {'phase': 'agent'}})
            return {"subtask_result": "Invalid task", "attempted": "no"}

    # GPU monitor and experiment tracker are now automatic utilities, not tools

    async def _run_cloud_storage(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run cloud storage tool"""
        try:
            # Initialize cloud storage tool if not already done
            if not self.cloud_storage_tool:
                config_path = "config/async_config.yaml"
                self.cloud_storage_tool = CloudStorageTool(config_path)
            
            # Extract parameters and call the appropriate method
            action = params.get('action')
            if not action:
                return {"subtask_result": "No action specified for cloud_storage tool", "attempted": "no"}
            
            # Remove action from params as it's not needed by the tool methods
            tool_params = {k: v for k, v in params.items() if k != 'action'}
            
            # Call the cloud storage tool
            result = await self.cloud_storage_tool.run(action, tool_params, self.worker_context)
            
            return {"subtask_result": result, "attempted": "yes"}
        except Exception as e:
            return {"subtask_result": f"Cloud storage tool failed: {str(e)}", "attempted": "yes", "error": str(e)}

    def __del__(self):
        """Cleanup thread pool on deletion"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
        if hasattr(self, 'cloud_storage_tool') and self.cloud_storage_tool:
            asyncio.create_task(self.cloud_storage_tool.cleanup())


class AsyncToolManager:
    """Manager for concurrent tool execution"""
    
    def __init__(self, max_concurrent_tools: int = 3):
        self.max_concurrent_tools = max_concurrent_tools
        self.semaphore = asyncio.Semaphore(max_concurrent_tools)
        self.active_tools: Dict[str, AsyncTool] = {}
    
    async def execute_tool(self, tool_id: str, task: Dict[str, Any], worker_context: Optional[Any] = None) -> Dict[str, Any]:
        """Execute a single tool with concurrency control"""
        async with self.semaphore:
            tool = AsyncTool(task, worker_context)
            self.active_tools[tool_id] = tool
            
            try:
                result = await tool.run_async()
                return result
            finally:
                del self.active_tools[tool_id]
    
    async def execute_tools_parallel(self, tasks: List[Dict[str, Any]], worker_context: Optional[Any] = None) -> List[Dict[str, Any]]:
        """Execute multiple tools in parallel"""
        if not tasks:
            return []
        
        # Show parallel execution start
        parallel_text = Text()
        parallel_text.append("🔀 PARALLEL EXECUTION ", style="bold blue")
        parallel_text.append(f"({len(tasks)} tools)", style="blue")
        console.print(parallel_text)
        
        # Create tasks for parallel execution
        async_tasks = []
        for i, task in enumerate(tasks):
            tool_id = f"tool_{i}_{time.time()}"
            async_tasks.append(
                asyncio.create_task(
                    self.execute_tool(tool_id, task, worker_context),
                    name=f"tool_execution_{tool_id}"
                )
            )
        
        # Wait for all tasks to complete
        try:
            results = await asyncio.gather(*async_tasks, return_exceptions=True)
            
            # Process results and handle exceptions
            processed_results = []
            success_count = 0
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    error_text = Text()
                    error_text.append(f"❌ Tool {i} failed: ", style="red")
                    error_text.append(str(result)[:50], style="dim red")
                    console.print(error_text)
                    
                    processed_results.append({
                        "subtask_result": f"Tool failed: {str(result)}",
                        "attempted": "yes",
                        "error": str(result)
                    })
                else:
                    success_count += 1
                    processed_results.append(result)
            
            # Show parallel execution summary
            summary_text = Text()
            summary_text.append("📊 PARALLEL SUMMARY: ", style="bold blue")
            summary_text.append(f"{success_count}/{len(tasks)} succeeded", style="green" if success_count == len(tasks) else "yellow")
            console.print(summary_text)
            
            return processed_results
            
        except Exception as e:
            error_panel = Panel(
                f"Parallel execution failed: {str(e)}",
                title="❌ Parallel Execution Error",
                style="red"
            )
            console.print(error_panel)
            logger.error(f"Error in parallel tool execution: {e}")
            raise
    
    async def close(self):
        """Close all active tools"""
        for tool in self.active_tools.values():
            if hasattr(tool, 'executor'):
                tool.executor.shutdown(wait=False)
        self.active_tools.clear()


# Backwards compatibility
class Tool(AsyncTool):
    """Backwards compatible sync tool wrapper"""
    
    def run(self) -> Dict[str, Any]:
        """Synchronous run method for backwards compatibility"""
        try:
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, we need to run in a new thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.run_async())
                    return future.result()
            else:
                # If no loop is running, we can run directly
                return loop.run_until_complete(self.run_async())
        except RuntimeError:
            # No event loop exists, create a new one
            return asyncio.run(self.run_async()) 