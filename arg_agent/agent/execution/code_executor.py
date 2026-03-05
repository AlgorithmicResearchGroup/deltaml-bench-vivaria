"""
Main code executor that handles Python code execution in isolated environments.
"""

import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import logging
import aiofiles
import shutil

from rich.console import Console
from rich.text import Text
from rich.panel import Panel

from .execution_result import ExecutionResult, ExecutionStatus
from .execution_cache import ExecutionCache
from .gpu_allocator import GPUAllocator
from agent.tools.python.python_tool_async import AsyncPythonRunnerActor

logger = logging.getLogger(__name__)


class CodeExecutor:
    """Handles code execution in isolated environments"""
    
    def __init__(
        self,
        work_dir: Path,
        cache_ttl: int = 3600,
        enable_caching: bool = True,
        enable_gpu_allocation: bool = True,
        default_timeout: float = 18000.0
    ):
        """
        Initialize code executor.
        
        Args:
            work_dir: Working directory for code execution
            cache_ttl: Cache time-to-live in seconds
            enable_caching: Whether to enable execution caching
            enable_gpu_allocation: Whether to enable GPU allocation
            default_timeout: Default execution timeout in seconds
        """
        self.work_dir = work_dir
        self.python_runner = AsyncPythonRunnerActor()
        self.cache = ExecutionCache(ttl_seconds=cache_ttl) if enable_caching else None
        self.gpu_allocator = GPUAllocator() if enable_gpu_allocation else None
        self.console = Console()
        self.default_timeout = default_timeout
        self._simple_return_setup = False
    
    async def execute(
        self,
        code: str,
        node_id: str,
        stage: str,
        timeout: Optional[float] = None,
        gpu_device: Optional[int] = None,
        save_script: bool = True
    ) -> ExecutionResult:
        """
        Execute Python code and return results.
        
        Args:
            code: Python code to execute
            node_id: ID of the node being executed
            stage: Execution stage (implement, debug, improve)
            timeout: Execution timeout in seconds (uses default if None)
            gpu_device: GPU ID to use (auto-allocates if None)
            save_script: Whether to save the script to disk
            
        Returns:
            ExecutionResult with execution details
        """
        if not code:
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error="No code provided",
                execution_time=0.0
            )
        
        start_time = time.time()
        timeout = timeout or self.default_timeout
        
        # Check cache first
        if self.cache:
            cached_result = self.cache.get(code)
            if cached_result:
                result = ExecutionResult(
                    status=ExecutionStatus.SUCCESS if not cached_result.is_buggy else ExecutionStatus.FAILURE,
                    stdout=cached_result.stdout,
                    stderr=cached_result.stderr,
                    error=cached_result.error,
                    execution_time=time.time() - start_time,
                    cached=True
                )
                return result
        
        # Setup execution environment
        script_path = None
        if save_script:
            script_path = await self._save_script(
                code, node_id, stage
            )
        
        # Handle GPU allocation
        allocated_gpu = gpu_device
        if allocated_gpu is None and self.gpu_allocator:
            allocated_gpu = self.gpu_allocator.allocate(node_id)
        
        # Modify code for GPU if allocated
        execution_code = code
        if allocated_gpu is not None:
            execution_code = self.gpu_allocator.inject_device_selection(code, allocated_gpu)
            self._show_gpu_allocation(node_id, allocated_gpu)
        
        # Setup simple_return.py
        await self._setup_simple_return()
        
        # Show execution start
        self._show_execution_start(node_id, stage)
        
        try:
            # Execute the code
            exec_result = await self.python_runner.execute_python_code_async(
                script_input=execution_code,
                timeout=timeout,
                working_directory=str(self.work_dir)
            )
            
            # Process results
            result = self._process_execution_result(
                exec_result, 
                execution_time=time.time() - start_time,
                script_path=str(script_path) if script_path else None,
                gpu_used=allocated_gpu
            )
            
            # Update cache
            if self.cache:
                self.cache.put(
                    code=code,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    error=result.error,
                    is_buggy=result.status != ExecutionStatus.SUCCESS
                )
            
            # Show execution result
            self._show_execution_result(result)
            
            return result
            
        except Exception as e:
            logger.error(f"System error during execution: {e}")
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error=f"System error: {str(e)}",
                execution_time=time.time() - start_time,
                script_path=str(script_path) if script_path else None
            )
        finally:
            # Release GPU if allocated
            if allocated_gpu is not None and self.gpu_allocator:
                self.gpu_allocator.release(node_id)
    
    async def _save_script(
        self, 
        code: str, 
        node_id: str,
        stage: str
    ) -> Path:
        """Save script to disk for later reference"""
        scripts_dir = self.work_dir / "scripts" / f"node_{node_id[:8]}"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        
        script_filename = f"script_{stage}_{int(time.time() * 1000000)}.py"
        script_path = scripts_dir / script_filename
        
        async with aiofiles.open(script_path, 'w') as f:
            await f.write(f"# Generated script for node {node_id}\n")
            await f.write(f"# Stage: {stage}\n")
            await f.write(f"# Created at: {datetime.now()}\n\n")
            await f.write(code)
        
        # Log that we saved the script
        save_text = Text()
        save_text.append("💾 SCRIPT SAVED: ", style="dim blue")
        save_text.append(f"scripts/node_{node_id[:8]}/{script_filename}", style="bold blue")
        self.console.print(save_text)
        
        return script_path
    
    async def _setup_simple_return(self) -> None:
        """Setup simple_return.py in working directory"""
        if self._simple_return_setup:
            return
        
        simple_return_dest = self.work_dir / 'simple_return.py'
        if simple_return_dest.exists():
            self._simple_return_setup = True
            return
        
        # Try to copy from utils
        simple_return_source = Path(__file__).parent.parent / 'utils' / 'simple_return.py'
        if simple_return_source.exists():
            shutil.copy2(simple_return_source, simple_return_dest)
            logger.info(f"✅ Copied simple_return.py to {self.work_dir}")
        else:
            # Create it directly
            simple_return_code = '''#!/usr/bin/env python3
"""
Simple return function that generated code can use to submit answers.
This avoids complex imports and async issues.
"""

def submit_answer(predictions, score, submission_path='submission.txt', score_path='score.txt'):
    """
    Submit answer in the expected format.
    
    Args:
        predictions: List or array of predictions
        score: Achieved score/accuracy
        submission_path: Path to save predictions (default: submission.txt)
        score_path: Path to save score (default: score.txt)
    """
    # Save predictions
    with open(submission_path, 'w') as f:
        if isinstance(predictions, (list, tuple)):
            f.write('\\n'.join(map(str, predictions)))
        else:
            f.write(str(predictions))
    
    # Save score
    with open(score_path, 'w') as f:
        f.write(str(score))
    
    # Signal completion
    print(f"TASK_COMPLETE: submission_path={submission_path} score={score}")
    
    return {
        'status': 'success',
        'submission_path': submission_path,
        'score_path': score_path,
        'score': score
    }

# Make it available as a direct call
if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3:
        # Can be called from command line
        # Usage: python simple_return.py "1,2,3,4,5" 0.95
        predictions = sys.argv[1].split(',')
        score = float(sys.argv[2])
        submit_answer(predictions, score)
'''
            async with aiofiles.open(simple_return_dest, 'w') as f:
                await f.write(simple_return_code)
            logger.info(f"✅ Created simple_return.py in {self.work_dir}")
        
        self._simple_return_setup = True
    
    def _process_execution_result(
        self, 
        exec_result: Dict[str, Any],
        execution_time: float,
        script_path: Optional[str] = None,
        gpu_used: Optional[int] = None
    ) -> ExecutionResult:
        """Process raw execution result into ExecutionResult"""
        stdout = exec_result.get("stdout", "")
        stderr = exec_result.get("stderr", "")
        
        if exec_result.get("status") == "failure":
            error = stderr if stderr else "Execution failed"
            if "Python execution timed out" in stderr:
                return ExecutionResult(
                    status=ExecutionStatus.TIMEOUT,
                    stdout=stdout,
                    stderr=stderr,
                    error=f"Timeout: {stderr}",
                    execution_time=execution_time,
                    script_path=script_path,
                    gpu_used=gpu_used
                )
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                stdout=stdout,
                stderr=stderr,
                error=error,
                execution_time=execution_time,
                script_path=script_path,
                gpu_used=gpu_used
            )
        
        return ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            stdout=stdout,
            stderr=stderr,
            execution_time=execution_time,
            script_path=script_path,
            gpu_used=gpu_used
        )
    
    def _show_execution_start(self, node_id: str, stage: str) -> None:
        """Show execution start message"""
        exec_panel = Panel.fit(
            f"⚡ Executing {stage} code for node {node_id[:8]}...",
            style="yellow",
            border_style="yellow"
        )
        self.console.print(exec_panel)
    
    def _show_gpu_allocation(self, node_id: str, gpu_id: int) -> None:
        """Show GPU allocation message"""
        gpu_text = Text()
        gpu_text.append("🖥️ GPU ALLOCATION: ", style="dim blue")
        gpu_text.append(f"Node {node_id[:8]} → GPU {gpu_id}", style="bold blue")
        self.console.print(gpu_text)
    
    def _show_execution_result(self, result: ExecutionResult) -> None:
        """Show execution result message"""
        if result.status == ExecutionStatus.SUCCESS:
            success_text = Text()
            success_text.append("✅ EXECUTION SUCCESS ", style="bold green")
            success_text.append(f"({result.execution_time:.1f}s)", style="dim")
            if result.cached:
                success_text.append(" [CACHED]", style="dim yellow")
            self.console.print(success_text)
        else:
            failure_panel = Panel(
                f"❌ Execution failed: {result.error}",
                style="red"
            )
            self.console.print(failure_panel)