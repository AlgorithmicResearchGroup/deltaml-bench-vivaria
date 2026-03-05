#!/usr/bin/env python3
"""
Success tracker that maintains a list of successful nodes with their scripts and scores.
"""
from typing import List, Dict, Optional
from dataclasses import dataclass
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from pathlib import Path
import time


@dataclass
class SuccessRecord:
    """Record of a successful node execution"""
    node_id: str
    stage: str
    script_path: str
    score: float
    metric_name: str
    timestamp: float
    plan_summary: str


class SuccessTracker:
    """Tracks successful nodes and their associated scripts"""
    
    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.successes: List[SuccessRecord] = []
        
    def add_success(self, node_id: str, stage: str, script_path: str, 
                   score: float, metric_name: str, plan: str = ""):
        """Add a successful node to the tracker"""
        # Extract first line of plan as summary
        plan_summary = plan.split('\n')[0][:80] if plan else "No plan"
        if len(plan_summary) == 80:
            plan_summary += "..."
            
        record = SuccessRecord(
            node_id=node_id,
            stage=stage,
            script_path=script_path,
            score=score,
            metric_name=metric_name,
            timestamp=time.time(),
            plan_summary=plan_summary
        )
        self.successes.append(record)
        
    def create_success_panel(self, show_last: int = 5) -> Panel:
        """Create a panel showing successful nodes"""
        if not self.successes:
            content = Text("[dim]No successful nodes yet...[/dim]")
            return Panel(content, title="🏆 Successful Nodes", border_style="green")
            
        # Create table
        table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=2)
        table.add_column("Node", style="cyan", width=8)
        table.add_column("Stage", style="white", width=10)
        table.add_column("Score", style="bold green", width=8)
        table.add_column("Script", style="yellow", width=30)
        table.add_column("Plan", style="dim", width=35)
        
        # Show most recent successes
        recent = self.successes[-show_last:] if len(self.successes) > show_last else self.successes
        
        for i, record in enumerate(recent, 1):
            # Format script path to be relative to work_dir
            try:
                rel_path = Path(record.script_path).relative_to(self.work_dir)
                script_display = str(rel_path)
            except:
                script_display = Path(record.script_path).name
                
            table.add_row(
                str(i),
                f"[{record.node_id[-6:]}]",
                record.stage,
                f"{record.score:.4f}",
                script_display,
                record.plan_summary
            )
            
        # Add summary footer
        best = max(self.successes, key=lambda x: x.score)
        footer = Text()
        footer.append(f"\nTotal successful: {len(self.successes)} | ", style="white")
        footer.append(f"Best: {best.score:.4f}", style="bold green")
        footer.append(f" (Node [{best.node_id[-6:]}])", style="cyan")
        
        content = Table.grid()
        content.add_row(table)
        content.add_row(footer)
        
        return Panel(
            content,
            title="🏆 Successful Nodes",
            border_style="green",
            padding=(1, 1)
        )
        
    def get_best_script(self) -> Optional[str]:
        """Get the path to the script with the best score"""
        if not self.successes:
            return None
        best = max(self.successes, key=lambda x: x.score)
        return best.script_path
        
    def get_inline_summary(self) -> Text:
        """Get a one-line summary of successes"""
        if not self.successes:
            return Text("No successes yet", style="dim")
            
        best = max(self.successes, key=lambda x: x.score)
        summary = Text()
        summary.append(f"Successes: {len(self.successes)} | ", style="white")
        summary.append(f"Best: {best.score:.4f}", style="bold green")
        summary.append(f" ({Path(best.script_path).name})", style="yellow")
        
        return summary
        
    def display(self, console: Console, show_last: int = 5):
        """Display the success tracker panel"""
        panel = self.create_success_panel(show_last)
        console.print(panel)