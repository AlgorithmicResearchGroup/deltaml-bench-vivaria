"""
Workspace manager for creating and managing agent working directories.
"""

import os
import asyncio
import shutil
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import aiofiles

logger = logging.getLogger(__name__)

# ANSI color codes for error reporting
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_error(message: str):
    """Print error message in red"""
    print(f"{Colors.RED}{Colors.BOLD}❌ WORKSPACE ERROR: {message}{Colors.END}")

def print_success(message: str):
    """Print success message in green"""
    print(f"{Colors.GREEN}{Colors.BOLD}✅ WORKSPACE SUCCESS: {message}{Colors.END}")

def print_warning(message: str):
    """Print warning message in yellow"""
    print(f"{Colors.YELLOW}{Colors.BOLD}⚠️  WORKSPACE WARNING: {message}{Colors.END}")

def print_info(message: str):
    """Print info message in blue"""
    print(f"{Colors.BLUE}{Colors.BOLD}ℹ️  WORKSPACE INFO: {message}{Colors.END}")


class WorkspaceManager:
    """Manages working directory creation and asset management for agents"""
    
    def __init__(self, run_id: str, worker_number: int, storage_config: Optional[Dict[str, Any]] = None):
        """
        Initialize workspace manager.
        
        Args:
            run_id: Run identifier
            worker_number: Worker number for unique directory naming
            storage_config: Optional storage configuration with data directory paths
        """
        self.run_id = run_id
        self.worker_number = worker_number
        self.storage_config = storage_config or {}
    
    async def create_workspace(self) -> Path:
        """
        Create working directory asynchronously with proper asset copying.
        
        Returns:
            Path to the created working directory
        """
        work_dir = Path("/tmp") / f"worker_{self.run_id}_{self.worker_number}"
        
        # Create directory in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: work_dir.mkdir(parents=True, exist_ok=True))
        
        # Create scratchpad file asynchronously
        scratchpad = work_dir / "scratchpad.txt"
        async with aiofiles.open(scratchpad, "w") as f:
            await f.write("This is a scratchpad file for you to write notes on your task.")

        # Vivaria Integration: Create simple_return.py for compatibility
        # Even though submission goes through Vivaria hooks, agent code may import this
        simple_return_path = work_dir / "simple_return.py"
        simple_return_content = '''#!/usr/bin/env python3
"""
Simple return function that generated code can use to submit answers.
In Vivaria mode, this integrates with the Vivaria submission system.
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
    
    # Signal completion - will be intercepted by Vivaria integration
    print(f"TASK_COMPLETE: submission_path={submission_path} score={score}")
    
    return {
        'status': 'success',
        'submission_path': submission_path,
        'score_path': score_path,
        'score': score
    }
'''
        async with aiofiles.open(simple_return_path, "w") as f:
            await f.write(simple_return_content)

        # Copy relevant task files from current working directory
        current_working_dir = Path(os.getcwd())
        copied_items = await self._copy_task_assets(current_working_dir, work_dir)
        
        if copied_items:
            logger.info(f"Copied {len(copied_items)} task assets: {', '.join(copied_items)}", 
                       extra={'custom_tags': {'phase': 'agent'}})
        else:
            logger.info("No task asset files found to copy from current directory.", 
                       extra={'custom_tags': {'phase': 'agent'}})
        
        # INTEGRATED FILE VERIFICATION - Check if critical files are present
        verification_success = self._verify_critical_files(work_dir, current_working_dir)
        if not verification_success:
            print_error("Critical files missing in workspace! This may cause task failures.")
            print_error("Checking if task family start() method was called properly...")
            
            # Check if files exist in source (current) directory but missing in workspace
            missing_in_source = []
            for file_name in ["static_model.py", "score.py"]:
                source_file = current_working_dir / file_name
                if not source_file.exists():
                    missing_in_source.append(file_name)
            
            if missing_in_source:
                print_error(f"CRITICAL: Files missing from source directory: {', '.join(missing_in_source)}")
                print_error("This indicates the task family start() method did NOT run or failed!")
                print_error("Check that task_family.start(task_obj, run_id) was called in run_agent.py")
            else:
                print_error("Files exist in source but failed to copy to workspace")
                print_error("This indicates a workspace copying issue")
            
            logger.error("Workspace verification failed - critical files missing")
        
        # Create symlink asynchronously
        await self._create_home_symlink(work_dir)
        
        # Handle data directory if provided
        await self._handle_data_directory(work_dir)
        
        # Call task_family.start() if provided
        task_family = self.storage_config.get('task_family')
        task_obj = self.storage_config.get('task_obj')
        if task_family and task_obj and hasattr(task_family, 'start'):
            # Change to work directory temporarily to run start method
            original_cwd = os.getcwd()
            os.chdir(str(work_dir))
            try:
                # Run task_family.start() synchronously in executor to avoid race conditions
                await loop.run_in_executor(
                    None, 
                    task_family.start, 
                    task_obj, 
                    self.run_id
                )
                logger.info(f"Called task_family.start() for {task_family.__class__.__name__}")
                
                # List files after start() to verify
                files_after = list(work_dir.iterdir())
                logger.info(f"Files in work_dir after task.start(): {[f.name for f in files_after]}")
            except Exception as e:
                logger.error(f"Error calling task_family.start(): {e}")
                # Don't raise - allow the agent to continue even if start() fails
                # The agent might still be able to work with partial setup
            finally:
                os.chdir(original_cwd)
        
        return work_dir
    
    def _verify_critical_files(self, work_dir: Path, source_dir: Path) -> bool:
        """
        Verify that critical files were copied successfully.
        Shows red error messages for missing files.
        
        Args:
            work_dir: Working directory to check
            source_dir: Source directory for context
            
        Returns:
            True if all critical files present, False otherwise
        """
        print_info(f"Verifying critical files in workspace: {work_dir.name}")
        
        # Universal critical files that should always be present
        universal_files = {
            "scratchpad.txt": "Agent scratchpad file"
        }
        
        # Add simple_return.py only if not in Vivaria mode
        # In Vivaria mode, submission is handled via hooks.submit() directly
        if not os.environ.get("VIVARIA_MODE") == "true":
            universal_files["simple_return.py"] = "Simple return helper function"
        
        # Try to detect task type from source directory or environment
        task_specific_files = {}
        
        # Check for task-specific patterns in source directory
        if (source_dir / "static_model.py").exists() or any("fix_embedding" in str(f) for f in source_dir.iterdir()):
            task_specific_files.update({
                "score.py": "Task evaluation script",
                "static_model.py": "Static model definition (required for fix_embedding task)"
            })
            print_info("Detected ai_rd_fix_embedding task - checking for static_model.py")
        elif (source_dir / "score.py").exists():
            task_specific_files["score.py"] = "Task evaluation script"
            print_info("Detected RE-bench task - checking for score.py")
        
        # Check if we can detect task from directory contents in work_dir
        if not task_specific_files:
            # Look for clues in the working directory
            for item in work_dir.iterdir():
                if item.name == "static_model.py":
                    task_specific_files["static_model.py"] = "Static model definition"
                elif item.name == "score.py":
                    task_specific_files["score.py"] = "Task evaluation script"
        
        # Combine all files to check
        all_critical_files = {**universal_files, **task_specific_files}
        
        missing_files = []
        verification_passed = True
        
        for file_name, description in all_critical_files.items():
            file_path = work_dir / file_name
            if file_path.exists():
                size = file_path.stat().st_size
                print_success(f"{description} found: {file_name} ({size} bytes)")
            else:
                print_error(f"{description} NOT FOUND: {file_name}")
                missing_files.append(file_name)
                verification_passed = False
        
        # Provide specific troubleshooting for missing files
        if missing_files:
            print_error(f"Missing {len(missing_files)} critical files: {', '.join(missing_files)}")
            
            if "static_model.py" in missing_files:
                print_error("static_model.py is CRITICAL for fix_embedding task!")
                print_info("This should be copied from benchmarks/re_bench/ai_rd_fix_embedding/assets/")
                print_info("Check that task family start() method ran successfully")
            
            if "score.py" in missing_files:
                print_error("score.py is CRITICAL for task evaluation!")
                print_info("This should be copied from the benchmark assets directory")
            
            if "simple_return.py" in missing_files:
                print_error("simple_return.py creation failed!")
                print_info("This indicates a workspace setup issue")
            
            print_info("Troubleshooting steps:")
            print_info("1. Check that source assets exist in benchmark directory")
            print_info("2. Verify task family start() method executed without errors")
            print_info("3. Check file copying process in _copy_task_assets()")
        else:
            print_success("All critical files verified successfully!")
        
        return verification_passed
    
    async def _copy_task_assets(self, source_dir: Path, work_dir: Path) -> List[str]:
        """
        Copy relevant task assets from source directory to working directory.
        Enhanced with better logging and critical file detection.
        
        Args:
            source_dir: Source directory to scan for assets
            work_dir: Target working directory
            
        Returns:
            List of copied items
        """
        loop = asyncio.get_event_loop()
        copied_items = []

        # Define file extensions and patterns that are likely task assets
        asset_extensions = {'.pdf', '.html', '.txt', '.json', '.csv', '.xml', '.md', 
                          '.xlsx', '.xls', '.tsv', '.parquet', '.feather', '.h5', 
                          '.hdf5', '.pkl', '.pickle', '.py'}  # Added .py for scripts
        asset_patterns = ['assets', 'data', 'papers', 'documents', 'solution']
        
        # Critical files that should always be copied if present
        critical_files = {
            'score.py', 'static_model.py', 'save_models.py', 'save_models_robust.py',
            'prepare_data.py', 'torch_rule_enforcer.py', 'heldout_setup.py',
            'rust_codecontests_utils.py'
        }
        
        logger.info(f"Scanning current directory {source_dir} for data files...")

        for item in source_dir.iterdir():
            should_copy = False
            copy_reason = ""
            
            # Skip system directories and code directories
            skip_dirs = {
                'agent', 'benchmarks', 'venv', '.git', '__pycache__', 
                '.pytest_cache', 'node_modules', '.DS_Store', 'config'
            }
            skip_files = {
                'run_coder.py', 'run_batch_job.py', 'requirements.txt', 
                'Dockerfile', '.gitignore', '.env', 'check_worker_files.py',
                'check_source_assets.py', 'debug_workspace_copy.py'
            }
            
            if item.name in skip_dirs or item.name in skip_files:
                continue
            if item.name.startswith('worker_') or item.name.startswith('workdir_'):
                continue
            
            # Copy files with asset-like extensions
            if item.is_file():
                if item.name in critical_files:
                    should_copy = True
                    copy_reason = "critical task file"
                    print_info(f"Found critical file: {item.name}")
                elif item.suffix.lower() in asset_extensions:
                    should_copy = True
                    copy_reason = f"file extension '{item.suffix}'"
                    logger.info(f"Found data file to copy: {item.name} (extension: {item.suffix})")
                # Also copy files that look like they contain research content
                elif any(keyword in item.name.lower() for keyword in ['paper', 'research', 'wiki', 'temporal', 'ppo', 'trpo']):
                    should_copy = True
                    copy_reason = "research content"
            
            # Copy directories that look like asset directories
            elif item.is_dir():
                if any(pattern in item.name.lower() for pattern in asset_patterns):
                    should_copy = True
                    copy_reason = "asset directory"
            
            if should_copy:
                item_dest = work_dir / item.name
                try:
                    if item.is_file():
                        await loop.run_in_executor(
                            None, 
                            lambda src=item, dest=item_dest: shutil.copy2(src, dest)
                        )
                        copied_items.append(f"file: {item.name}")
                        
                        # Verify critical files were copied successfully
                        if item.name in critical_files:
                            if item_dest.exists():
                                size = item_dest.stat().st_size
                                print_success(f"Critical file copied: {item.name} ({size} bytes)")
                            else:
                                print_error(f"Critical file copy FAILED: {item.name}")
                                
                    elif item.is_dir():
                        await loop.run_in_executor(
                            None, 
                            lambda src=item, dest=item_dest: shutil.copytree(src, dest, dirs_exist_ok=True)
                        )
                        copied_items.append(f"dir: {item.name}")
                        
                except Exception as e:
                    print_error(f"Failed to copy {item.name}: {e}")
                    logger.warning(f"Failed to copy {item}: {e}")
        
        return copied_items
    
    async def _create_home_symlink(self, work_dir: Path) -> None:
        """
        Create symlink in home directory pointing to work directory.
        
        Args:
            work_dir: Working directory path
        """
        loop = asyncio.get_event_loop()
        home_dir = Path.home()
        symlink_path = home_dir / f"workdir_{self.run_id}"
        
        # Remove existing symlink if it exists
        def create_symlink():
            if symlink_path.exists() or symlink_path.is_symlink():
                try:
                    os.remove(symlink_path)
                except IsADirectoryError:
                    os.rmdir(symlink_path)
            os.symlink(work_dir.absolute(), symlink_path)
        
        await loop.run_in_executor(None, create_symlink)
        logger.info(f"Created symlink: {symlink_path} -> {work_dir.absolute()}", 
                   extra={'custom_tags': {'phase': 'agent'}})
    
    async def _handle_data_directory(self, work_dir: Path) -> None:
        """
        Handle data directory by creating symlinks to data files.
        
        Args:
            work_dir: Working directory path
        """
        loop = asyncio.get_event_loop()
        
        # Handle data directory if provided
        data_directory = None
        if self.storage_config and 'data_directory' in self.storage_config:
            data_directory = self.storage_config['data_directory']
        
        # Also check environment variable (used in Kubernetes)
        if not data_directory and os.environ.get('AGENT_DATA_DIR'):
            data_directory = os.environ.get('AGENT_DATA_DIR')
            logger.info(f"Using data directory from AGENT_DATA_DIR env var: {data_directory}")
            
        if data_directory and os.path.exists(data_directory):
            logger.info(f"Symlinking data files from: {data_directory}")
            data_path = Path(data_directory)
            
            # Create symlinks for each data file
            symlinked_files = []
            for data_file in data_path.iterdir():
                if data_file.is_file():
                    # Create symlink in working directory
                    link_path = work_dir / data_file.name
                    try:
                        # Remove existing file/link if it exists
                        if link_path.exists() or link_path.is_symlink():
                            link_path.unlink()
                        
                        # Create symlink
                        await loop.run_in_executor(
                            None,
                            lambda df=data_file, lp=link_path: os.symlink(df.absolute(), lp)
                        )
                        symlinked_files.append(data_file.name)
                        logger.info(f"Created symlink: {link_path} -> {data_file}")
                    except Exception as e:
                        logger.warning(f"Failed to symlink {data_file.name}: {e}")
                        # Fall back to copying if symlink fails
                        try:
                            await loop.run_in_executor(
                                None,
                                lambda df=data_file, lp=link_path: shutil.copy2(df, lp)
                            )
                            symlinked_files.append(f"{data_file.name} (copied)")
                            logger.info(f"Copied file instead: {data_file.name}")
                        except Exception as e2:
                            logger.error(f"Failed to copy {data_file.name}: {e2}")
            
            if symlinked_files:
                logger.info(f"Made {len(symlinked_files)} data files available in working directory: {', '.join(symlinked_files)}")
                logger.info(f"Agent can now use: pd.read_csv('train.csv') directly")
        else:
            logger.info("No data_directory in storage_config")