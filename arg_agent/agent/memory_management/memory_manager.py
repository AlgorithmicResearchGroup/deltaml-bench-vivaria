"""
Memory manager for saving and retrieving agent attempts.
"""

import json
import logging
from typing import Optional, Dict, Any
from agent.memory_management.memory_async import AsyncAgentMemory
from agent.core.solution_tree import SolutionNode
from rich.console import Console
from rich.text import Text

logger = logging.getLogger(__name__)
console = Console()


class MemoryManager:
    """Manages memory persistence for agent attempts and tool executions"""
    
    def __init__(self, memory: Optional[AsyncAgentMemory], run_id: str, user_id: int):
        self.memory = memory
        self.run_id = run_id
        self.user_id = user_id
    
    async def save_node_attempt(self, node: SolutionNode) -> None:
        """Save node attempt to simplified memory"""
        logger.info(f"save_node_attempt called for node {node.id[:8]}")
        logger.info(f"  has_executed: {node.has_executed}, memory exists: {self.memory is not None}")
        
        if not node.has_executed or not self.memory:
            logger.warning(f"Skipping memory save - has_executed: {node.has_executed}, memory: {self.memory}")
            return
        
        try:
            # Create simple description of what was tried
            action_description = f"Generated and executed {node.stage} code"
            what_was_tried = f"Plan: {node.plan[:200]}... Code approach: {node.code[:200] if node.code else 'No code'}..."
            result_status = "success" if not node.is_buggy else "failure"
            
            await self.memory.save_simple_attempt(
                run_id=self.run_id,
                user_id=self.user_id,
                action=f"code_execution_{node.stage}",
                what_was_tried=what_was_tried,
                result_status=result_status,
                output=node.exec_stdout or "",
                error=node.exec_stderr or node.exec_error or ""
            )
            
            # Show memory save confirmation
            memory_text = Text()
            memory_text.append("💾 SAVED TO MEMORY: ", style="dim blue")
            memory_text.append(f"Node {node.id[:8]} ({result_status})", style="blue")
            console.print(memory_text)
            
        except Exception as e:
            logger.warning(f"Failed to save node to memory: {e}")
    
    async def save_tool_execution(
        self, 
        tool_name: str, 
        tool_params: Dict[str, Any], 
        tool_result: Dict[str, Any]
    ) -> None:
        """Save tool execution to database immediately"""
        if not self.memory:
            return
            
        try:
            await self.memory.save_simple_attempt(
                run_id=self.run_id,
                user_id=self.user_id,
                action=tool_name,
                what_was_tried=json.dumps(tool_params)[:500],  # Truncate long params
                result_status="success" if tool_result.get("status") == "success" else "failure",
                output=str(tool_result.get("stdout", ""))[:1000] + str(tool_result.get("subtask_result", ""))[:1000],
                error=str(tool_result.get("stderr", ""))[:1000]
            )
            logger.info(f"Saved tool execution to database: {tool_name}")
            
            # Visual confirmation
            save_text = Text()
            save_text.append("💾 ", style="blue")
            save_text.append(f"Saved {tool_name} to database", style="dim blue")
            console.print(save_text)
        except Exception as e:
            logger.error(f"Failed to save tool execution to database: {e}")
            error_text = Text()
            error_text.append("❌ ", style="red")
            error_text.append(f"Failed to save {tool_name}: {str(e)}", style="dim red")
            console.print(error_text)
    
    async def get_current_run_context(self, limit: int = 15) -> str:
        """Get current run memory context"""
        if not self.memory:
            return ""
        
        try:
            # Get current run context only (most important!)
            current_context = await self.memory.get_current_run_memory(self.run_id, limit=limit)
            return f"\n🧠 WHAT YOU'VE TRIED IN THIS RUN:\n{current_context}\n"
        except Exception as e:
            logger.warning(f"Failed to get memory context: {e}")
            return ""
    
    async def get_error_specific_context(
        self, 
        error_type: str, 
        error_text: str,
        current_error: Optional[str] = None
    ) -> str:
        """Get memory context specific to the error type - CURRENT RUN ONLY"""
        if not self.memory:
            return ""
        
        try:
            # Get current run context with error focus
            if current_error:
                error_context = await self.memory.get_simple_context(
                    self.run_id, 
                    current_error=current_error
                )
                return error_context
            
            # Otherwise get normal run context
            current_run_context = await self.memory.get_current_run_memory(self.run_id, limit=15)
            
            # Look for similar errors in the current run
            if error_type.lower() in current_run_context.lower():
                return f"""
🚨 ERROR PATTERN DETECTED IN THIS RUN:
{current_run_context}

💡 CRITICAL: You've encountered {error_type} before in this run!
Review the above attempts and try a COMPLETELY DIFFERENT approach.
"""
            
            return current_run_context
            
        except Exception as e:
            logger.warning(f"Failed to get error-specific memory context: {e}")
            return ""