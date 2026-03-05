"""
Beam Search with Diversity implementation for the Coding Agent.
This module provides an alternative search strategy that maintains top-K candidates
with diversity constraints to avoid exploring similar approaches.
"""

import random
from typing import List, Tuple, Dict, Optional, Set
from collections import defaultdict
import hashlib

from agent.core.solution_tree import SolutionJournal, SolutionNode


class BeamSearchWithDiversity:
    """
    Implements Beam Search with Diversity for solution tree exploration.
    
    This search strategy:
    1. Maintains a beam of top-K candidates at each level
    2. Enforces diversity by filtering similar approaches
    3. Balances exploitation (high scores) with exploration (diversity)
    """
    
    def __init__(self, beam_width: int = 3, diversity_threshold: float = 0.7):
        """
        Initialize Beam Search with Diversity.
        
        Args:
            beam_width: Maximum number of candidates to maintain (K)
            diversity_threshold: Similarity threshold for diversity filtering (0-1)
        """
        self.beam_width = beam_width
        self.diversity_threshold = diversity_threshold
        self.approach_signatures: Dict[str, Set[str]] = defaultdict(set)
        
    def select_nodes_for_expansion(
        self, 
        journal: SolutionJournal,
        max_nodes: int = 3,
        prioritize_debugging: bool = True
    ) -> List[SolutionNode]:
        """
        Select nodes for expansion using beam search with diversity.
        
        Args:
            journal: The solution journal containing all nodes
            max_nodes: Maximum number of nodes to return
            prioritize_debugging: Whether to prioritize debugging over exploration
            
        Returns:
            List of nodes selected for expansion
        """
        leaf_nodes = journal.get_leaf_nodes()
        if not leaf_nodes:
            return []
            
        # Separate nodes by execution status
        unexecuted = [n for n in leaf_nodes if not n.has_executed]
        buggy = [n for n in leaf_nodes if n.has_executed and n.is_buggy and not getattr(n, 'debug_exhausted', False)]
        successful = [n for n in leaf_nodes if n.has_executed and not n.is_buggy]
        
        selected_nodes = []
        
        # Priority 1: Debug critical errors if prioritize_debugging is True
        if prioritize_debugging and buggy:
            critical_bugs = self._filter_critical_bugs(buggy)
            if critical_bugs:
                # Select most recent critical bug
                selected_nodes.append(max(critical_bugs, key=lambda x: x.created_at))
                max_nodes -= 1
                
        # Priority 2: Select from unexecuted nodes using beam search
        if unexecuted and max_nodes > 0:
            beam_candidates = self._beam_select_diverse(
                unexecuted, 
                min(self.beam_width, max_nodes),
                journal
            )
            selected_nodes.extend(beam_candidates)
            max_nodes -= len(beam_candidates)
            
        # Priority 3: Select from successful nodes for improvement
        if successful and max_nodes > 0:
            # Rank by score and recency
            ranked_successful = self._rank_nodes(successful)
            improvement_candidates = self._filter_diverse_candidates(
                ranked_successful[:max_nodes * 2],  # Consider more candidates
                max_nodes,
                journal
            )
            selected_nodes.extend(improvement_candidates)
            
        return selected_nodes[:max_nodes]
        
    def _beam_select_diverse(
        self, 
        candidates: List[SolutionNode], 
        beam_size: int,
        journal: SolutionJournal
    ) -> List[SolutionNode]:
        """
        Select diverse candidates using beam search.
        
        This maintains top-K candidates while ensuring diversity.
        """
        if len(candidates) <= beam_size:
            return candidates
            
        # Score candidates based on multiple factors
        scored_candidates = []
        for node in candidates:
            score = self._calculate_node_score(node, journal)
            scored_candidates.append((score, node))
            
        # Sort by score (higher is better)
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        
        # Select diverse subset from top candidates
        selected = []
        selected_signatures = set()
        
        for score, node in scored_candidates:
            if len(selected) >= beam_size:
                break
                
            # Generate approach signature
            signature = self._generate_approach_signature(node, journal)
            
            # Check diversity against already selected nodes
            is_diverse = True
            for selected_sig in selected_signatures:
                if self._calculate_similarity(signature, selected_sig) > self.diversity_threshold:
                    is_diverse = False
                    break
                    
            if is_diverse:
                selected.append(node)
                selected_signatures.add(signature)
                
        # If we don't have enough diverse candidates, add best remaining
        if len(selected) < beam_size:
            for score, node in scored_candidates:
                if node not in selected and len(selected) < beam_size:
                    selected.append(node)
                    
        return selected
        
    def _calculate_node_score(self, node: SolutionNode, journal: SolutionJournal) -> float:
        """
        Calculate a score for a node based on multiple factors.
        
        Factors considered:
        - Parent performance (if any)
        - Recency (newer nodes get slight boost)
        - Stage (different stages get different weights)
        - Tree depth (prefer shallower trees initially)
        """
        score = 0.0
        
        # Parent performance factor
        if node.parent_id:
            parent = journal.get_node(node.parent_id)
            if parent and parent.metric_value is not None:
                score += parent.metric_value * 0.5
        else:
            # Root nodes get neutral score
            score += 0.3
            
        # Recency factor (small boost for newer nodes)
        if hasattr(node, 'created_at'):
            all_times = [n.created_at for n in journal.nodes.values() if hasattr(n, 'created_at')]
            if all_times:
                min_time = min(all_times)
                max_time = max(all_times)
                if max_time > min_time:
                    recency = (node.created_at - min_time) / (max_time - min_time)
                    score += recency * 0.1
                    
        # Stage factor
        stage_weights = {
            "draft": 0.2,
            "implement": 0.3,
            "debug": 0.1,
            "improve": 0.4
        }
        score += stage_weights.get(node.stage, 0.2)
        
        # Tree depth factor (prefer exploring shallower nodes first)
        depth = self._calculate_node_depth(node, journal)
        score += max(0, (10 - depth) * 0.05)  # Slight preference for shallower nodes
        
        return score
        
    def _generate_approach_signature(self, node: SolutionNode, journal: SolutionJournal) -> str:
        """
        Generate a signature representing the approach taken by this node.
        
        The signature is based on the plan content and ancestry.
        """
        components = []
        
        # Walk up the tree to get approach context
        current = node
        depth = 0
        while current and depth < 3:  # Limit depth to avoid too long signatures
            if current.plan:
                # Extract key words from plan
                words = [w.lower() for w in current.plan.split() 
                        if len(w) > 4 and w.isalpha()]
                # Take first few significant words
                components.extend(words[:5])
                
            if current.parent_id:
                current = journal.get_node(current.parent_id)
            else:
                current = None
            depth += 1
            
        # Create a hash of the approach
        approach_str = "_".join(sorted(set(components)))
        return hashlib.md5(approach_str.encode()).hexdigest()[:16]
        
    def _calculate_similarity(self, sig1: str, sig2: str) -> float:
        """
        Calculate similarity between two approach signatures.
        
        Simple character-based similarity for now.
        """
        if sig1 == sig2:
            return 1.0
            
        # Count matching characters
        matches = sum(1 for a, b in zip(sig1, sig2) if a == b)
        return matches / max(len(sig1), len(sig2))
        
    def _filter_critical_bugs(self, buggy_nodes: List[SolutionNode]) -> List[SolutionNode]:
        """
        Filter for critical bugs that should be prioritized.
        """
        critical_errors = [
            "FileNotFoundError", "ImportError", "ModuleNotFoundError", 
            "NameError", "AttributeError"
        ]
        
        critical = []
        for node in buggy_nodes:
            error_text = (node.exec_error or "") + (node.exec_stderr or "")
            if any(err in error_text for err in critical_errors):
                critical.append(node)
                
        return critical
        
    def _rank_nodes(self, nodes: List[SolutionNode]) -> List[SolutionNode]:
        """
        Rank nodes by performance and recency.
        """
        def node_key(node):
            metric_score = node.metric_value if node.metric_value is not None else 0
            time_score = node.created_at if hasattr(node, 'created_at') else 0
            return (metric_score, time_score)
            
        return sorted(nodes, key=node_key, reverse=True)
        
    def _filter_diverse_candidates(
        self, 
        candidates: List[SolutionNode], 
        max_count: int,
        journal: SolutionJournal
    ) -> List[SolutionNode]:
        """
        Filter candidates to ensure diversity.
        """
        if len(candidates) <= max_count:
            return candidates
            
        selected = []
        selected_signatures = set()
        
        for node in candidates:
            if len(selected) >= max_count:
                break
                
            signature = self._generate_approach_signature(node, journal)
            
            # Check diversity
            is_diverse = True
            for sig in selected_signatures:
                if self._calculate_similarity(signature, sig) > self.diversity_threshold:
                    is_diverse = False
                    break
                    
            if is_diverse:
                selected.append(node)
                selected_signatures.add(signature)
                
        return selected
        
    def _calculate_node_depth(self, node: SolutionNode, journal: SolutionJournal) -> int:
        """
        Calculate the depth of a node in the tree.
        """
        depth = 0
        current = node
        while current.parent_id:
            depth += 1
            current = journal.get_node(current.parent_id)
            if not current:  # Safety check
                break
        return depth