#!/usr/bin/env python3
"""
Live tree display using Rich's Live display capability.
This integrates better with the existing Rich console output.
"""
import time
from typing import Optional
from pathlib import Path
from rich.live import Live
from rich.table import Table
from rich.tree import Tree
from rich.panel import Panel
from rich.layout import Layout
from rich.console import Console, Group
from rich.text import Text
from rich import box
from agent.core.solution_tree import SolutionJournal, SolutionNode
from agent.utils.monitoring.success_tracker import SuccessTracker


class LiveTreeDisplay:
    """Live tree display that updates alongside agent output"""
    
    def __init__(self, journal: SolutionJournal, success_tracker: Optional[SuccessTracker] = None):
        self.journal = journal
        self.success_tracker = success_tracker
        self.console = Console()
        self.current_node_id: Optional[str] = None
        
    def set_current_node(self, node_id: str):
        """Update the current active node"""
        self.current_node_id = node_id
        
    def create_tree_visual(self) -> Panel:
        """Create a visual representation of the tree with success tracking"""
        # Create tree content
        tree_content = self._create_tree_content()
        
        # If we have successes, create a layout with both tree and success sections
        if self.success_tracker and self.success_tracker.successes:
            # Create layout
            layout = Layout()
            layout.split_column(
                Layout(name="tree", ratio=3),
                Layout(name="successes", ratio=1)
            )
            
            # Add content to sections
            layout["tree"].update(tree_content)
            
            success_content = self._create_success_content()
            layout["successes"].update(success_content)
            
            return Panel(
                layout,
                title="🌳 SOLUTION TREE",
                border_style="bold blue",
                padding=(0, 1)
            )
        else:
            # Just return the tree content directly
            return Panel(
                tree_content,
                title="🌳 SOLUTION TREE",
                border_style="bold blue",
                padding=(0, 1)
            )
        
    def _create_tree_content(self):
        """Create the tree visualization content"""
        if not self.journal.nodes:
            return Text("No nodes yet...", style="dim")
            
        # Create tree
        tree = Tree("🌳 Search Tree", guide_style="dim")
        
        # Build tree from roots
        root_nodes = [n for n in self.journal.nodes.values() if n.parent_id is None]
        for root in sorted(root_nodes, key=lambda n: n.created_at):
            self._add_node_to_tree(tree, root)
            
        # Create summary stats
        stats = self._create_stats()
        
        # Combine tree and stats
        content = Group(tree, Text(""), stats)
        
        return content
        
    def _add_node_to_tree(self, parent_tree: Tree, node: SolutionNode):
        """Recursively add nodes to tree"""
        # Create node label
        label = self._create_node_label(node)
        
        # Determine if this is the current node
        is_current = node.id == self.current_node_id
        
        # Add to tree with appropriate styling
        if is_current:
            branch = parent_tree.add(label, style="yellow", guide_style="yellow")
        else:
            branch = parent_tree.add(label)
            
        # Add children
        children = sorted(
            [n for n in self.journal.nodes.values() if n.parent_id == node.id],
            key=lambda n: n.created_at
        )
        for child in children:
            self._add_node_to_tree(branch, child)
            
    def _create_node_label(self, node: SolutionNode) -> Text:
        """Create a formatted label for a node"""
        # Check if this is current node
        is_current = node.id == self.current_node_id
        
        # Status icon
        if not node.has_executed:
            if is_current:
                icon = "▶"
                style = "bold yellow"
            else:
                icon = "⏳"
                style = "yellow"
        elif node.is_buggy:
            icon = "❌"
            style = "red"
        else:
            icon = "✅"
            style = "green"
            
        # Base label
        label = Text(f"{icon} ", style=style)
        label.append(f"{node.stage}", style="bold white" if is_current else "white")
        label.append(f" [{node.id[:6]}]", style="bright_cyan" if is_current else "dim cyan")
        
        # Add metric if available
        if node.metric_value is not None:
            label.append(f" = {node.metric_value:.4f}", style="bold green")
            
        # Add current indicator
        if is_current:
            label.append(" ◀ CURRENT", style="bold yellow")
            
        # Add exploration indicator if available
        if node.metadata and "has_exploration" in node.metadata:
            if node.metadata["has_exploration"]:
                label.append(" 🔍", style="blue")
            else:
                label.append(" ⚠️", style="yellow")
                
        return label
        
    def _create_stats(self) -> Table:
        """Create statistics table"""
        stats = Table(show_header=False, box=None)
        stats.add_column("Stat", style="dim")
        stats.add_column("Value", justify="right")
        
        # Count nodes by status
        total = len(self.journal.nodes)
        executed = sum(1 for n in self.journal.nodes.values() if n.has_executed)
        successful = sum(1 for n in self.journal.nodes.values() if n.has_executed and not n.is_buggy)
        failed = sum(1 for n in self.journal.nodes.values() if n.has_executed and n.is_buggy)
        pending = total - executed
        
        stats.add_row("Total Nodes:", str(total))
        stats.add_row("✅ Successful:", str(successful), style="green")
        stats.add_row("❌ Failed:", str(failed), style="red") 
        stats.add_row("⏳ Pending:", str(pending), style="yellow")
        
        # Best metric
        if self.journal.good_nodes:
            best_nodes = [n for n in self.journal.good_nodes if n.metric_value is not None]
            if best_nodes:
                best = max(best_nodes, key=lambda n: n.metric_value or 0)
                stats.add_row("", "")  # Spacer
                stats.add_row("🏆 Best Score:", f"{best.metric_value:.3f}", style="bold cyan")
                
        return stats
        
    def _create_success_content(self) -> Panel:
        """Create success tracker content"""
        if not self.success_tracker or not self.success_tracker.successes:
            return Panel("No successes yet", title="Successes", border_style="green")
            
        # Create table
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=2)
        table.add_column("Score", style="bold green", width=8)
        table.add_column("Script", style="yellow", width=35)
        table.add_column("Stage", style="white", width=12)
        
        # Show recent successes
        for i, record in enumerate(self.success_tracker.successes[-3:], 1):
            script_name = Path(record.script_path).name
            if len(script_name) > 35:
                script_name = script_name[:32] + "..."
            table.add_row(
                str(i),
                f"{record.score:.4f}",
                script_name,
                record.stage[:12]
            )
            
        return Panel(
            table,
            title=f"🏆 Successful Scripts ({len(self.success_tracker.successes)} total)",
            border_style="green",
            padding=(0, 1)
        )


class CompactTreeDisplay:
    """Ultra-compact tree display for inline use"""
    
    def __init__(self, journal: SolutionJournal):
        self.journal = journal
        
    def get_compact_tree(self) -> str:
        """Get a compact string representation of the tree"""
        if not self.journal.nodes:
            return "🌳 Empty tree"
            
        lines = []
        for root_id in self.journal.root_node_ids:
            self._build_compact_tree(lines, root_id, "")
            
        return "\n".join(lines)
        
    def _build_compact_tree(self, lines: list, node_id: str, prefix: str):
        """Build compact tree representation"""
        node = self.journal.get_node(node_id)
        if not node:
            return
            
        # Status
        if not node.has_executed:
            status = "○"
        elif node.is_buggy:
            status = "✗"
        else:
            status = "✓"
            
        # Line
        line = f"{prefix}{status} {node.stage[:3]}"
        if node.metric_value is not None:
            line += f"({node.metric_value:.2f})"
            
        lines.append(line)
        
        # Children
        for i, child_id in enumerate(node.children_ids):
            child_prefix = prefix + ("└" if i == len(node.children_ids) - 1 else "├")
            self._build_compact_tree(lines, child_id, child_prefix)