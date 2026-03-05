"""Solution tree visualization for the agent."""

from typing import Optional, Set
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree
from rich.live import Live
from rich import box

from agent.core.solution_tree import SolutionJournal, SolutionNode
from agent.utils.general import console


class SolutionTreeVisualizer:
    """Visualizes the solution tree with color-coded status indicators"""
    
    def __init__(self, journal: SolutionJournal, parallel_explorer=None):
        self.journal = journal
        self.parallel_explorer = parallel_explorer
        self.last_tree_lines = 0  # Track lines for clearing
        
    def _get_node_style(self, node: SolutionNode) -> tuple[str, str]:
        """Get the style and icon for a node based on its status"""
        if not node.has_executed:
            # Check if currently being processed
            if self.parallel_explorer and node.id in self.parallel_explorer.processing_nodes:
                return "yellow", "⏳"  # Currently processing
            else:
                return "dim", "○"  # Not yet processed
        elif node.is_buggy:
            return "red", "❌"  # Failed
        elif node.metric_value is not None and node.metric_value > 0:
            if node.metric_value >= 0.95:
                return "bright_green", "🌟"  # Excellent
            elif node.metric_value >= 0.8:
                return "green", "✅"  # Good
            else:
                return "yellow", "⚡"  # Completed but low score
        else:
            return "cyan", "✓"  # Completed, no metric
    
    def _get_node_label(self, node: SolutionNode, compact: bool = False) -> str:
        """Generate a descriptive label for a node"""
        if compact:
            # Compact mode for cleaner display
            label = f"{node.id[:6]}"
            if node.metric_value is not None:
                label += f" [{node.metric_value:.2f}]"
            return label
        
        parts = [f"{node.id[:8]}"]
        
        # Add stage
        stage_emoji = {
            "implement": "🔨",
            "debug": "🐛", 
            "improve": "📈",
            "draft": "📝"
        }
        parts.append(f"{stage_emoji.get(node.stage, '📄')} {node.stage}")
        
        # Add metric if available
        if node.metric_value is not None:
            parts.append(f"[{node.metric_value:.3f}]")
        
        # Add error type if buggy
        if node.is_buggy and hasattr(node, 'error_metadata'):
            error_type = node.error_metadata.get('error_type', 'error')
            parts.append(f"({error_type})")
        
        # Add timing
        if node.exec_time_seconds:
            parts.append(f"{node.exec_time_seconds:.1f}s")
            
        return " ".join(parts)
    
    def _add_node_to_tree(self, tree_node: Tree, node: SolutionNode, visited: set):
        """Recursively add nodes to the tree"""
        if node.id in visited:
            return
        visited.add(node.id)
        
        style, icon = self._get_node_style(node)
        label = self._get_node_label(node)
        
        # Create tree branch
        branch = tree_node.add(f"{icon} {label}", style=style)
        
        # Add children
        for child_id in node.children_ids:
            child = self.journal.get_node(child_id)
            if child:
                self._add_node_to_tree(branch, child, visited)
    
    def create_tree(self) -> Tree:
        """Create a visual tree representation of the solution journal"""
        # Create title with current status
        title = Text("🌳 Solution Tree", style="bold white")
        
        # Add search status to title
        total_nodes = len(self.journal.nodes)
        if hasattr(self.journal, '_search_complete'):
            title.append(" - Search Complete", style="green")
        else:
            title.append(f" - {total_nodes} nodes explored", style="cyan")
        
        tree = Tree(title)
        
        visited = set()
        
        # Add all root nodes
        for root_id in self.journal.root_node_ids:
            root = self.journal.get_node(root_id)
            if root:
                self._add_node_to_tree(tree, root, visited)
        
        # Add orphaned nodes (shouldn't happen, but just in case)
        for node in self.journal.nodes.values():
            if node.id not in visited and not node.parent_id:
                self._add_node_to_tree(tree, node, visited)
        
        # Add statistics panel
        stats = self._generate_stats()
        tree.add(Panel(stats, title="📊 Statistics", style="dim"))
        
        return tree
    
    def _generate_stats(self) -> str:
        """Generate statistics about the search"""
        total = len(self.journal.nodes)
        successful = len([n for n in self.journal.nodes.values() if not n.is_buggy and n.has_executed])
        failed = len([n for n in self.journal.nodes.values() if n.is_buggy])
        pending = total - successful - failed
        
        best_node = None
        best_metric = 0
        for node in self.journal.nodes.values():
            if node.metric_value and node.metric_value > best_metric:
                best_metric = node.metric_value
                best_node = node
        
        stats_parts = [
            f"Total Nodes: {total}",
            f"✅ Successful: {successful}",
            f"❌ Failed: {failed}",
            f"⏳ Pending: {pending}"
        ]
        
        if best_node:
            stats_parts.append(f"🏆 Best Score: {best_metric:.3f} (Node {best_node.id[:8]})")
        
        return "\n".join(stats_parts)
    
    def display(self, clear_previous: bool = False):
        """Display the tree"""
        tree = self.create_tree()
        console.print(tree)
    
    def create_live_display(self):
        """Create a Live display context for continuous updates"""
        return Live(self.create_tree(), console=console, refresh_per_second=2, transient=True)