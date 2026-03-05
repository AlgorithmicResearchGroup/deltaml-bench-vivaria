#!/usr/bin/env python3
"""
Simple persistent tree display using a status panel that updates in place.
"""
from typing import Optional
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree
from rich.table import Table
from rich.live import Live
from agent.core.solution_tree import SolutionJournal, SolutionNode


class SimplePersistentDisplay:
    """Simple tree display that updates in a fixed panel"""
    
    def __init__(self, journal: SolutionJournal):
        self.journal = journal
        self.current_node_id: Optional[str] = None
        self._last_panel = None
        
    def set_current_node(self, node_id: str):
        """Update the current active node"""
        self.current_node_id = node_id
        
    def create_status_panel(self) -> Panel:
        """Create a compact status panel"""
        content = []
        
        # Header
        header = Text("🌳 SOLUTION TREE", style="bold white", justify="center")
        content.append(header)
        content.append(Text("─" * 40, style="dim"))
        
        # Current node
        if self.current_node_id:
            current = self.journal.get_node(self.current_node_id)
            if current:
                current_text = Text("▶ CURRENT: ", style="bold yellow")
                current_text.append(f"{current.stage} [{current.id[-6:]}]", style="cyan")
                content.append(current_text)
                content.append(Text("─" * 40, style="dim"))
        
        # Tree structure (compact)
        tree_lines = self._build_compact_tree()
        content.append(Text(tree_lines, style="white"))
        
        # Stats
        content.append(Text("─" * 40, style="dim"))
        stats = self._get_stats()
        content.append(stats)
        
        # Create panel
        panel = Panel(
            Group(*content),
            title="Tree Monitor",
            border_style="blue",
            width=45,
            height=None  # Auto height
        )
        
        self._last_panel = panel
        return panel
        
    def _build_compact_tree(self) -> str:
        """Build a compact tree representation"""
        if not self.journal.nodes:
            return "[dim]No nodes yet...[/dim]"
            
        lines = []
        for root_id in self.journal.root_node_ids:
            self._build_tree_lines(lines, root_id, "", is_last=True)
            
        # Limit to last 15 lines to keep it compact
        if len(lines) > 15:
            lines = ["..."] + lines[-14:]
            
        return "\n".join(lines)
        
    def _build_tree_lines(self, lines: list, node_id: str, prefix: str, is_last: bool):
        """Recursively build tree lines"""
        node = self.journal.get_node(node_id)
        if not node:
            return
            
        # Node symbol
        if not node.has_executed:
            if node_id == self.current_node_id:
                symbol = "▶"
                style = "[bold yellow]"
            else:
                symbol = "○"
                style = "[yellow]"
        elif node.is_buggy:
            symbol = "✗"
            style = "[red]"
        else:
            symbol = "✓"
            style = "[green]"
            
        # Branch
        if prefix:
            branch = "└─" if is_last else "├─"
        else:
            branch = ""
            
        # Node text
        node_text = f"{prefix}{branch}{style}{symbol}[/] {node.stage[:3]}"
        if node.metric_value is not None:
            node_text += f" ({node.metric_value:.2f})"
        if node_id == self.current_node_id:
            node_text += " [bold yellow]◀[/]"
            
        lines.append(node_text)
        
        # Children
        if node.children_ids:
            extension = "  " if is_last else "│ "
            child_prefix = prefix + extension
            for i, child_id in enumerate(node.children_ids):
                is_last_child = i == len(node.children_ids) - 1
                self._build_tree_lines(lines, child_id, child_prefix, is_last_child)
                
    def _get_stats(self) -> Text:
        """Get compact stats"""
        total = len(self.journal.nodes)
        successful = sum(1 for n in self.journal.nodes.values() if n.has_executed and not n.is_buggy)
        failed = sum(1 for n in self.journal.nodes.values() if n.has_executed and n.is_buggy)
        pending = total - successful - failed
        
        stats = Text()
        stats.append(f"Nodes: {total} ", style="white")
        stats.append(f"✓{successful} ", style="green")
        stats.append(f"✗{failed} ", style="red")
        stats.append(f"○{pending}", style="yellow")
        
        # Best score
        best_nodes = [n for n in self.journal.good_nodes if n.metric_value is not None]
        if best_nodes:
            best = max(best_nodes, key=lambda n: n.metric_value or 0)
            stats.append(f"\n🏆 Best: {best.metric_value:.3f}", style="bold cyan")
            
        return stats
        
    def display(self, console: Console):
        """Display the current panel"""
        panel = self.create_status_panel()
        console.print(panel)