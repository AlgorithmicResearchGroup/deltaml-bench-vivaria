#!/usr/bin/env python3
"""
Compact tree status that shows essential info in a single panel.
"""
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.columns import Columns
from rich import box
from agent.core.solution_tree import SolutionJournal, SolutionNode
from agent.utils.monitoring.success_tracker import SuccessTracker


class CompactTreeStatus:
    """Ultra-compact tree status display"""
    
    def __init__(self, journal: SolutionJournal, success_tracker: Optional[SuccessTracker] = None):
        self.journal = journal
        self.current_node_id: Optional[str] = None
        self.success_tracker = success_tracker
        
    def set_current_node(self, node_id: str):
        """Update the current active node"""
        self.current_node_id = node_id
        
    def create_status_panel(self) -> Panel:
        """Create a compact status panel"""
        # Build status line
        status_parts = []
        
        # Current node
        if self.current_node_id:
            node = self.journal.get_node(self.current_node_id)
            if node:
                current = Text()
                current.append("▶ ", style="bold yellow")
                current.append(f"{node.stage} [{node.id[-6:]}]", style="bold cyan")
                status_parts.append(current)
        else:
            status_parts.append(Text("▶ Starting...", style="yellow"))
            
        # Separator
        status_parts.append(Text(" │ ", style="dim"))
        
        # Path (compact)
        path = self._get_compact_path()
        status_parts.append(path)
        
        # Separator
        status_parts.append(Text(" │ ", style="dim"))
        
        # Stats
        stats = self._get_inline_stats()
        status_parts.append(stats)
        
        # Separator
        status_parts.append(Text(" │ ", style="dim"))
        
        # Best score
        best = self._get_best_score()
        status_parts.append(best)
        
        # Add success tracker info if available
        if self.success_tracker and self.success_tracker.successes:
            # Separator
            status_parts.append(Text(" │ ", style="dim"))
            
            # Success summary
            success_summary = self.success_tracker.get_inline_summary()
            status_parts.append(success_summary)
        
        # Combine all parts
        status_line = Text()
        for part in status_parts:
            status_line.append(part)
            
        return Panel(
            status_line,
            title="🌳 TREE STATUS",
            title_align="left",
            border_style="bold blue",
            padding=(0, 1)
        )
        
    def _get_compact_path(self) -> Text:
        """Get ultra-compact path representation"""
        if not self.current_node_id:
            return Text("Path: -", style="dim")
            
        path_nodes = []
        node_id = self.current_node_id
        
        while node_id and len(path_nodes) < 4:
            node = self.journal.get_node(node_id)
            if not node:
                break
                
            if node.has_executed:
                symbol = "✓" if not node.is_buggy else "✗"
                style = "green" if not node.is_buggy else "red"
            else:
                symbol = "○"
                style = "yellow"
                
            path_nodes.append(f"[{style}]{symbol}[/{style}]")
            node_id = node.parent_id
            
        path_nodes.reverse()
        
        path_text = Text("Path: ")
        path_text.append("→".join(path_nodes[-3:]))  # Show last 3
        if len(path_nodes) > 3:
            path_text = Text("Path: ...→") + Text("→".join(path_nodes[-3:]))
            
        return path_text
        
    def _get_inline_stats(self) -> Text:
        """Get inline statistics"""
        total = len(self.journal.nodes)
        successful = sum(1 for n in self.journal.nodes.values() if n.has_executed and not n.is_buggy)
        failed = sum(1 for n in self.journal.nodes.values() if n.has_executed and n.is_buggy)
        pending = total - successful - failed
        
        stats = Text("Nodes: ")
        stats.append(f"{total} total", style="white")
        stats.append(" (", style="dim")
        stats.append(f"✓{successful}", style="green")
        stats.append(" ", style="dim")
        stats.append(f"✗{failed}", style="red")
        stats.append(" ", style="dim")
        stats.append(f"○{pending}", style="yellow")
        stats.append(")", style="dim")
        
        return stats
        
    def _get_best_score(self) -> Text:
        """Get best score info"""
        best_nodes = [n for n in self.journal.good_nodes if n.metric_value is not None]
        if not best_nodes:
            return Text("Best: none yet", style="dim")
            
        best = max(best_nodes, key=lambda n: n.metric_value or 0)
        
        score_text = Text("Best: ")
        score_text.append(f"{best.metric_value:.3f}", style="bold green")
        score_text.append(f" ({best.stage})", style="dim")
        
        return score_text
        
    def display(self, console: Console):
        """Display the status panel"""
        console.print(self.create_status_panel())