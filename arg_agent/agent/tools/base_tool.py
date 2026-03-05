"""Base tool classes for async tool execution."""

import asyncio
import time
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich import box

from agent.utils.general import logger, console


class AsyncTool:
    """Base class for async tools."""
    
    def __init__(self, name: str = None, description: str = None, examples: list = None, 
                 task: Dict[str, Any] = None, worker_context: Optional[Any] = None):
        self.name = name
        self.description = description 
        self.examples = examples or []
        self.task = task
        self.worker_context = worker_context
        self.executor = ThreadPoolExecutor(max_workers=4)

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

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the tool with given input data. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement execute method")

    async def run_async(self) -> Dict[str, Any]:
        """Async tool execution with performance monitoring"""
        start_time = time.time()
        
        if not self.task:
            return {"subtask_result": "No task provided", "attempted": "no"}

        if self.task.get("type") == "function":
            function_name = self.task["function"]["name"]
            
            # Show tool execution start
            self.print_human_readable(
                self.task["function"]["parameters"], function_name
            )
            
            try:
                result = await self.execute(self.task["function"]["parameters"])
                
                # Show completion time with visual indicator
                execution_time = time.time() - start_time
                
                completion_text = Text()
                completion_text.append("✅ COMPLETED ", style="bold green")
                completion_text.append(f"{function_name}", style="green")
                completion_text.append(f" in {execution_time:.2f}s", style="dim")
                console.print(completion_text)
                
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
            error_text.append("❌ INVALID TASK TYPE ", style="bold red")
            error_text.append(f"{self.task.get('type', 'unknown')}", style="red")
            console.print(error_text)
            
            logger.error(f"Invalid task type: {self.task.get('type', 'unknown')}", extra={'custom_tags': {'phase': 'agent'}})
            return {"subtask_result": "Invalid task", "attempted": "no"}

    def __del__(self):
        """Cleanup thread pool on deletion"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)


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