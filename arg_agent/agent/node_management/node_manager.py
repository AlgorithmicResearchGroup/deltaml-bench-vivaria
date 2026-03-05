"""
Node manager for creating and managing solution tree nodes.
"""

import uuid
import time
import logging
from typing import Optional, List
from rich.console import Console
from rich.panel import Panel
from agent.core.solution_tree import SolutionNode, SolutionJournal

logger = logging.getLogger(__name__)
console = Console()


class NodeManager:
    """Manages creation and manipulation of solution tree nodes"""
    
    def __init__(self, journal: SolutionJournal, reflection_manager=None):
        """
        Initialize node manager.
        
        Args:
            journal: Solution journal for storing nodes
            reflection_manager: Optional reflection manager for generating reflections
        """
        self.journal = journal
        self.reflection_manager = reflection_manager
    
    async def create_debug_child_node(self, parent_node: SolutionNode) -> Optional[SolutionNode]:
        """
        Create a debug child node for a buggy parent node.
        
        Args:
            parent_node: The buggy parent node
            
        Returns:
            Created debug child node or None if parent is not buggy
        """
        if not parent_node.is_buggy:
            return None
        
        debug_child = SolutionNode(
            id=str(uuid.uuid4()),
            stage="debug",
            parent_id=parent_node.id,
            created_at=time.time()
        )
        
        # Add child relationship
        if debug_child.id not in parent_node.children_ids:
            parent_node.children_ids.append(debug_child.id)
        
        self.journal.add_node(debug_child)
        
        console.print(Panel(
            f"🐛➡️🔧 Created debug child {debug_child.id[:8]} for buggy node {parent_node.id[:8]}",
            style="yellow"
        ))
        
        return debug_child
    
    async def create_fresh_approach_node(self) -> Optional[SolutionNode]:
        """
        Create a completely fresh approach when stuck in loops.
        
        Returns:
            Fresh root-level approach node
        """
        fresh_node = SolutionNode(
            id=str(uuid.uuid4()),
            stage="implement",
            parent_id=None,  # Root level approach
            created_at=time.time()
        )
        
        self.journal.add_node(fresh_node)
        
        console.print(Panel(
            f"🌟 Created fresh approach node {fresh_node.id[:8]} to break out of failure patterns",
            style="green bold"
        ))
        
        return fresh_node
    
    async def create_alternative_approach_node(
        self, 
        exhausted_node: SolutionNode, 
        reflection_plan: Optional[str] = None
    ) -> Optional[SolutionNode]:
        """
        Create an alternative approach node when debugging is exhausted.
        
        Args:
            exhausted_node: The node that has exhausted debug attempts
            reflection_plan: Optional reflection plan text
            
        Returns:
            Alternative approach node
        """
        # Find the root cause node (go up the tree to find non-debug ancestor)
        current = exhausted_node
        while current and current.stage == "debug" and current.parent_id:
            parent = self.journal.get_node(current.parent_id)
            if parent:
                current = parent
            else:
                break
        
        # Create alternative as sibling to the root cause
        alternative_node = SolutionNode(
            id=str(uuid.uuid4()),
            stage="implement",
            parent_id=current.parent_id,  # Same parent as root cause
            created_at=time.time()
        )
        
        # Add some metadata to indicate this is an alternative approach
        alternative_node.metadata = {
            "alternative_to": exhausted_node.id,
            "approach_number": self._get_next_approach_number(),
            "reason": "debug_exhausted",
            "reflection": reflection_plan if reflection_plan else "No reflection performed." 
        }
        
        self.journal.add_node(alternative_node)
        
        console.print(Panel(
            f"🔀 Created alternative approach {alternative_node.id[:8]} "
            f"(approach #{alternative_node.metadata['approach_number']})",
            style="cyan bold"
        ))
        
        return alternative_node
    
    async def create_threshold_improvement_node(
        self, 
        best_nodes: List[SolutionNode],
        current_best: float,
        target_threshold: float,
        success_metric: str,
        user_query: str
    ) -> Optional[SolutionNode]:
        """
        Create a specialized node to improve performance toward the threshold.
        
        Args:
            best_nodes: List of successful nodes
            current_best: Current best metric value
            target_threshold: Target threshold to achieve
            success_metric: Name of the success metric
            user_query: Original user query for context
            
        Returns:
            Threshold improvement node
        """
        # Find the best performing node
        best_node = max(best_nodes, key=lambda x: x.metric_value or 0)
        
        # Perform reflection on why we haven't met the threshold
        reflection = ""
        if self.reflection_manager:
            reflection = await self.reflection_manager.perform_threshold_reflection(
                best_node, current_best, target_threshold, user_query
            )
        
        # Create improvement node
        improvement_node = SolutionNode(
            id=str(uuid.uuid4()),
            stage="improve",
            parent_id=best_node.id,
            created_at=time.time()
        )
        
        # Add metadata about threshold targeting
        improvement_node.metadata = {
            "improvement_type": "threshold_targeting",
            "current_best": current_best,
            "target_threshold": target_threshold,
            "gap_percentage": ((target_threshold - current_best) / target_threshold) * 100,
            "reflection": reflection,
            "approach_hint": f"You MUST achieve at least {target_threshold:.4f} {success_metric}. "
                           f"Current best is {current_best:.4f}. "
                           f"Focus on the specific improvements suggested in the reflection."
        }
        
        # Add child relationship
        if improvement_node.id not in best_node.children_ids:
            best_node.children_ids.append(improvement_node.id)
        
        self.journal.add_node(improvement_node)
        
        console.print(Panel(
            f"🎯 Created threshold improvement node {improvement_node.id[:8]}\n"
            f"Parent: {best_node.id[:8]} (current: {current_best:.4f})\n"
            f"Target: {target_threshold:.4f} ({improvement_node.metadata['gap_percentage']:.1f}% gap)",
            style="cyan bold"
        ))
        
        return improvement_node
    
    def _get_next_approach_number(self) -> int:
        """
        Get the next approach number for alternative strategies.
        
        Returns:
            Next approach number
        """
        existing_approaches = [
            node.metadata.get("approach_number", 1) 
            for node in self.journal.nodes.values() 
            if node.metadata.get("approach_number")
        ]
        return max(existing_approaches, default=0) + 1
    
    def count_debug_children(self, parent_node: SolutionNode) -> int:
        """
        Count how many debug children a node has (recursively).
        
        Args:
            parent_node: Node to count debug children for
            
        Returns:
            Number of debug children
        """
        def count_recursive(node_id: str):
            node = self.journal.get_node(node_id)
            if not node:
                return 0
            
            debug_count = 0
            for child_id in node.children_ids:
                child = self.journal.get_node(child_id)
                if child and child.stage == "debug":
                    debug_count += 1
                    debug_count += count_recursive(child_id)
            return debug_count
        
        debug_count = count_recursive(parent_node.id)
        return debug_count