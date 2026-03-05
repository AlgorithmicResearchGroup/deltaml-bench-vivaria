"""
Reflection manager for analyzing failures and suggesting improvements.
"""

import logging
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from agent.core.solution_tree import SolutionNode
from agent.utils.general import log_with_panel

logger = logging.getLogger(__name__)
console = Console()


class ReflectionManager:
    """Manages reflection and analysis of failures to suggest improvements"""
    
    def __init__(self, llm_interface):
        """
        Initialize reflection manager.
        
        Args:
            llm_interface: LLM interface for generating reflections
        """
        self.llm = llm_interface
    
    async def perform_reflection(
        self, 
        failing_node: SolutionNode, 
        error_type: str, 
        error_count: int,
        user_query: str
    ) -> str:
        """
        Performs a reflection step when a repeated error pattern is detected.
        Asks the LLM to analyze the persistent failure and suggest diverse strategies.
        
        Args:
            failing_node: The node that failed
            error_type: Type of error encountered
            error_count: Number of times this error has occurred
            user_query: Original user query for context
            
        Returns:
            Reflection text with suggestions
        """
        console.print(Panel(
            f"🤔 Performing reflection on repeated error: '{error_type}' (occurred {error_count} times)",
            title="🔄 Reflection Step",
            style="magenta bold"
        ))

        try:
            # Use LLM interface for reflection
            reflection_text = await self.llm.perform_reflection(
                failing_node=failing_node,
                error_type=error_type,
                error_count=error_count,
                user_query=user_query
            )
            
            log_with_panel("🧘 Reflection Generated", reflection_text, "magenta")
            return reflection_text

        except Exception as e:
            logger.error(f"❌ Error during reflection: {e}", exc_info=True)
            log_with_panel("LLM Reflection Error (Exception)", f"Error: {e}", "red")
            return f"Reflection failed due to an exception: {e}"
    
    async def perform_threshold_reflection(
        self, 
        best_node: SolutionNode,
        current_best: float,
        target_threshold: float,
        user_query: str
    ) -> str:
        """
        Reflect on why the current best doesn't meet threshold and suggest improvements.
        
        Args:
            best_node: The best performing node so far
            current_best: Current best metric value
            target_threshold: Target threshold to achieve
            user_query: Original user query for context
            
        Returns:
            Reflection text with improvement suggestions
        """
        console.print(Panel(
            f"🤔 Analyzing gap between current best ({current_best:.4f}) and threshold ({target_threshold:.4f})",
            title="🎯 Threshold Reflection",
            style="magenta bold"
        ))
        
        try:
            if not self.llm:
                return "Reflection failed: LLM not initialized."
            
            # Use LLM interface for threshold reflection
            reflection_text = await self.llm.perform_threshold_reflection(
                best_node=best_node,
                current_best=current_best,
                target_threshold=target_threshold,
                user_query=user_query
            )
            
            log_with_panel("🎯 Threshold Improvement Strategy", reflection_text[:500] + "...", "magenta")
            return reflection_text
            
        except Exception as e:
            logger.error(f"❌ Error during threshold reflection: {e}", exc_info=True)
            return f"Reflection failed: {e}"