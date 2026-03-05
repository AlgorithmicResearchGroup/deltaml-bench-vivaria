import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Literal

# Consider if dataclasses_json is already a dependency or if it needs to be added.
# If not, standard dataclasses are fine, and persistence can be handled separately if needed.

@dataclass
class SolutionNode:
    """
    A single node in the solution tree, representing one attempt or iteration.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)

    stage: Literal["draft", "debug", "improve", "initial_plan", "implement"] = "implement" # Stage of generation
    
    # Inputs to the LLM for this node
    generation_prompt: str = "" # The full prompt used to generate plan_and_code

    # Outputs from the LLM for this node
    plan: str = "" # LLM-generated plan for this step
    code: str = "" # LLM-generated code for this step

    # Execution results
    exec_stdout: Optional[str] = None
    exec_stderr: Optional[str] = None
    exec_error: Optional[str] = None # Formatted exception if one occurred
    exec_time_seconds: Optional[float] = None
    
    # Post-execution analysis by LLM
    review_prompt: str = "" # Prompt used to get the review
    analysis: Optional[str] = None # LLM's textual analysis of the execution
    metric_name: Optional[str] = None 
    metric_value: Optional[float] = None 
    is_buggy: Optional[bool] = None # Determined by LLM review or execution errors

    # Timestamps
    created_at: float = field(default_factory=time.time)
    executed_at: Optional[float] = None
    reviewed_at: Optional[float] = None

    # Misc
    working_directory: Optional[str] = None # The working directory for this node's execution

    # NEW: Debug exhaustion tracking
    debug_exhausted: bool = False  # True if this node has exceeded debug attempts
    metadata: Dict[str, Any] = field(default_factory=dict)  # For additional tracking

    def __post_init__(self):
        if self.parent_id and not isinstance(self.parent_id, str):
            # Ensure parent_id is a string if provided
            raise ValueError("parent_id must be a string (UUID of parent node)")

    @property
    def is_successful_execution(self) -> bool:
        """Did the code run without critical errors?"""
        return self.exec_error is None and self.is_buggy is False

    @property
    def has_executed(self) -> bool:
        return self.executed_at is not None

    @property
    def has_been_reviewed(self) -> bool:
        return self.reviewed_at is not None


@dataclass
class SolutionJournal:
    """
    Manages a collection of SolutionNodes, representing the history of attempts.
    """
    run_id: str
    nodes: Dict[str, SolutionNode] = field(default_factory=dict)
    root_node_ids: List[str] = field(default_factory=list) # Nodes with no parent

    def add_node(self, node: SolutionNode):
        if node.id in self.nodes:
            raise ValueError(f"Node with ID {node.id} already exists in the journal.")
        self.nodes[node.id] = node
        if node.parent_id:
            if node.parent_id not in self.nodes:
                # This could happen if nodes are added out of order, though ideally not.
                print(f"Warning: Parent node {node.parent_id} not found when adding child {node.id}")
            else:
                parent = self.nodes[node.parent_id]
                if node.id not in parent.children_ids:
                    parent.children_ids.append(node.id)
        else:
            if node.id not in self.root_node_ids:
                self.root_node_ids.append(node.id)
                
    def get_node(self, node_id: str) -> Optional[SolutionNode]:
        return self.nodes.get(node_id)

    def get_parent(self, node: SolutionNode) -> Optional[SolutionNode]:
        if node.parent_id:
            return self.nodes.get(node.parent_id)
        return None

    def get_children(self, node: SolutionNode) -> List[SolutionNode]:
        return [self.nodes[child_id] for child_id in node.children_ids if child_id in self.nodes]

    @property
    def all_nodes_chronological(self) -> List[SolutionNode]:
        return sorted(list(self.nodes.values()), key=lambda n: n.created_at)
        
    @property
    def draft_nodes(self) -> List[SolutionNode]:
        return [n for n in self.nodes.values() if n.stage == "draft" and not n.parent_id]

    @property
    def buggy_nodes(self) -> List[SolutionNode]:
        return [n for n in self.nodes.values() if n.is_buggy is True and n.has_executed]

    @property
    def good_nodes(self) -> List[SolutionNode]:
        """Nodes that have executed and are not marked as buggy."""
        return [n for n in self.nodes.values() if n.has_executed and n.is_buggy is False]

    def get_best_node(self, metric_name: str, lower_is_better: bool = False) -> Optional[SolutionNode]:
        """
        Return the best solution found so far (node with the best metric).
        Filters out nodes without the specified metric or not successfully executed.
        """
        valid_nodes = [
            n for n in self.good_nodes 
            if n.metric_name == metric_name and n.metric_value is not None
        ]
        if not valid_nodes:
            return None
        
        return sorted(valid_nodes, key=lambda n: n.metric_value, reverse=not lower_is_better)[0]

    def get_leaf_nodes(self) -> List[SolutionNode]:
        return [n for n in self.nodes.values() if not n.children_ids]

    def get_debug_depth(self, node: SolutionNode) -> int:
        depth = 0
        current = node
        while current and current.stage == "debug" and current.parent_id:
            depth += 1
            parent = self.get_parent(current)
            if not parent: # Should not happen in a consistent tree
                break
            current = parent
        return depth

    def generate_summary_for_llm(self, max_entries=5, include_code=False, only_buggy_ancestors_of: Optional[str] = None, node_id_to_highlight: Optional[str] = None, truncate_lengths: Optional[Dict[str, int]] = None) -> str:
        """
        Generate a summary of the journal for the LLM context.
        Prioritizes recent, successful, and impactful (good metric) nodes.
        If 'only_buggy_ancestors_of' is provided, it will only summarize the buggy ancestors of that specific node.
        If 'node_id_to_highlight' is provided, it will mark that node in the summary.
        If 'truncate_lengths' is provided, it overrides default truncation lengths.
        """
        summary_parts = []
        nodes_for_summary = []

        if only_buggy_ancestors_of:
            # Trace back buggy ancestors for the reflection step
            current_node_id = only_buggy_ancestors_of
            ancestor_chain = []
            while current_node_id:
                node = self.get_node(current_node_id)
                if not node:
                    break
                ancestor_chain.append(node)
                current_node_id = node.parent_id
            
            # Filter for buggy ones and reverse to get chronological order (oldest first)
            buggy_ancestors = [n for n in reversed(ancestor_chain) if n.is_buggy and n.has_executed]
            nodes_for_summary = buggy_ancestors[-max_entries:] # Get the most recent 'max_entries' buggy ancestors
            if not nodes_for_summary:
                 return "No buggy ancestors found for the specified node to summarize for reflection."

        else:
            # Original logic for general summary
            nodes_to_consider = sorted(
                self.good_nodes, 
                key=lambda n: (n.metric_value is not None, n.metric_value if n.metric_value is not None else -float('inf'), n.created_at), 
                reverse=True
            )
            
            if len(nodes_to_consider) < max_entries:
                buggy_leafs = sorted(
                    [n for n in self.buggy_nodes if not n.children_ids], # consider recent buggy leaves
                    key=lambda n: n.created_at,
                    reverse=True
                )
                nodes_to_consider.extend(buggy_leafs)

            # Ensure unique nodes and limit count
            processed_ids = set()
            final_nodes_for_summary_temp = []
            for n in nodes_to_consider:
                if n.id not in processed_ids:
                    final_nodes_for_summary_temp.append(n)
                    processed_ids.add(n.id)
                if len(final_nodes_for_summary_temp) >= max_entries:
                    break
            
            # Sort the final list by creation time for chronological context
            nodes_for_summary = sorted(final_nodes_for_summary_temp, key=lambda n: n.created_at)

        if not nodes_for_summary:
            return "No significant attempts recorded yet."

        # Default truncation lengths - increased significantly to prevent context loss
        default_truncate = {
            'plan': 1500,      # Increased from 200
            'code': 800,       # Increased from 100
            'analysis': 1200,  # Increased from 150
            'error': 3000      # Increased from 200 - needs to be large for full stack traces
        }
        
        # Use provided truncation lengths or defaults
        truncate = truncate_lengths or default_truncate
        
        for n in nodes_for_summary:
            highlight_marker = ""
            if node_id_to_highlight and n.id == node_id_to_highlight:
                highlight_marker = "*** THIS IS THE FAILING NODE WE ARE REFLECTING ON ***\n"
            
            part = f"{highlight_marker}Attempt (ID: {n.id[-6:]}, Stage: {n.stage}):\n"
            
            # Truncate plan with increased limit
            if n.plan:
                plan_limit = truncate.get('plan', 800)
                part += f"  Plan: {n.plan[:plan_limit] + '...' if len(n.plan) > plan_limit else n.plan}\n"
            
            if include_code and n.code:
                code_limit = truncate.get('code', 400)
                part += f"  Code Snippet: {n.code[:code_limit]}...\n"
            
            if n.has_executed:
                status_msg = 'Buggy' if n.is_buggy else 'OK'
                if n.metric_name and n.metric_value is not None:
                    status_msg += f" (Metric {n.metric_name}: {n.metric_value:.3f})"
                part += f"  Execution Status: {status_msg}\n"
                
                if n.analysis: # Show analysis if available
                    analysis_limit = truncate.get('analysis', 600)
                    part += f"  Analysis: {n.analysis[:analysis_limit] + '...' if len(n.analysis) > analysis_limit else n.analysis}\n"
                
                if n.is_buggy and n.exec_error: # Show error only if buggy
                    error_limit = truncate.get('error', 800)
                    part += f"  Error: {n.exec_error[:error_limit] + '...' if len(n.exec_error) > error_limit else n.exec_error}\n"
            else:
                part += "  Status: Not yet executed.\n"
            summary_parts.append(part)
            
        title_prefix = "Summary of Buggy Ancestors" if only_buggy_ancestors_of else "Recent Attempts Summary"
        if node_id_to_highlight and not only_buggy_ancestors_of:
             title_prefix += " (Highlighting Specific Node)"
        return f"{title_prefix}:\n" + "\n-------------------------------\n".join(summary_parts)