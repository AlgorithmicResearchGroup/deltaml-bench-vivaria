import random
import time
from typing import Optional, Tuple, Dict, Any
from agent.core.solution_tree import SolutionJournal, SolutionNode

class SearchPolicy:
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the search policy with configuration.
        Expected config keys:
        - num_drafts (int): Minimum number of draft solutions to aim for.
        - debug_prob (float): Probability (0.0-1.0) of choosing a debug action.
        - max_debug_depth (int): Maximum number of consecutive debug steps on a single branch.
        - min_debug_attempts (int): Minimum number of debug attempts per bug.
        - target_metric_name (str): Name of the metric to optimize (e.g., 'accuracy').
        - target_metric_lower_is_better (bool): True if a lower metric value is better.
        - search_strategy (str): Search strategy to use ('tree_search' or 'beam_search').
        """
        self.num_drafts = config.get("num_drafts", 2)
        self.debug_prob = config.get("debug_prob", 0.7)
        self.max_debug_depth = config.get("max_debug_depth", 5)
        self.min_debug_attempts = config.get("min_debug_attempts", 4)
        self.target_metric_name = config.get("target_metric_name", "accuracy") # Default or from worker
        self.target_metric_lower_is_better = config.get("target_metric_lower_is_better", False)
        self.search_strategy = config.get("search_strategy", "tree_search")


    def get_next_action(self, journal: SolutionJournal) -> Tuple[str, Optional[SolutionNode]]:
        """
        Selects the next action (draft, debug, improve) and a parent node if applicable.
        Returns:
            Tuple[str, Optional[SolutionNode]]: (action_type, parent_node)
            action_type can be "draft", "debug", "improve".
            parent_node is None for "draft", and a SolutionNode for "debug" or "improve".
        """
        # 1. Initial Drafting
        # If no nodes at all, or fewer draft nodes than configured, try to draft.
        # A "draft" here means a root-level attempt, not necessarily the "draft" stage of a node.
        # The first node(s) will be of stage "draft".
        if not journal.nodes or len(journal.draft_nodes) < self.num_drafts:
            print("[Search Policy] Action: draft (not enough initial drafts)")
            return "draft", None

        # Enhanced debugging logic
        # Prioritize debugging if we have recent failures
        recent_buggy_nodes = [
                n for n in journal.buggy_nodes 
                if not n.children_ids and journal.get_debug_depth(n) < self.max_debug_depth
            and (time.time() - n.created_at) < 600  # Focus on recent bugs (10 min)
        ]
        
        # Always debug if we have critical errors and few debug attempts
        critical_buggy_nodes = [
            n for n in recent_buggy_nodes
            if any(error_type in (n.exec_error or "") for error_type in 
                   ["FileNotFoundError", "ImportError", "ModuleNotFoundError", "NameError"])
            and journal.get_debug_depth(n) < self.min_debug_attempts
        ]
        
        if critical_buggy_nodes:
            # Always debug critical errors first
            selected_node = max(critical_buggy_nodes, key=lambda x: x.created_at)  # Most recent
            print(f"[Search Policy] Action: debug (critical error in node {selected_node.id[-6:]})")
            return "debug", selected_node
        
        # Force more attempts for file not found errors
        file_not_found_nodes = [
            n for n in recent_buggy_nodes
            if "FileNotFoundError" in (n.exec_error or "")
            and journal.get_debug_depth(n) < 4  # Force at least 4 attempts
        ]
        
        if file_not_found_nodes:
            selected_node = max(file_not_found_nodes, key=lambda x: x.created_at)
            print(f"[Search Policy] Action: debug (FileNotFoundError - forcing investigation)")
            return "debug", selected_node

        
        # Standard debug logic with higher probability
        if recent_buggy_nodes and (random.random() < self.debug_prob or len(journal.good_nodes) == 0):
            selected_node = random.choice(recent_buggy_nodes)
            print(f"[Search Policy] Action: debug (node {selected_node.id[-6:]})")
            return "debug", selected_node


        # 3. Improvement or New Draft
        # If there are good nodes, try to improve the best one.
        # Otherwise, or if improvement path seems stuck (e.g. too many children on best node), draft new.
        
        best_node = journal.get_best_node(
            metric_name=self.target_metric_name, 
            lower_is_better=self.target_metric_lower_is_better
        )

        if best_node:
            # Potentially add more sophisticated logic here:
            # - If best_node has many 'improve' children already without much gain, maybe draft.
            # - If best_node is very old, maybe draft.
            print(f"[Search Policy] Action: improve (parent node {best_node.id[-6:]})")
            return "improve", best_node
        else:
            # No good nodes to improve, or decision to draft anew.
            print("[Search Policy] Action: draft (no good nodes to improve, or choosing to draft)")
            return "draft", None