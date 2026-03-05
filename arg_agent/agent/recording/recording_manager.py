"""
Recording manager for saving agent execution results and summaries.
"""

import logging
import asyncio
import os
import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from agent.core.solution_tree import SolutionNode
from agent.storage.storage_interface import CloudStorageInterface
from agent.utils.monitoring.auto_monitor import AutoMonitor

logger = logging.getLogger(__name__)
console = Console()


class RecordingManager:
    """Handles recording and storage of agent execution results"""
    
    def __init__(self, 
                 working_dir: Path, 
                 config: Dict[str, Any], 
                 storage_client: Optional[CloudStorageInterface] = None,
                 auto_monitor: Optional[AutoMonitor] = None,
                 run_id: str = "",
                 task_name: Optional[str] = None,
                 user_query: str = "",
                 success_metric: str = "accuracy",
                 success_threshold: Optional[float] = None,
                 subtask_id: Optional[str] = None):
        """
        Initialize recording manager.
        
        Args:
            working_dir: Working directory for saving files
            config: Configuration dictionary
            storage_client: Optional cloud storage client
            auto_monitor: Optional auto monitor for metrics
            run_id: Run identifier
            task_name: Task name for organization
            user_query: User query for context
            success_metric: Success metric name
            success_threshold: Success threshold value
            subtask_id: Optional subtask ID for organizing outputs
        """
        self.working_dir = working_dir
        self.config = config
        self.storage_client = storage_client
        self.auto_monitor = auto_monitor
        self.run_id = run_id
        self.task_name = task_name
        self.user_query = user_query
        self.success_metric = success_metric
        self.success_threshold = success_threshold
        self.subtask_id = subtask_id
        self.outputs_folder = self._get_outputs_folder()
        self.storage_config = config.get('storage', {})
    
    def _get_outputs_folder(self) -> Path:
        """Get the outputs folder path"""
        if self.subtask_id:
            return Path(self.config.get("OUTPUT_DIR", "./outputs")) / self.subtask_id
        return Path(self.config.get("OUTPUT_DIR", "./outputs"))
    
    async def save_node_to_storage(self, node: SolutionNode) -> Optional[str]:
        """Save node execution results to cloud storage"""
        if not self.storage_client or not node.has_executed:
            return None
            
        try:
            # Prepare node data for storage
            node_data = {
                "run_id": self.run_id,
                "node_id": node.id,
                "parent_id": node.parent_id,
                "stage": node.stage,
                "created_at": node.created_at,
                "executed_at": node.executed_at,
                "reviewed_at": node.reviewed_at,
                "exec_time_seconds": node.exec_time_seconds,
                "is_successful": node.is_successful_execution,
                "is_buggy": node.is_buggy,
                "metric_name": node.metric_name,
                "metric_value": node.metric_value,
                "working_directory": str(node.working_directory) if node.working_directory else None,
                "plan": node.plan,
                "code": node.code,
                "exec_stdout": node.exec_stdout,
                "exec_stderr": node.exec_stderr,
                "exec_error": node.exec_error,
                "analysis": node.analysis,
                "generation_prompt": node.generation_prompt[:1000] if node.generation_prompt else "",  # Truncate for storage
                "review_prompt": node.review_prompt[:1000] if node.review_prompt else "",
                "metadata": node.metadata,
                "task_name": self.task_name,
                "user_query": self.user_query,
                "success_metric": self.success_metric,
                "success_threshold": self.success_threshold,
            }
            
            # Save as JSON
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            storage_key = f"experiments/{self.task_name or 'unknown'}/{self.run_id}/nodes/{timestamp}_{node.id}.json"
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(node_data, f, indent=2, default=str)
                temp_path = f.name
            
            # Upload to storage
            bucket = self.storage_config.get('bucket', 'coding-agent-outputs')
            url = await self.storage_client.upload_file(
                local_path=Path(temp_path),
                bucket=bucket,
                key=storage_key
            )
            
            # Clean up temp file
            os.unlink(temp_path)
            
            # Also save the actual code file if it exists
            if node.code and node.working_directory:
                code_file_path = Path(node.working_directory) / f"solution_{node.id[:8]}.py"
                if code_file_path.exists():
                    code_key = f"experiments/{self.task_name or 'unknown'}/{self.run_id}/code/{timestamp}_{node.id}.py"
                    code_url = await self.storage_client.upload_file(
                        local_path=code_file_path,
                        bucket=bucket,
                        key=code_key
                    )
                    logger.info(f"Saved code file to: {code_url}")
            
            logger.info(f"Saved node {node.id[:8]} to storage: {url}")
            return url
            
        except Exception as e:
            logger.error(f"Failed to save node to storage: {e}")
            return None
    
    async def save_final_summary_to_storage(self, final_node: SolutionNode, score: float) -> Optional[str]:
        """Save final run summary and all outputs to cloud storage"""
        if not self.storage_client:
            return None
            
        try:
            summary_data = {
                "run_id": self.run_id,
                "task_name": self.task_name,
                "user_query": self.user_query,
                "success_metric": self.success_metric,
                "success_threshold": self.success_threshold,
                "final_score": score,
                "final_node_id": final_node.id,
                "final_stage": final_node.stage,
                "is_successful": final_node.is_successful_execution,
                "metric_achieved": score >= (self.success_threshold or 0) if self.success_threshold else None,
                "total_nodes_explored": len([n for n in final_node.get_all_ancestors_and_descendants()]),
                "execution_summary": {
                    "has_executed": final_node.has_executed,
                    "is_buggy": final_node.is_buggy,
                    "exec_time_seconds": final_node.exec_time_seconds,
                    "output_preview": final_node.exec_stdout[:1000] if final_node.exec_stdout else "",
                    "error_preview": final_node.exec_stderr[:1000] if final_node.exec_stderr else "",
                },
                "code_summary": {
                    "lines_of_code": len(final_node.code.split('\n')) if final_node.code else 0,
                    "has_solution": bool(final_node.code),
                },
                "timestamp": datetime.now().isoformat(),
            }
            
            # Save summary JSON
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            summary_key = f"experiments/{self.task_name or 'unknown'}/{self.run_id}/final_summary_{timestamp}.json"
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(summary_data, f, indent=2, default=str)
                temp_path = f.name
            
            # Upload to storage
            bucket = self.storage_config.get('bucket', 'coding-agent-outputs')
            url = await self.storage_client.upload_file(
                local_path=Path(temp_path),
                bucket=bucket,
                key=summary_key
            )
            os.unlink(temp_path)
            
            logger.info(f"Saved final summary to: {url}")
            
            # If enabled, zip and upload the entire workspace
            if self.storage_config.get('upload_workspace', True) and final_node.working_directory:
                try:
                    zip_path = Path(self.working_dir) / f"workspace_{self.run_id}.zip"
                    
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for root, dirs, files in os.walk(final_node.working_directory):
                            for file in files:
                                file_path = Path(root) / file
                                arcname = file_path.relative_to(final_node.working_directory)
                                zipf.write(file_path, arcname)
                    
                    workspace_key = f"experiments/{self.task_name or 'unknown'}/{self.run_id}/workspace_{timestamp}.zip"
                    workspace_url = await self.storage_client.upload_file(
                        local_path=zip_path,
                        bucket=bucket,
                        key=workspace_key
                    )
                    
                    # Clean up zip file
                    os.unlink(zip_path)
                    logger.info(f"Saved workspace to: {workspace_url}")
                    
                except Exception as e:
                    logger.warning(f"Failed to save workspace: {e}")
            
            return url
            
        except Exception as e:
            logger.error(f"Failed to save final summary to storage: {e}")
            return None
    
    async def save_script_summary(self, final_code: str, final_plan: str, execution_time: float) -> None:
        """Save script summary to file"""
        try:
            await self._ensure_outputs_folder()
            
            script_path = self.outputs_folder / "solution_script.py"
            summary_path = self.outputs_folder / "solution_summary.md"
            
            # Save the script
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: script_path.write_text(final_code)
            )
            
            # Create summary
            summary = f"""# Solution Summary

## Plan
{final_plan}

## Execution Time
{execution_time:.2f} seconds

## Script Location
{script_path}
"""
            
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: summary_path.write_text(summary)
            )
            
            console.print(f"\n[green]✓[/green] Script saved to: {script_path}")
            console.print(f"[green]✓[/green] Summary saved to: {summary_path}")
            
        except Exception as e:
            logger.error(f"Failed to save script summary: {e}")
    
    async def print_final_summary(self, final_result: Dict[str, Any]) -> None:
        """Print final execution summary"""
        console.print("\n" + "="*80)
        console.print(Panel.fit("[bold green]✨ EXECUTION COMPLETE ✨[/bold green]", style="green"))
        
        # # Show result
        # if final_result.get("success"):
        #     console.print("\n[bold green]✅ SUCCESS![/bold green]")
        #     if final_result.get("output"):
        #         console.print(f"\n📊 Output:\n{final_result['output'][:500]}...")
        # else:
        #     console.print("\n[bold red]❌ FAILED[/bold red]")
        #     if final_result.get("error"):
        #         console.print(f"\n🚨 Error:\n{final_result['error']}")
        
        # Show execution stats
        console.print(f"\n⏱️  Execution time: {final_result.get('execution_time', 0):.2f}s")
        console.print(f"🔄 Iterations: {final_result.get('iterations', 0)}")
        console.print(f"🌳 Nodes explored: {final_result.get('nodes_explored', 0)}")
        
        # Show best solution
        if final_result.get("best_node"):
            best_node = final_result["best_node"]
            console.print("\n📝 Best solution:")
            console.print(f"   Stage: {best_node.get('stage', 'Unknown')}")
            console.print(f"   Score: {best_node.get('score', 0):.4f}")
        
        console.print("="*80 + "\n")
    
    async def run_auto_monitoring(self, node: SolutionNode) -> None:
        """Run automatic GPU/CPU monitoring and experiment tracking"""
        if not self.auto_monitor:
            return
            
        try:
            # Extract metric value if present in output
            metric_value = None
            metric_name = self.success_metric
            
            # Try to extract score from output
            if "score=" in node.exec_stdout:
                import re
                score_match = re.search(r"score=(\d+\.?\d*)", node.exec_stdout)
                if score_match:
                    try:
                        metric_value = float(score_match.group(1))
                    except:
                        pass
            
            # Run auto monitoring
            monitoring_results = await self.auto_monitor.capture_metrics(
                code=node.code,
                output=node.exec_stdout,
                metric_value=metric_value,
                metric_name=metric_name,
                task_name=self.task_name
            )
            
            # Store monitoring results in node metadata
            if monitoring_results:
                node.metadata["monitoring"] = monitoring_results
                
                # Log key metrics
                if "gpu" in monitoring_results:
                    gpu_info = monitoring_results["gpu"]
                    logger.info(f"GPU Usage: {gpu_info.get('gpu_util', 0):.1f}%, "
                              f"Memory: {gpu_info.get('mem_used_gb', 0):.1f}GB, "
                              f"Power: {gpu_info.get('power_watts', 0):.0f}W")
                
                if "metrics" in monitoring_results:
                    metrics = monitoring_results["metrics"]
                    logger.info(f"Captured metrics: {metrics}")
        
        except Exception as e:
            logger.warning(f"Auto monitoring failed: {e}")
            # Don't fail the execution for monitoring errors
    
    async def upload_results_to_gcp(self, local_dir: Path, gcs_dir: str) -> Dict[str, Any]:
        """Upload results to GCP storage"""
        try:
            # Check if gsutil is available
            check_result = await asyncio.create_subprocess_exec(
                "which", "gsutil",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await check_result.communicate()
            
            if check_result.returncode != 0:
                return {
                    "success": False,
                    "error": "gsutil not found. Please install Google Cloud SDK."
                }
            
            # Upload files
            console.print(f"\n[cyan]📤 Uploading results to GCS: {gcs_dir}[/cyan]")
            
            # Run upload in executor to avoid blocking
            def _gcp_upload_sync():
                import subprocess
                cmd = ["gsutil", "-m", "cp", "-r", str(local_dir), gcs_dir]
                result = subprocess.run(cmd, capture_output=True, text=True)
                return result.returncode, result.stdout, result.stderr
            
            returncode, stdout, stderr = await asyncio.get_event_loop().run_in_executor(
                None, _gcp_upload_sync
            )
            
            if returncode == 0:
                console.print(f"[green]✅ Successfully uploaded to {gcs_dir}[/green]")
                return {
                    "success": True,
                    "gcs_path": gcs_dir,
                    "stdout": stdout
                }
            else:
                console.print(f"[red]❌ Upload failed: {stderr}[/red]")
                return {
                    "success": False,
                    "error": stderr,
                    "stdout": stdout
                }
                
        except Exception as e:
            logger.error(f"Failed to upload to GCP: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _ensure_outputs_folder(self) -> None:
        """Ensure outputs folder exists"""
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.outputs_folder.mkdir(parents=True, exist_ok=True)
        )