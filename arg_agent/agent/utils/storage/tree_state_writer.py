#!/usr/bin/env python3
"""
Tree state writer that saves tree state to file for external monitor
"""
import json
import time
from pathlib import Path
from typing import Optional
from agent.core.solution_tree import SolutionJournal, SolutionNode
from agent.utils.monitoring.success_tracker import SuccessTracker


class TreeStateWriter:
    """Writes tree state to file for external monitoring"""
    
    def __init__(self, journal: SolutionJournal, success_tracker: Optional[SuccessTracker] = None,
                 state_file: Path = Path("/tmp/tree_monitor_state.json")):
        self.journal = journal
        self.success_tracker = success_tracker
        self.state_file = state_file
        self.current_node_id: Optional[str] = None
        
    def set_current_node(self, node_id: str):
        """Update current node and write state"""
        self.current_node_id = node_id
        self.write_state()
        
    def write_state(self):
        """Write current state to file"""
        state = {
            'timestamp': time.time(),
            'current_node_id': self.current_node_id,
            'nodes': {},
            'successes': [],
            'best_score': None
        }
        
        # Convert nodes to serializable format
        for node_id, node in self.journal.nodes.items():
            state['nodes'][node_id] = {
                'id': node.id,
                'stage': node.stage,
                'parent_id': node.parent_id,
                'has_executed': node.has_executed,
                'is_buggy': node.is_buggy,
                'metric_value': node.metric_value,
                'children_ids': [n.id for n in self.journal.nodes.values() if n.parent_id == node_id]
            }
            
        # Add success records
        if self.success_tracker:
            for record in self.success_tracker.successes:
                state['successes'].append({
                    'node_id': record.node_id,
                    'stage': record.stage,
                    'score': record.score,
                    'script_name': Path(record.script_path).name if record.script_path else 'unknown',
                    'metric_name': record.metric_name
                })
                
        # Find best score
        best_nodes = [n for n in self.journal.nodes.values() if n.metric_value is not None]
        if best_nodes:
            best = max(best_nodes, key=lambda n: n.metric_value or 0)
            state['best_score'] = best.metric_value
            
        # Write to file
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            # Ignore write errors
            pass