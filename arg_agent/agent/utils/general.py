import re
import logging
import sys
import tiktoken
import os
from datetime import datetime
from typing import Dict, Any, Optional
from pythonjsonlogger.json import JsonFormatter

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich.columns import Columns
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.live import Live
from rich import box
from rich.align import Align

# Detect if running in Vivaria (disable colors/styling for clean output)
in_vivaria = os.getenv('RUN_ID') is not None or os.getenv('API_URL') is not None

# Helper function to clean console output for Vivaria
def vivaria_safe_print(*args, style=None, **kwargs):
    """Print without styles in Vivaria environment"""
    if in_vivaria and 'style' in kwargs:
        kwargs.pop('style')
    return console.print(*args, **kwargs)

def vivaria_safe_panel(content, **kwargs):
    """Create Panel without styles in Vivaria environment"""
    if in_vivaria:
        kwargs.pop('style', None)
        kwargs.pop('border_style', None)
    return Panel(content, **kwargs)

# Global console for rich output - disable colors in Vivaria for clean output
console = Console(
    width=120, 
    force_terminal=not in_vivaria,  # Don't force terminal colors in Vivaria
    legacy_windows=False,
    color_system=None if in_vivaria else "auto",  # Disable colors in Vivaria
    markup=not in_vivaria,  # Disable markup in Vivaria
    emoji=not in_vivaria,   # Disable emoji in Vivaria
    highlight=not in_vivaria  # Disable syntax highlighting in Vivaria
)

class HumanReadableFormatter(logging.Formatter):
    """Custom formatter for human-readable logs"""
    
    def __init__(self):
        super().__init__()
        
    def format(self, record):
        # Extract custom information
        custom_tags = getattr(record, 'custom_tags', {})
        phase = custom_tags.get('phase', 'system')
        tool = custom_tags.get('tool', None)
        
        # Create timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        
        # Format based on message content and level
        message = record.getMessage()
        
        # Don't format if it's already a rich renderable
        if hasattr(record, '_rich_renderable'):
            return record._rich_renderable
            
        # Handle different types of messages
        if "Iteration" in message and "---" in message:
            return self._format_iteration(message, timestamp)
        elif "Generating plan and code" in message:
            return self._format_generation(message, timestamp)
        elif "Code execution" in message and "failed" in message:
            return self._format_execution_failure(message, timestamp)
        elif "Review for node" in message:
            return self._format_review(message, timestamp)
        elif tool:
            return self._format_tool_execution(message, tool, timestamp)
        else:
            return self._format_standard(message, record.levelname, timestamp, phase)
    
    def _format_iteration(self, message, timestamp):
        iteration_match = re.search(r'Iteration (\d+)/(\d+)', message)
        if iteration_match:
            current, total = iteration_match.groups()
            return f"[{timestamp}] 🔄 ITERATION {current}/{total}"
        return message
    
    def _format_generation(self, message, timestamp):
        stage = ""
        if "draft" in message:
            stage = "DRAFT"
        elif "debug" in message:
            stage = "DEBUG" 
        elif "improve" in message:
            stage = "IMPROVE"
        return f"[{timestamp}] 🧠 GENERATING {stage}"
    
    def _format_execution_failure(self, message, timestamp):
        text = Text()
        text.append(f"[{timestamp}] ", style="dim")
        text.append("❌ EXEC FAILED ", style="bold red")
        if "timed out" in message:
            text.append("(TIMEOUT)", style="red")
        return text
    
    def _format_review(self, message, timestamp):
        text = Text()
        text.append(f"[{timestamp}] ", style="dim")
        text.append("📊 REVIEW ", style="bold cyan")
        
        # Extract review details
        if "Buggy=True" in message:
            text.append("❌ BUGGY ", style="red")
        elif "Buggy=False" in message:
            text.append("✅ CLEAN ", style="green")
            
        # Extract metric if present
        metric_match = re.search(r'Metric=([^\s,]+)', message)
        if metric_match:
            metric = metric_match.group(1)
            if metric != "None":
                text.append(f"📈 {metric}", style="bold")
        
        return text
    
    def _format_tool_execution(self, message, tool, timestamp):
        text = Text()
        text.append(f"[{timestamp}] ", style="dim")
        text.append("🔧 TOOL ", style="bold magenta")
        text.append(f"{tool.upper()}", style="magenta")
        return text
    
    def _format_standard(self, message, level, timestamp, phase):
        text = Text()
        text.append(f"[{timestamp}] ", style="dim")
        
        # Level icon and color
        level_styles = {
            "INFO": ("ℹ️", "blue"),
            "WARNING": ("⚠️", "yellow"), 
            "ERROR": ("❌", "red"),
            "DEBUG": ("🐛", "dim"),
        }
        
        icon, color = level_styles.get(level, ("•", "white"))
        text.append(f"{icon} ", style=color)
        text.append(message[:100], style=color if level != "INFO" else "white")
        if len(message) > 100:
            text.append("...", style="dim")
        
        return text

# Setup Rich logging
class RichTreeLogger:
    """Rich-based logger with tree visualization capabilities"""
    
    def __init__(self):
        self.console = console
        self.current_iteration = 0
        self.node_tree = Tree("🌳 Solution Tree")
        self.current_nodes = {}  # node_id -> tree_node
        
    def log_iteration_start(self, iteration: int, total: int):
        """Log the start of a new iteration with visual separator"""
        self.current_iteration = iteration
        
        panel = Panel.fit(
            f"🔄 Iteration {iteration}/{total}",
            style="bold blue" if not in_vivaria else "",
            border_style="blue"
        )
        self.console.print(panel)
    
    def log_node_creation(self, node_id: str, stage: str, parent_id: Optional[str] = None):
        """Add a node to the solution tree"""
        node_display = f"[{stage.upper()}] {node_id[:8]}..."
        
        if parent_id and parent_id in self.current_nodes:
            parent_tree_node = self.current_nodes[parent_id]
            tree_node = parent_tree_node.add(node_display)
        else:
            tree_node = self.node_tree.add(node_display)
            
        self.current_nodes[node_id] = tree_node
    
    def log_node_execution(self, node_id: str, success: bool, execution_time: float):
        """Update node with execution results"""
        if node_id in self.current_nodes:
            tree_node = self.current_nodes[node_id]
            status = "✅" if success else "❌"
            tree_node.label = f"{tree_node.label} {status} ({execution_time:.1f}s)"
    
    def log_node_review(self, node_id: str, is_buggy: bool, metric_value: Optional[float]):
        """Update node with review results"""
        if node_id in self.current_nodes:
            tree_node = self.current_nodes[node_id]
            bug_status = "🐛" if is_buggy else "🎯"
            metric_str = f" 📊{metric_value:.3f}" if metric_value is not None else ""
            tree_node.label = f"{tree_node.label} {bug_status}{metric_str}"
    
    def show_tree(self):
        """Display the current solution tree"""
        self.console.print(self.node_tree)
    
    def log_execution_summary(self, stdout: str, stderr: str, success: bool):
        """Log execution summary in a formatted way"""
        if stdout:
            stdout_panel = Panel(
                stdout[:500] + ("..." if len(stdout) > 500 else ""),
                title="📤 Output",
                style="green" if success else "red",
                expand=False
            )
            self.console.print(stdout_panel)
            
        if stderr:
            stderr_panel = Panel(
                stderr[:300] + ("..." if len(stderr) > 300 else ""),
                title="⚠️ Errors",
                style="red",
                expand=False
            )
            self.console.print(stderr_panel)
    
    def log_performance_metrics(self, metrics: Dict[str, Any]):
        """Display performance metrics in a table"""
        table = Table(title="📊 Performance Metrics", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")
        
        for key, value in metrics.items():
            if isinstance(value, float):
                table.add_row(key.replace('_', ' ').title(), f"{value:.2f}")
            else:
                table.add_row(key.replace('_', ' ').title(), str(value))
        
        self.console.print(table)

# Global rich tree logger instance
rich_logger = RichTreeLogger()

# Setup standard logger with Rich handler
logger = logging.getLogger("MyAgentLogger")
logger.setLevel(logging.INFO)

# Clear any existing handlers
logger.handlers.clear()

# Create simpler Rich handler without custom formatter
rich_handler = RichHandler(
    console=console,
    show_time=True,
    show_path=False,
    rich_tracebacks=not in_vivaria,  # Disable rich tracebacks in Vivaria
    markup=False,  # Disable markup
    keywords=[]   # Disable keyword highlighting in Vivaria
)

# Don't use custom formatter for now
logger.addHandler(rich_handler)
logger.propagate = False

def count_tokens(string: str, encoding_name: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens

def remove_ascii(text):
    pattern = r"[\x00-\x7F]"
    cleaned_string = re.sub(pattern, "", text)
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    result_cleaned = re.sub(
        r"(^|\n)(Out|In)\[[0-9]+\]: ", r"\1", ansi_escape.sub("", text)
    )
    return result_cleaned

def clean_message(error_message):
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    clean_message = ansi_escape.sub("", error_message)
    clean_message = clean_message.strip()
    clean_message = clean_message.replace("\n", " ")
    clean_message = re.sub(r"\s+", " ", clean_message)
    return clean_message

def anthropic_to_openai(anthropic_function_call):
    openai_function_call = {
        "type": "function",
        "function": {
            "name": anthropic_function_call["name"],
            "description": anthropic_function_call["description"],
            "parameters": anthropic_function_call["input_schema"],
        },
    }
    return openai_function_call

# Helper functions for rich logging
def log_with_panel(title: str, content: str, style: str = "blue"):
    """Log content in a rich panel"""
    panel = Panel(content, title=title, style=style, expand=False)
    console.print(panel)

def log_code_snippet(code: str, title: str = "Code"):
    """Log code in a syntax-highlighted panel"""
    from rich.syntax import Syntax
    syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
    panel = Panel(syntax, title=title, style="green", expand=False)
    console.print(panel)
