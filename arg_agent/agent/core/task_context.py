"""Task context utilities to help agents understand their working environment"""
import os
from pathlib import Path
from typing import Dict, List, Optional


class TaskContext:
    """Simple task context class for Vivaria integration"""
    
    def __init__(self, task_description: str, workspace_dir: str, max_iterations: int = 50):
        self.task_description = task_description
        self.workspace_dir = Path(workspace_dir)
        self.max_iterations = max_iterations
        self.current_iteration = 0
        
    def get_workspace_context(self) -> str:
        """Get working directory context"""
        return generate_working_directory_context(self.workspace_dir)
        
    def increment_iteration(self):
        """Increment the current iteration counter"""
        self.current_iteration += 1
        
    def is_max_iterations_reached(self) -> bool:
        """Check if maximum iterations reached"""
        return self.current_iteration >= self.max_iterations


def generate_working_directory_context(work_dir: Path) -> str:
    """Generate a clear description of the working directory structure"""
    
    context_lines = [
        "🗂️ WORKING DIRECTORY INFORMATION:",
        f"Your current working directory is: {work_dir}",
        "",
        "📁 Available files and directories:"
    ]
    
    # List all files and directories in the working directory
    try:
        items = []
        for item in work_dir.iterdir():
            if item.is_dir():
                # Count files in subdirectory
                file_count = sum(1 for _ in item.rglob("*") if _.is_file())
                items.append(f"  📂 {item.name}/ ({file_count} files)")
                # Show first few files in each directory
                sub_items = list(item.iterdir())[:5]
                for sub_item in sub_items:
                    if sub_item.is_file():
                        items.append(f"     - {sub_item.name}")
            else:
                size = item.stat().st_size
                size_str = f"{size/1024:.1f}KB" if size > 1024 else f"{size}B"
                items.append(f"  📄 {item.name} ({size_str})")
        
        if items:
            context_lines.extend(items)
        else:
            context_lines.append("  (Working directory is empty)")
            
    except Exception as e:
        context_lines.append(f"  Error listing directory contents: {e}")
    
    context_lines.extend([
        "",
        "💡 IMPORTANT NOTES:",
        "- All file paths should be relative to your current working directory",
        "- Use '.' or Path.cwd() to refer to the current directory",
        "- DO NOT use hardcoded absolute paths like /root/BENCHMARKS/",
        "- To check your current directory, use: run_bash tool with 'pwd'",
        "- To list files, use: run_bash tool with 'ls -la'",
        ""
    ])
    
    return "\n".join(context_lines)

