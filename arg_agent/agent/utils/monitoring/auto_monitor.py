"""
Automatic monitoring utilities that run on every solution submission
"""
import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from agent.utils.general import logger, console
from rich.panel import Panel
from rich.table import Table
from rich import box

class AutoMonitor:
    """Automatically monitors GPU/CPU and tracks experiments on submission"""
    
    def __init__(self):
        self.gpu_monitor = None
    
    async def initialize(self):
        """Initialize monitoring tools lazily"""
        if not self.gpu_monitor:
            from agent.tools.gpu_monitor.gpu_monitor_tool_async import GPUMonitorTool
            self.gpu_monitor = GPUMonitorTool()
    
    async def capture_metrics(self, 
                            code: str, 
                            output: str, 
                            metric_value: Optional[float] = None,
                            metric_name: Optional[str] = None,
                            task_name: Optional[str] = None) -> Dict[str, Any]:
        """Capture GPU/CPU metrics and experiment data automatically"""
        await self.initialize()
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "gpu_stats": None,
            "experiment_info": None
        }
        
        # Capture GPU/CPU stats
        try:
            gpu_result = await self.gpu_monitor.execute({"action": "check"})
            if gpu_result and "output" in gpu_result:
                gpu_data = gpu_result["output"]
                results["gpu_stats"] = gpu_data
                
                # Display GPU stats in a nice table
                self._display_gpu_stats(gpu_data)
                
        except Exception as e:
            logger.warning(f"Failed to capture GPU stats: {e}")
        
        # Check if code uses W&B for ML tasks (optional now)
        uses_wandb = "wandb.init" in code and "wandb.log" in code
        is_ml_task = any(keyword in code.lower() for keyword in [
            "train", "model", "epoch", "loss", "accuracy", "optimizer"
        ])
        
        # W&B is now optional - just log status
        if is_ml_task:
            if uses_wandb:
                results["experiment_info"] = {
                    "status": "W&B tracking detected",
                    "uses_wandb": True
                }
                logger.info("✅ W&B tracking detected for ML task")
            else:
                results["experiment_info"] = {
                    "status": "ML task without W&B tracking (optional)",
                    "detected_ml_task": True,
                    "uses_wandb": False
                }
                logger.info("ℹ️ ML task detected - W&B tracking is optional")
            
        # Still log basic metrics locally for reference
        if metric_value is not None and metric_name:
            try:
                exp_dir = Path("experiments")
                exp_dir.mkdir(exist_ok=True)
                
                log_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "task": task_name,
                    "metric_name": metric_name,
                    "metric_value": metric_value,
                    "uses_wandb": uses_wandb,
                    "is_ml_task": is_ml_task
                }
                
                with open(exp_dir / "metrics_summary.jsonl", 'a') as f:
                    f.write(json.dumps(log_entry) + '\n')
                    
            except Exception as e:
                logger.warning(f"Failed to save metric summary: {e}")
        
        return results
    
    def _display_gpu_stats(self, gpu_data: Dict[str, Any]):
        """Display GPU/CPU stats in a formatted way"""
        if not gpu_data or "error" in gpu_data:
            return
            
        # Create monitoring table
        monitor_table = Table(title="🖥️ System Resources", box=box.ROUNDED)
        monitor_table.add_column("Resource", style="cyan")
        monitor_table.add_column("Usage", style="yellow")
        monitor_table.add_column("Details", style="white")
        
        if gpu_data.get("backend") == "cpu":
            # CPU-only system
            cpu_data = gpu_data.get("cpu", {})
            memory_data = gpu_data.get("memory", {})
            
            monitor_table.add_row(
                "CPU", 
                f"{cpu_data.get('percent', 0):.1f}%",
                f"{cpu_data.get('count', 0)} cores"
            )
            
            monitor_table.add_row(
                "Memory",
                f"{memory_data.get('percent', 0):.1f}%",
                f"{memory_data.get('used_gb', 0):.1f}/{memory_data.get('total_gb', 0):.1f} GB"
            )
        else:
            # GPU system
            devices = gpu_data.get("devices", [])
            for device in devices:
                if "memory" in device:
                    monitor_table.add_row(
                        f"GPU {device['device_id']}",
                        f"{device['memory']['utilization_percent']:.1f}%",
                        f"{device['memory']['used_gb']:.1f}/{device['memory']['total_gb']:.1f} GB"
                    )
        
        # Add recommendation if available
        if gpu_data.get("recommendation"):
            monitor_table.add_row(
                "💡 Tip",
                "",
                gpu_data["recommendation"]
            )
        
        console.print(monitor_table)
    
    async def generate_report(self, results: Dict[str, Any]) -> str:
        """Generate a monitoring report for the agent to see"""
        report_lines = []
        
        # Add GPU stats to report
        if results.get("gpu_stats"):
            stats = results["gpu_stats"]
            report_lines.append("\n📊 SYSTEM RESOURCES:")
            
            if stats.get("backend") == "cpu":
                cpu = stats.get("cpu", {})
                mem = stats.get("memory", {})
                report_lines.append(f"  CPU: {cpu.get('percent', 0):.1f}% ({cpu.get('count', 0)} cores)")
                report_lines.append(f"  Memory: {mem.get('percent', 0):.1f}% ({mem.get('used_gb', 0):.1f}/{mem.get('total_gb', 0):.1f} GB)")
            else:
                for device in stats.get("devices", []):
                    if "memory" in device:
                        report_lines.append(
                            f"  GPU {device['device_id']}: {device['memory']['utilization_percent']:.1f}% "
                            f"({device['memory']['used_gb']:.1f}/{device['memory']['total_gb']:.1f} GB)"
                        )
            
            if stats.get("recommendation"):
                report_lines.append(f"  💡 {stats['recommendation']}")
        
        # Add experiment tracking info
        if results.get("experiment_info"):
            exp_info = results["experiment_info"]
            if exp_info.get("uses_wandb"):
                report_lines.append("\n✅ W&B TRACKING DETECTED")
            elif exp_info.get("detected_ml_task"):
                report_lines.append("\nℹ️ ML task detected - experiment tracking is optional")
        
        return "\n".join(report_lines) if report_lines else ""