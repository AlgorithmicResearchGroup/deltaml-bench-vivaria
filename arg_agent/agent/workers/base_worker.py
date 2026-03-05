import os
import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Set
from concurrent.futures import ThreadPoolExecutor
import uuid
from collections import defaultdict

from dotenv import load_dotenv
from agent.utils.general import logger, rich_logger, console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich import box

from agent.memory_management.memory_async import AsyncAgentMemory
from agent.tools.tool_registry_async import AsyncToolManager
from agent.core.prompts import (
    get_worker_system_prompt, 
    get_draft_prompt, 
    get_debug_prompt,
    get_improve_prompt,
    get_review_prompt,
    get_review_function_spec,
    get_tool_enhanced_draft_prompt
)
# Model imports moved to LLM interface
from agent.core.solution_tree import SolutionJournal, SolutionNode
from agent.search.policy import SearchPolicy
from agent.search.beam_search import BeamSearchWithDiversity

# Import new execution module
from agent.execution import CodeExecutor, ExecutionStatus

# Import LLM interface
from agent.llm import LLMInterface

# Import memory management
from agent.memory_management import MemoryManager, ContextBuilder

# Import tool execution
from agent.tools.execution import ToolExecutor

# Import recording
from agent.recording import RecordingManager
from agent.utils.monitoring.auto_monitor import AutoMonitor

# Import workspace
from agent.workspace import WorkspaceManager

# Import error analysis
from agent.error_analysis import ErrorAnalyzer

# Import reflection
from agent.reflection import ReflectionManager

# Import node management
from agent.node_management import NodeManager

# Import storage
from agent.storage.storage_factory import StorageFactory
from agent.storage.storage_interface import CloudStorageInterface

# Import extracted modules
from agent.processing.parallel_explorer import ParallelNodeExplorer
from agent.utils.dashboard.visualization import SolutionTreeVisualizer
from agent.utils.worker_utils import convert_node_to_dict_for_prompt, log_with_panel, log_code_snippet
from agent.utils.display.live_tree_display import LiveTreeDisplay
from agent.utils.display.simple_persistent_display import SimplePersistentDisplay
from agent.utils.dashboard.compact_tree_status import CompactTreeStatus
from agent.utils.monitoring.success_tracker import SuccessTracker
from agent.utils.storage.tree_state_writer import TreeStateWriter
from agent.core.task_context import generate_working_directory_context

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
    print(f"{Colors.RED}{Colors.BOLD}❌ WORKER ERROR: {message}{Colors.END}")

def print_success(message: str):
    """Print success message in green"""
    print(f"{Colors.GREEN}{Colors.BOLD}✅ WORKER SUCCESS: {message}{Colors.END}")

def print_warning(message: str):
    """Print warning message in yellow"""
    print(f"{Colors.YELLOW}{Colors.BOLD}⚠️  WORKER WARNING: {message}{Colors.END}")

def print_info(message: str):
    """Print info message in blue"""
    print(f"{Colors.BLUE}{Colors.BOLD}ℹ️  WORKER INFO: {message}{Colors.END}")

load_dotenv(override=False)

# Utility functions are now imported from worker_utils module
# Duplicate classes removed - now imported from their respective modules
class AsyncWorker:
    def __init__(
        self,
        user_id: int,
        run_id: str,
        user_query: str,
        plan: str,
        worker_number: int,
        email: str,
        provider: str,
        success_metric: str = "accuracy",
        success_threshold: Optional[float] = None,
        auto_complete: bool = False,
        max_iterations: int = 100,
        search_policy_config: Optional[Dict[str, Any]] = None,
        enable_parallel_exploration: bool = True,
        repeat_error_threshold: int = 3,
        storage_config: Optional[Dict[str, Any]] = None,
        model_name: Optional[str] = None,
        task_name: Optional[str] = None,
        max_concurrent_nodes: int = 3,
        wandb_project: str = "ml-agent",
        enable_tool_use: bool = False,
        time_limit: int = 1800,
    ) -> None:
        self.user_id = user_id
        self.run_id = run_id
        self.agent_model = provider
        self.model_name = model_name  # Specific model version
        self.user_query = user_query
        self.initial_plan = plan
        self.wandb_project = wandb_project
        self.worker_number = worker_number
        self.task_number = 0
        # Token counting now handled by LLM interface
        self.run_number = run_id
        self.start_time = datetime.now()
        self.system_prompt = get_worker_system_prompt(self.run_id)
        self.email = email
        self.repeat_error_threshold = repeat_error_threshold

        # 🔥 SUCCESS CRITERIA
        self.success_metric = success_metric.lower()
        self.success_threshold = success_threshold
        logger.info(f"Worker initialized with success_metric={self.success_metric}, threshold={self.success_threshold}")
        self.auto_complete = auto_complete
        self.task_name = task_name
        
        # Parallel exploration configuration
        self.enable_parallel_exploration = enable_parallel_exploration
        self.max_concurrent_nodes = max_concurrent_nodes
        
        # Tool usage mode
        self.enable_tool_use = enable_tool_use

        # Async components
        self.memory: Optional[AsyncAgentMemory] = None
        self.llm: Optional[LLMInterface] = None
        self.tool_manager: Optional[AsyncToolManager] = None
        self.memory_manager: Optional[MemoryManager] = None
        self.context_builder: Optional[ContextBuilder] = None
        self.tool_executor: Optional[ToolExecutor] = None
        self.recording_manager: Optional[RecordingManager] = None
        self.workspace_manager: Optional[WorkspaceManager] = None
        self.error_analyzer = ErrorAnalyzer()
        self.reflection_manager: Optional[ReflectionManager] = None
        self.node_manager: Optional[NodeManager] = None
        self.executor = ThreadPoolExecutor(max_workers=4)

        # Performance monitoring
        self.performance_metrics = {
            "total_execution_time": 0,
            "memory_operations": 0,
            "model_calls": 0,
            "tool_executions": 0,
            "parallel_operations": 0,
            "nodes_created": 0,
        }

        
        # Task completion tracking
        self.task_completed = False

        # Solution Tree Search components
        self.journal = SolutionJournal(run_id=self.run_id)
        _default_search_policy_config = {
            "num_drafts": 2,
            "debug_prob": 0.6,  # Increased from 0.25
            "max_debug_depth": 5,  # Increased from 3
            "min_debug_attempts": 2,  # New parameter
            "target_metric_name": self.success_metric,
            "target_threshold": self.success_threshold,
            "target_metric_lower_is_better": False,
            "search_strategy": "tree_search",  # Default search strategy
        }
        self.search_policy = SearchPolicy(search_policy_config or _default_search_policy_config)
        
        # Initialize beam search if selected
        self.beam_search = None
        if self.search_policy.search_strategy == "beam_search":
            self.beam_search = BeamSearchWithDiversity(
                beam_width=self.search_policy.num_drafts,  # Use num_drafts as beam width
                diversity_threshold=0.7
            )
            console.print(Panel(
                f"🔍 Using Beam Search with Diversity\n"
                f"Beam Width: {self.search_policy.num_drafts}\n"
                f"Diversity Threshold: 0.7",
                title="Search Strategy",
                style="blue"
            ))
            
        self.work_dir: Optional[Path] = None
        
        # Search limits
        self.time_limit = time_limit  # Time limit in seconds (configurable from YAML)
        self.max_nodes = max_iterations  # Maximum nodes to explore
        # self.start_time already initialized as datetime.now() above

        # Initialize the CodeExecutor
        self.code_executor = None  # Will be initialized with work_dir
        
        # Initialize tree visualizer (will be set after journal is created)
        self.tree_visualizer = None
        
        
        # Initialize tree display
        self.tree_display = None
        self.persistent_display = None
        self.tree_status_bar = None
        self.success_tracker = None
        self.tree_state_writer = None
        
        # Initialize storage client (will be configured in initialize_async_components)
        self.storage_client: Optional[CloudStorageInterface] = None
        self.storage_config = storage_config or {}  # Pass storage config from caller
        
        
        # Track current node for tool access
        self.current_node = None

    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize_async_components()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.cleanup_async_components()

    async def initialize_async_components(self):
        """Initialize all async components"""
        self.memory = AsyncAgentMemory()
        
        # Initialize LLM interface
        self.llm = LLMInterface(
            model_provider=self.agent_model,
            model_name=self.model_name,
            system_prompt=self.system_prompt,
            run_id=self.run_id,
            success_metric=self.success_metric,
            success_threshold=self.success_threshold,
            enable_tool_use=self.enable_tool_use
        )
        
        logger.info(f"Initialized LLM interface with provider: {self.agent_model}, model: {self.model_name or 'default'}")
        
        self.tool_manager = AsyncToolManager(max_concurrent_tools=3) # Retain for other potential tools
        
        # Initialize memory manager and context builder
        self.memory_manager = MemoryManager(self.memory, self.run_id, self.user_id)
        self.context_builder = ContextBuilder(self.journal, self.user_query)
        
        # Initialize tool executor
        self.tool_executor = ToolExecutor(self, self.memory_manager)
        
        # Initialize storage client if configured
        if self.storage_config and self.storage_config.get('enabled', False):
            try:
                storage_provider = self.storage_config.get('provider', 'gcs')
                self.storage_client = StorageFactory.create(storage_provider, self.storage_config)
                await self.storage_client.initialize()
                logger.info(f"Initialized {storage_provider} storage client")
            except Exception as e:
                logger.error(f"Failed to initialize storage client: {e}")
                self.storage_client = None
        
        # Initialize workspace manager and create working directory
        self.workspace_manager = WorkspaceManager(
            run_id=self.run_id,
            worker_number=self.worker_number,
            storage_config=self.storage_config
        )
        logger.info(f"Creating workspace for task_family: {self.storage_config.get('task_family', 'None')}")
        self.work_dir = await self.workspace_manager.create_workspace()
        os.chdir(self.work_dir)
        logger.info(f"Changed working directory to: {self.work_dir.resolve()}", 
                   extra={'custom_tags': {'phase': 'agent'}})
        
        # FINAL WORKER-LEVEL FILE VERIFICATION
        # Double-check that all critical files are accessible from the agent's perspective
        self._perform_final_file_verification()
        
        # Initialize CodeExecutor with work directory
        self.code_executor = CodeExecutor(
            work_dir=self.work_dir,
            cache_ttl=3600,  # 1 hour cache
            enable_caching=True,
            enable_gpu_allocation=self.enable_parallel_exploration
        )
        
        # Initialize recording manager
        self.recording_manager = RecordingManager(
            working_dir=self.work_dir,
            config=self.storage_config,
            storage_client=self.storage_client,
            auto_monitor=AutoMonitor(),  # Create AutoMonitor instance here
            run_id=self.run_id,
            task_name=self.task_name,
            user_query=self.user_query,
            success_metric=self.success_metric,
            success_threshold=self.success_threshold
        )
        logger.info("Initialized recording manager")
        
        # Initialize reflection manager
        self.reflection_manager = ReflectionManager(self.llm)
        logger.info("Initialized reflection manager")
        
        # Initialize node manager
        self.node_manager = NodeManager(self.journal, self.reflection_manager)
        logger.info("Initialized node manager")
        
        # Initialize DVC for data version control
        try:
            # Initialize DVC without git (simpler for temporary workspaces)
            init_result = await self._run_command_async("dvc init --no-scm -f")
            if init_result['returncode'] == 0:
                # Configure DVC cache to be local
                await self._run_command_async(f"dvc cache dir {self.work_dir}/.dvc-cache")
                logger.info("✅ Initialized DVC for data version control")
            else:
                logger.warning(f"DVC initialization failed: {init_result['stderr']}")
        except Exception as e:
            logger.warning(f"Could not initialize DVC: {e}")
        
        # Initialize success tracker with work directory
        self.success_tracker = SuccessTracker(self.work_dir)
        
        # Enhance user_query with working directory context
        # This helps the agent understand its environment
        original_query = self.user_query
        self.original_user_query = original_query  # Keep original for reference
        

    async def cleanup_async_components(self):
        """Cleanup all async components"""
        if self.memory:
            await self.memory.close()
        if self.llm:
            await self.llm.close()
        if self.tool_manager:
            await self.tool_manager.close()
        if self.storage_client:
            await self.storage_client.close()
        if self.executor:
            self.executor.shutdown(wait=False)
        
        # Stop database state writer
        try:
            from agent.utils.storage.db_state_writer import stop_db_state_writer
            stop_db_state_writer()
        except Exception:
            pass
        
        # Stop MinIO uploader
        try:
            from agent.utils.storage.minio_uploader import stop_minio_uploader
            stop_minio_uploader()
        except Exception:
            pass

    def _display_tree(self):
        """Display the tree using the tree display"""
        if self.tree_display:
            console.print("\n")  # Add spacing
            console.print(self.tree_display.create_tree_visual())
            console.print("\n")  # Add spacing after
            
    def _show_tree_status(self):
        """Show the tree status bar"""
        if self.tree_status_bar:
            self.tree_status_bar.display(console)
            
        # Also show success tracker panel if we have successful nodes
        if self.success_tracker and self.success_tracker.successes:
            console.print("")  # Add spacing
            self.success_tracker.display(console, show_last=3)
    
    def _get_best_score(self) -> float:
        """Get the best score achieved so far"""
        best_node = self.journal.get_best_node(self.success_metric)
        if best_node and best_node.metric_value is not None:
            return best_node.metric_value
        return 0.0
    
    def _perform_final_file_verification(self):
        """
        Perform final verification of critical files from the agent's perspective.
        This is the last check before agent execution begins.
        """
        print_info("Performing final file verification in agent working directory")
        
        current_dir = Path.cwd()
        print_info(f"Agent working directory: {current_dir}")
        
        # Define critical files based on task type
        critical_files = {
            "simple_return.py": "Simple return helper function",
            "scratchpad.txt": "Agent scratchpad file"
        }
        
        # Try to detect task type and add task-specific files
        task_specific_files = self._detect_task_specific_files(current_dir)
        critical_files.update(task_specific_files)
        
        missing_files = []
        verification_errors = []
        
        for file_name, description in critical_files.items():
            file_path = current_dir / file_name
            
            if file_path.exists():
                try:
                    # Check if file is readable
                    size = file_path.stat().st_size
                    if size == 0:
                        print_warning(f"{description} is empty: {file_name}")
                    else:
                        print_success(f"{description} verified: {file_name} ({size} bytes)")
                        
                    # For Python files, try a basic import test
                    if file_name.endswith('.py') and file_name != 'simple_return.py':
                        try:
                            with open(file_path, 'r') as f:
                                content = f.read()
                                if 'import' in content or 'def ' in content or 'class ' in content:
                                    print_success(f"Python file {file_name} appears valid")
                                else:
                                    print_warning(f"Python file {file_name} may be incomplete")
                        except Exception as e:
                            print_warning(f"Could not validate Python file {file_name}: {e}")
                            
                except Exception as e:
                    print_error(f"Error accessing {file_name}: {e}")
                    verification_errors.append(f"{file_name}: {e}")
            else:
                print_error(f"{description} NOT FOUND: {file_name}")
                missing_files.append(file_name)
        
        # Report final verification status
        if missing_files or verification_errors:
            print_error("AGENT FILE VERIFICATION FAILED!")
            
            if missing_files:
                print_error(f"Missing files: {', '.join(missing_files)}")
                
            if verification_errors:
                print_error(f"File access errors: {len(verification_errors)}")
                
            # Provide specific guidance for common missing files
            if "static_model.py" in missing_files:
                print_error("CRITICAL: static_model.py missing - this WILL cause ModuleNotFoundError!")
                print_info("Task execution will likely fail with 'No module named static_model' error")
                
            if "score.py" in missing_files:
                print_error("CRITICAL: score.py missing - task evaluation will fail!")
                
            print_info("Agent will proceed but task execution may fail due to missing files")
            
        else:
            print_success("All critical files verified successfully - agent ready to proceed!")
            
        # Log verification results
        logger.info(f"File verification complete. Missing: {len(missing_files)}, Errors: {len(verification_errors)}")
        if missing_files:
            logger.warning(f"Missing critical files: {missing_files}")
    
    def _detect_task_specific_files(self, work_dir: Path) -> dict:
        """
        Detect task-specific files that should be present based on task context.
        
        Args:
            work_dir: Working directory to check
            
        Returns:
            Dictionary of task-specific files to check
        """
        task_files = {}
        
        # Check task name or user query for clues
        task_indicators = {
            "fix_embedding": {"score.py": "Task evaluation script", "static_model.py": "Static model definition"},
            "triton_cumsum": {"score.py": "Task evaluation script"},
            "optimize_llm": {"score.py": "Task evaluation script", "env.sh": "Environment setup script"},
            "restricted_mlm": {"score.py": "Task evaluation script", "prepare_data.py": "Data preparation script"},
            "rust_codecontests": {"score.py": "Task evaluation script", "rust_codecontests_utils.py": "Rust utilities"},
            "nanogpt_chat": {"score.py": "Task evaluation script", "heldout_setup.py": "Heldout data setup"},
            "small_scaling": {"score.py": "Task evaluation script"},
            "sanity_check": {"score.py": "Task evaluation script"}
        }
        
        # Check task name
        if self.task_name:
            for indicator, files in task_indicators.items():
                if indicator in self.task_name.lower():
                    task_files.update(files)
                    print_info(f"Detected task type: {indicator}")
                    break
        
        # Check user query for task indicators
        if not task_files and self.user_query:
            query_lower = self.user_query.lower()
            for indicator, files in task_indicators.items():
                if indicator in query_lower:
                    task_files.update(files)
                    print_info(f"Detected task type from query: {indicator}")
                    break
        
        # Check for files that actually exist in the directory
        if not task_files:
            for file_path in work_dir.iterdir():
                if file_path.is_file():
                    if file_path.name == "static_model.py":
                        task_files["static_model.py"] = "Static model definition"
                        task_files["score.py"] = "Task evaluation script"
                        print_info("Detected fix_embedding task from static_model.py presence")
                    elif file_path.name == "score.py" and "score.py" not in task_files:
                        task_files["score.py"] = "Task evaluation script"
                        print_info("Detected RE-bench task from score.py presence")
        
        return task_files
    
    async def _run_command_async(self, command: str) -> Dict[str, Any]:
        """Helper to run shell commands asynchronously"""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            return {
                'returncode': process.returncode,
                'stdout': stdout.decode('utf-8') if stdout else '',
                'stderr': stderr.decode('utf-8') if stderr else ''
            }
        except Exception as e:
            return {
                'returncode': -1,
                'stdout': '',
                'stderr': str(e)
            }

    async def _generate_plan_and_code_async(
        self, prompt: str, node_stage: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Calls the LLM to generate a plan and code.
        """
        # If tool use is enabled, use tool-based generation
        if self.enable_tool_use:
            return await self._generate_solution_with_tools_async(prompt)
        
        self.performance_metrics["model_calls"] += 1
        
        gen_panel = Panel.fit(
            f"🧠 Calling LLM for {node_stage.upper()} generation...",
            style="blue",
            border_style="blue"
        )
        console.print(gen_panel)
        
        # Parse the node from context if needed
        node = self.current_node if hasattr(self, 'current_node') else None
        
        # Call LLM interface
        response = await self.llm.generate_solution(
            user_query=self.user_query,
            stage=node_stage,
            node=node,
            previous_attempts=prompt  # The prompt contains all context
        )
        
        # Handle errors
        if response.error:
            logger.error(f"❌ Generation failed: {response.error}")
            error_panel = Panel(f"Error: {response.error}", title="❌ Generation Failed", style="red")
            console.print(error_panel)
            return None, None
        
        # Update token count
        # Token counting now handled by LLM interface
        
        token_text = Text()
        token_text.append("🔢 TOKENS: ", style="dim")
        token_text.append(f"{response.total_tokens}", style="bold white")
        token_text.append(f" (total: {self.llm.get_total_tokens()})", style="dim")
        console.print(token_text)
        
        # Check results
        if response.plan and response.code:
            success_text = Text()
            success_text.append("✅ GENERATION SUCCESS ", style="bold green")
            success_text.append(f"({node_stage})", style="green")
            console.print(success_text)
            return response.plan, response.code
        else:
            logger.error("❌ LLM did not return both plan and code")
            return None, None

    async def _generate_solution_with_tools_async(self, prompt: str, max_iterations: int = 10) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate a solution using tools, then return plan and code for the existing pipeline.
        This allows tool use while maintaining all the existing validation and retry logic.
        """
        self.performance_metrics["model_calls"] += 1
        
        if self.tool_executor:
            return await self.tool_executor.generate_solution_with_tools(prompt, max_iterations)
        else:
            logger.error("Tool executor not initialized")
            return None, None



    async def _execute_generated_code_async(self, node: SolutionNode) -> None:
        """
        Executes the code in a SolutionNode using the modular CodeExecutor.
        """
        if not node.code:
            warning_panel = Panel(
                f"Node {node.id[:8]}... has no code to execute",
                title="⚠️ No Code",
                style="yellow"
            )
            console.print(warning_panel)
            
            node.is_buggy = True
            node.exec_error = "No code provided"
            node.executed_at = time.time()
            self.journal.add_node(node)
            self.performance_metrics["nodes_created"] = len(self.journal.nodes)
            return

        self.performance_metrics["tool_executions"] += 1

        # Execute code using the modular executor
        exec_result = await self.code_executor.execute(
            code=node.code,
            node_id=node.id,
            stage=node.stage,
            gpu_device=node.metadata.get('allocated_gpu') if hasattr(node, 'metadata') else None
        )

        # Update node with execution results
        node.exec_stdout = exec_result.stdout
        node.exec_stderr = exec_result.stderr
        node.exec_time_seconds = exec_result.execution_time
        node.executed_at = exec_result.timestamp.timestamp()
        node.script_path = exec_result.script_path
        
        # Set node directory based on script path
        if node.script_path:
            node.node_directory = str(Path(node.script_path).parent)
        
        if exec_result.status == ExecutionStatus.SUCCESS:
            node.is_buggy = False
        else:
            node.is_buggy = True
            node.exec_error = exec_result.error or exec_result.stderr or "Execution failed"
            
        # Save to cloud storage if configured
        if self.recording_manager:
            asyncio.create_task(self.recording_manager.save_node_to_storage(node))
        
        # Auto-monitor GPU/CPU and track experiments
        if not node.is_buggy and node.exec_stdout and self.recording_manager:
            asyncio.create_task(self.recording_manager.run_auto_monitoring(node))

        # After execution, add error classification
        if node.is_buggy and node.exec_error:
            error_type = self.error_analyzer.classify_error_type(node)
            
            # Store error classification in node metadata
            self.error_analyzer.annotate_node_with_error_metadata(node)
            
            # Show error classification
            error_class_panel = Panel(
                f"🔍 Error Classification: {error_type}\n"
                f"Error: {node.exec_error}...",
                title="🐛 Error Analysis",
                style="red"
            )
            console.print(error_class_panel)

    async def _review_execution_async(self, node: SolutionNode) -> None:
        """
        Calls an LLM to review the execution results of a node.
        """
        if not node.has_executed:
            logger.warning(f"⚠️ Node {node.id[:8]}... cannot be reviewed - not executed")
            return

        # Show review start
        review_panel = Panel.fit(
            f"📊 Reviewing execution for node {node.id[:8]}...",
            style="cyan",
            border_style="cyan"
        )
        console.print(review_panel)
        
        self.performance_metrics["model_calls"] += 1

        # Vivaria Integration: Skip custom completion detection
        # The agent now uses Vivaria's native hooks.submit() instead of TASK_COMPLETE patterns
        # Continue with standard LLM review
        validation_feedback = ""
        stdout_text = node.exec_stdout if node.exec_stdout else ""
        
        review_prompt_text = get_review_prompt(
            task_desc=self.user_query,
            code=node.code,
            stdout=stdout_text + validation_feedback,  # Append validation feedback to stdout
            stderr=node.exec_stderr if node.exec_stderr else "",
            error=node.exec_error if node.exec_error else ""
        )
        node.review_prompt = review_prompt_text
        
        review_func_spec = get_review_function_spec(
            metric_name=self.success_metric,
            metric_description=f"The primary metric for this task is {self.success_metric}."
        )

        try:
            # Use LLM interface for review
            review_result = await self.llm.review_execution(
                node=node,
                user_query=self.user_query
            )
            
            # Token counting is already handled by LLM interface in review_execution
            
            if review_result and not review_result.get('error'):
                node.analysis = review_result.get("summary", "Review summary not provided.")
                
                # Check if using new format or old format
                if "execution_status" in review_result:
                    # Handle new review format
                    execution_status = review_result.get("execution_status", "error")
                    is_correct = review_result.get("is_correct")
                    
                    # Determine if code is buggy based on execution status
                    if execution_status == "error":
                        node.is_buggy = True
                    elif execution_status == "success":
                        # Only mark as buggy if we can determine it's incorrect
                        node.is_buggy = (is_correct is False) if is_correct is not None else False
                    else:  # partial_success
                        node.is_buggy = True
                else:
                    # Backward compatibility with old format
                    node.is_buggy = review_result.get("is_buggy", node.is_buggy if node.is_buggy is not None else (node.exec_error is not None))
                
                # Handle metric value
                metric_val = review_result.get("metric_value")
                if metric_val is not None:
                    try:
                        node.metric_value = float(metric_val)
                        node.metric_name = self.success_metric
                    except ValueError:
                        logger.warning(f"⚠️ Could not parse metric value: {metric_val}")
                        # Don't mark as buggy just because metric parsing failed
                
                # Add execution status to analysis for clarity (only for new format)
                if "execution_status" in review_result:
                    execution_status = review_result.get("execution_status", "error")
                    is_correct = review_result.get("is_correct")
                    if execution_status != "success" or is_correct is False:
                        status_desc = f" [Status: {execution_status}"
                        if is_correct is not None:
                            status_desc += f", Correct: {is_correct}"
                        status_desc += "]"
                        node.analysis += status_desc

                # Show review completion
                review_result_text = Text()
                review_result_text.append("📊 REVIEW COMPLETE ", style="bold cyan")
                status = "🐛 BUGGY" if node.is_buggy else "✅ CLEAN"
                review_result_text.append(status, style="red" if node.is_buggy else "green")
                console.print(review_result_text)
                
                # Track successful nodes (but not if validation failed)
                if not node.is_buggy and node.metric_value is not None and self.success_tracker:
                    # Check if validation failed
                    if getattr(node, 'validation_failed', False):
                        # Show validation failure notification
                        validation_fail = Text()
                        validation_fail.append("❌ VALIDATION FAILED: ", style="bold red")
                        validation_fail.append(f"Score {node.metric_value:.4f} rejected - ", style="red")
                        validation_fail.append(getattr(node, 'validation_reason', 'Validation failed'), style="yellow")
                        console.print(validation_fail)
                        # Mark as buggy since validation failed
                        node.is_buggy = True
                        node.analysis = f"Validation failed: {getattr(node, 'validation_reason', 'Unknown reason')}. {node.analysis}"
                    else:
                        # Use the stored script path
                        script_path = getattr(node, 'script_path', None)
                        if script_path:
                            self.success_tracker.add_success(
                                node_id=node.id,
                                stage=node.stage,
                                script_path=script_path,
                                score=node.metric_value,
                                metric_name=self.success_metric,
                                plan=node.plan
                            )
                            
                            # Show success tracking notification
                            success_notify = Text()
                            success_notify.append("🏆 SUCCESS TRACKED: ", style="bold green")
                            success_notify.append(f"Score {node.metric_value:.4f} ", style="green")
                            success_notify.append(f"({Path(script_path).name})", style="yellow")
                            console.print(success_notify)
                        
                        # Update tree state for external monitor
                        if self.tree_state_writer:
                            self.tree_state_writer.write_state()
                
            else:
                logger.error(f"❌ Review LLM did not return expected function call")
                # Don't mark as buggy just because review failed - check execution results
                if node.is_buggy is None:
                    # If code executed without errors, assume it's not buggy
                    node.is_buggy = bool(node.exec_error)
                node.analysis = "Automated review failed - using execution status."
                
                # Show review failure but indicate execution status
                review_result_text = Text()
                review_result_text.append("📊 REVIEW FAILED ", style="bold yellow")
                if node.exec_error:
                    review_result_text.append("🐛 EXECUTION ERROR", style="red")
                else:
                    review_result_text.append("✅ EXECUTION SUCCESS", style="green")
                console.print(review_result_text)

        except Exception as e:
            error_panel = Panel(
                f"Review error: {str(e)}",
                title="❌ Review Failed",
                style="red"
            )
            console.print(error_panel)
            
            if node.is_buggy is None: 
                node.is_buggy = True
            node.analysis = f"Exception during review: {str(e)}"
        finally:
            node.reviewed_at = time.time()

    async def _process_single_node_async(self, node: SolutionNode) -> None:
        """
        Process a single node through the complete pipeline: generate -> execute -> review.
        """
        # Update current node in tree status bar
        if self.tree_status_bar:
            self.tree_status_bar.set_current_node(node.id)
            self._show_tree_status()
            
        # Update tree state for external monitor
        if self.tree_state_writer:
            self.tree_state_writer.set_current_node(node.id)
        
        # Node processing header
        node_panel = Panel.fit(
            f"🔧 Processing Node {node.id[:8]} (Stage: {node.stage})",
            style="bold cyan",
            border_style="cyan"
        )
        console.print(node_panel)
        
        # Step 1: Generate plan and code
        await self._generate_node_content_async(node)
        
        # Step 2: Execute the code  
        if node.code:
            await self._execute_generated_code_async(node)
        
        # Step 3: Review the execution
        if node.has_executed:
            await self._review_execution_async(node)
            
            # Save to persistent memory for cross-run learning
            if self.memory_manager:
                await self.memory_manager.save_node_attempt(node)
        
        # Update tree state after node completion
        if self.tree_state_writer:
            self.tree_state_writer.write_state()
        
        # Final node status
        status_icon = "✅" if not node.is_buggy else "🐛"
        status_text = "CLEAN" if not node.is_buggy else "BUGGY"
        metric_info = f" (Metric: {node.metric_value:.3f})" if node.metric_value is not None else ""
        
        completion_text = Text()
        completion_text.append(f"{status_icon} NODE COMPLETE: ", style="bold")
        completion_text.append(f"{status_text}", style="green" if not node.is_buggy else "red")
        completion_text.append(metric_info, style="dim")
        console.print(completion_text)
        
        # Show tree status after node completion
        if self.tree_status_bar:
            console.print()  # Add spacing
            self._show_tree_status()

    async def _generate_node_content_async(self, node: SolutionNode) -> None:
        """Generate content with enhanced error-specific memory context"""
        # Set current node for tool access
        self.current_node = node
        
        # Get memory context
        memory_context = await self.memory_manager.get_current_run_context() if self.memory_manager else ""
        
        # For debug nodes, get error-specific context
        if node.stage == "debug" and node.parent_id:
            parent_node = self.journal.get_node(node.parent_id)
            if parent_node and parent_node.is_buggy:
                error_type = self.error_analyzer.classify_error_type(parent_node)
                
                # Store error classification for later use
                self.error_analyzer.annotate_node_with_error_metadata(parent_node)
                
                # Get error-specific memory context
                if self.memory_manager:
                    error_context = await self.memory_manager.get_error_specific_context(
                        error_type=error_type,
                        error_text="",
                        current_error=parent_node.exec_error or parent_node.exec_stderr or "unknown error"
                    )
                    memory_context = error_context
        
        prompt_text = None # Initialize prompt_text

        # Determine prompt based on stage
        if node.stage == "implement":
            # Build context using ContextBuilder
            current_implement_context = self.context_builder.build_implement_context(
                memory_context=memory_context,
                node=node
            ) if self.context_builder else memory_context
            
            approach_hint = node.metadata.get("approach_hint", "")
            
            # Include any stored validation feedback from previous attempts
            if hasattr(self, '_validation_feedback') and self._validation_feedback:
                approach_hint = self._validation_feedback + "\n\n" + approach_hint if approach_hint else self._validation_feedback
                # Clear the feedback after using it
                self._validation_feedback = ""
            
            # Use tool-enhanced prompt if tool use is enabled
            if self.enable_tool_use:
                prompt_text = get_tool_enhanced_draft_prompt(
                    task_desc=self.user_query,
                    journal_summary=current_implement_context,
                    approach_hint=approach_hint,
                    wandb_project=self.wandb_project,
                    success_metric=self.success_metric,
                    success_threshold=self.success_threshold
                )
            else:
                prompt_text = get_draft_prompt(
                    task_desc=self.user_query,
                    journal_summary=current_implement_context, # Use potentially augmented context
                    approach_hint=approach_hint,
                    wandb_project=self.wandb_project,
                    success_metric=self.success_metric,
                    success_threshold=self.success_threshold
                )
        elif node.stage == "debug":
            parent_node = self.journal.get_node(node.parent_id) if node.parent_id else None
            if not parent_node:
                node.is_buggy = True
                node.exec_error = "No parent node found for debugging"
                logger.error(node.exec_error)
                return
                
            # Count debug attempts and classify error
            debug_attempts = self.node_manager.count_debug_children(parent_node) + 1
            max_attempts = 10
            
            error_type = "unknown"
            if hasattr(parent_node, 'error_metadata') and parent_node.error_metadata.get('error_type'):
                error_type = parent_node.error_metadata['error_type']
            elif parent_node.is_buggy:
                error_type = self.error_analyzer.classify_error_type(parent_node)
            
            # Build debug context using ContextBuilder
            debug_context = self.context_builder.build_debug_context(
                memory_context=memory_context,
                node=node,
                parent_node=parent_node,
                error_type=error_type,
                debug_attempts=debug_attempts,
                max_attempts=max_attempts,
                repeat_error_threshold=self.repeat_error_threshold
            ) if self.context_builder else memory_context
            
            prompt_text = get_debug_prompt(
                task_desc=self.user_query,
                buggy_node_dict=convert_node_to_dict_for_prompt(parent_node),
                journal_summary=debug_context,
            )
        elif node.stage == "improve":
            parent_node = self.journal.get_node(node.parent_id) if node.parent_id else None
            if not parent_node:
                node.is_buggy = True
                node.exec_error = "No parent node found for improvement"
                logger.error(node.exec_error)
                return
                
            # Build improve context using ContextBuilder
            improve_context = self.context_builder.build_improve_context(
                memory_context=memory_context,
                node=node,
                parent_node=parent_node
            ) if self.context_builder else memory_context
                    
            prompt_text = get_improve_prompt(
                task_desc=self.user_query,
                parent_node_dict=convert_node_to_dict_for_prompt(parent_node),
                journal_summary=improve_context,
                wandb_project=self.wandb_project,
            )
        
        if prompt_text is None: # Fallback if no prompt was generated for a known stage
            node.is_buggy = True
            node.exec_error = f"Failed to determine prompt for stage: {node.stage} with metadata: {node.metadata}"
            node.executed_at = time.time()  # Mark as executed to prevent reprocessing
            logger.error(node.exec_error)
            console.print(f"🐛 NODE COMPLETE: BUGGY (Prompt generation failed)")
            return
        
        node.generation_prompt = prompt_text
        
        # Generate content
        plan, code = await self._generate_plan_and_code_async(prompt_text, node.stage)
        
        if not plan or not code:
            node.is_buggy = True
            node.exec_error = "Failed to generate plan/code from LLM"
            node.executed_at = time.time()  # Mark as executed to prevent reprocessing
            console.print(f"🐛 NODE COMPLETE: BUGGY (Generation failed)")
            return
        
        node.plan = plan
        node.code = code
        
        # Show generated content preview
        if plan:
            log_with_panel("📋 Plan Generated", plan[:150] + ("..." if len(plan) > 150 else ""), "blue")
        
        if code:
            log_code_snippet(code, f"🐍 Code Generated ({node.stage})")


    async def process_subtasks_async(self) -> Dict[str, Any]:
        """Main tree search logic with parallel exploration and enhanced debugging"""
        
        # Show mode information
        if self.enable_tool_use:
            console.rule("🔧 Starting Tool-Enabled Tree Search", style="bold cyan")
            console.print(Panel(
                "Agent will use tools to explore and generate solutions,\n"
                "then validate them through the standard tree search pipeline",
                title="Tool Mode Active",
                style="cyan"
            ))
        else:
            console.rule("🚀 Starting Parallel Tree Search", style="bold blue")
        
        # Show parallel configuration
        if self.enable_parallel_exploration:
            console.print(Panel(
                f"🔀 Parallel exploration enabled with up to {self.max_concurrent_nodes} concurrent nodes\n"
                f"💡 Tip: Use --max-concurrent-nodes to adjust based on your GPU count",
                title="Parallel Configuration",
                style="cyan"
            ))
        
        # Initialize parallel explorer
        parallel_explorer = ParallelNodeExplorer(self, max_concurrent_nodes=self.max_concurrent_nodes)
        
        # Initialize tree visualizer
        self.tree_visualizer = SolutionTreeVisualizer(self.journal, parallel_explorer)
        
        # Initialize tree display
        self.tree_display = LiveTreeDisplay(self.journal, self.success_tracker)
        self.persistent_display = SimplePersistentDisplay(self.journal)
        self.tree_status_bar = CompactTreeStatus(self.journal, self.success_tracker)
        
        # Initialize tree state writer for external monitor
        # Use custom journal path if provided via storage config
        journal_path = None
        if self.storage_config and 'journal_path' in self.storage_config and self.storage_config['journal_path']:
            journal_path = Path(self.storage_config['journal_path'])
            logger.info(f"Using custom journal path: {journal_path}")
        
        if journal_path:
            self.tree_state_writer = TreeStateWriter(self.journal, self.success_tracker, state_file=journal_path)
        else:
            self.tree_state_writer = TreeStateWriter(self.journal, self.success_tracker)
        
        # Start database state writer if web service URL is provided
        if os.environ.get('WEB_SERVICE_URL'):
            try:
                from agent.utils.storage.db_state_writer import start_db_state_writer
                start_db_state_writer(self.run_id)
                logger.info(f"Started database state writer for run {self.run_id}")
            except Exception as e:
                logger.warning(f"Failed to start database state writer: {e}")
        
        # Start MinIO file uploader if configured
        if os.environ.get('MINIO_ENDPOINT'):
            try:
                from agent.utils.storage.minio_uploader import start_minio_uploader
                start_minio_uploader(self.run_id)
                logger.info(f"Started MinIO file uploader for run {self.run_id}")
            except Exception as e:
                logger.warning(f"Failed to start MinIO uploader: {e}")
        
        # Show instructions for tree monitor
        console.print(Panel(
            "💡 To see live tree visualization, run this in a separate terminal:\n\n"
            "python tree_monitor.py\n\n"
            "Smart features:\n"
            "• Focuses on relevant parts of large trees\n"
            "• Shows current path and node (marked with ▶ NOW)\n"
            "• Tracks successful scripts with scores\n"
            "• Collapses irrelevant branches automatically",
            title="🌳 Smart Tree Monitor",
            style="blue"
        ))
        
        # Phase 1: Parallel initial exploration if configured
        if self.search_policy.num_drafts > 1 and self.enable_parallel_exploration:
            console.print(Panel(
                f"🔀 Parallel exploration ENABLED - Creating {self.search_policy.num_drafts} initial drafts",
                style="blue bold"
            ))
            # Create and explore multiple drafts in parallel
            initial_drafts = await parallel_explorer.explore_initial_drafts_parallel(
                num_drafts=self.search_policy.num_drafts
            )
            
            # Display tree after initial drafts
            self._display_tree()
        else:
            if self.search_policy.num_drafts > 1 and not self.enable_parallel_exploration:
                console.print(Panel(
                    f"🔄 Parallel exploration DISABLED - Creating {self.search_policy.num_drafts} drafts sequentially",
                    style="yellow"
                ))
                # Create multiple drafts but process sequentially
                for i in range(self.search_policy.num_drafts):
                    draft_node = SolutionNode(
                        id=str(uuid.uuid4()),
                        stage="implement",
                        parent_id=None,
                        created_at=time.time(),
                        metadata={"draft_number": i + 1, "approach_hint": f"Approach #{i+1}"}
                    )
                    self.journal.add_node(draft_node)
                    await self._process_single_node_async(draft_node)
            else:
                # Create single initial node
                initial_node = SolutionNode(
                    id=str(uuid.uuid4()),
                    stage="implement",
                    parent_id=None,
                    created_at=time.time()
                )
                
                self.journal.add_node(initial_node)
                await self._process_single_node_async(initial_node)
        
        # Display initial tree
        self._display_tree()
        
        # Search loop with enhanced debugging logic and loop prevention
        iteration = 0
        max_debug_attempts = 5  # Reduced from 10 to prevent endless loops
        repeated_errors = {}  # Track repeated error patterns
        consecutive_failures = 0  # Track consecutive failures
        
        while self.should_continue_search():
            iteration += 1
            
            # Check if task was completed via return_fn
            if self.task_completed:
                # But only stop if threshold is met (if a threshold is defined)
                if self.success_threshold is not None:
                    # Get best metric from successful nodes
                    successful_nodes = [n for n in self.journal.nodes.values() 
                                      if not n.is_buggy and n.metric_value is not None]
                    if successful_nodes:
                        # Check if this is a "lower is better" metric
                        lower_is_better_metrics = ['loss', 'log-loss', 'multi-class-log-loss', 'rmse', 'mae', 'mse', 'error']
                        is_lower_better = any(metric in self.success_metric.lower() for metric in lower_is_better_metrics)
                        
                        if is_lower_better:
                            best_metric = min(n.metric_value for n in successful_nodes)
                        else:
                            best_metric = max(n.metric_value for n in successful_nodes)
                            
                        # Handle metric format conversion
                        if best_metric > 1:
                            threshold_for_comparison = self.success_threshold * 100
                        else:
                            threshold_for_comparison = self.success_threshold
                        
                        # Check if threshold is met based on metric type
                        if is_lower_better:
                            threshold_met = best_metric <= threshold_for_comparison
                            comparison_str = f"{best_metric:.4f} > {threshold_for_comparison:.4f}" if not threshold_met else f"{best_metric:.4f} <= {threshold_for_comparison:.4f}"
                        else:
                            threshold_met = best_metric >= threshold_for_comparison
                            comparison_str = f"{best_metric:.4f} < {threshold_for_comparison:.4f}" if not threshold_met else f"{best_metric:.4f} >= {threshold_for_comparison:.4f}"
                        
                        if not threshold_met:
                            # Threshold not met - don't stop, continue improving
                            console.print(Panel(
                                f"⚠️ Task marked complete but threshold not met ({comparison_str})\n"
                                f"Continuing to improve the solution...",
                                style="yellow bold"
                            ))
                            # Reset task_completed flag to allow improvements
                            self.task_completed = False
                        else:
                            # Threshold met - can stop
                            console.print(Panel(
                                "✅ Task completed via return_fn and threshold met - stopping search",
                                style="green bold"
                            ))
                            break
                    else:
                        # No successful nodes yet, don't stop
                        console.print(Panel(
                            "⚠️ Task marked complete but no successful solutions found yet",
                            style="yellow bold"
                        ))
                        self.task_completed = False
                else:
                    # No threshold defined - stop when task completed
                    console.print(Panel(
                        "✅ Task completed via return_fn - stopping search",
                        style="green bold"
                    ))
                    break
            
            # Show tree status at start of iteration
            if self.tree_status_bar:
                self._show_tree_status()
            
            console.rule(f"🔄 Iteration {iteration}", style="cyan")
            
            # Check if we should explore in parallel
            if self.enable_parallel_exploration and self._should_explore_parallel(iteration):
                # Get diverse candidates for parallel processing
                candidates = parallel_explorer.get_parallel_candidates(
                    self.journal, 
                    max_candidates=min(3, self.max_nodes - len(self.journal.nodes))
                )
                
                if len(candidates) > 1:
                    console.print(Panel(
                        f"🔀 Exploring {len(candidates)} branches in parallel",
                        title="Parallel Exploration",
                        style="blue"
                    ))
                    
                    # Process candidates in parallel
                    await parallel_explorer.explore_nodes_parallel(candidates)
                    
                    # Update metrics
                    self.performance_metrics["parallel_operations"] += 1
                    self.performance_metrics["nodes_created"] = len(self.journal.nodes)
                    
                    # Display updated tree after parallel exploration
                    if self.tree_display:
                        console.print("\n")  # Add spacing
                        self._display_tree()
                    
                    # Reset failure counters after parallel exploration
                    consecutive_failures = 0
                    continue
                elif len(candidates) == 1:
                    # Process single candidate sequentially
                    await self._process_single_node_async(candidates[0])
                    
                    # Display updated tree
                    if self.tree_display:
                        console.print("\n")  # Add spacing
                        self._display_tree()
                    
                    continue
                # If no candidates, fall through to sequential processing
            
            # Fall back to sequential processing
            best_leaf = self.choose_best_leaf_node_for_expansion()
            if not best_leaf:
                break
            
            # CRITICAL: Pattern detection and loop prevention
            if best_leaf.has_executed and best_leaf.is_buggy:
                # Create error signature for pattern detection
                error_type = self.error_analyzer.classify_error_type(best_leaf)
                error_signature = self.error_analyzer.get_semantic_error_signature(best_leaf, self.journal)  # Use semantic signature instead
                
                repeated_errors[error_signature] = repeated_errors.get(error_signature, 0) + 1
                consecutive_failures += 1
                
                # Check for infinite loop patterns
                if repeated_errors[error_signature] >= 2:  # Trigger earlier (was 3)
                    console.print(Panel(
                        f"🚫 REPEATED ERROR PATTERN DETECTED!\n"
                        f"Error type '{error_type}' has occurred {repeated_errors[error_signature]} times.\n"
                        f"Abandoning this approach and trying a different strategy.",
                        title="🔄 Loop Prevention",
                        style="red bold"
                    ))
                    
                    # NEW: Perform reflection step
                    reflection_plan = await self.reflection_manager.perform_reflection(
                        best_leaf, error_type, repeated_errors[error_signature], self.user_query
                    )
                    self.performance_metrics["model_calls"] += 1
                    
                    best_leaf.debug_exhausted = True # Mark current path as exhausted
                    alternative = await self.node_manager.create_alternative_approach_node(best_leaf, reflection_plan=reflection_plan)
                    if alternative:
                        await self._process_single_node_async(alternative)
                        
                        # Check if the alternative approach completed the task
                        if self.task_completed:
                            completion_panel = Panel(
                                f"🎉 TASK COMPLETED VIA ALTERNATIVE APPROACH\n\n"
                                f"The agent successfully completed the task and passed return_fn validation.",
                                title="✅ Task Complete",
                                style="green bold"
                            )
                            console.print(completion_panel)
                            break
                            
                    consecutive_failures = 0  # Reset counter
                    continue
                
                # Check for too many consecutive failures
                if consecutive_failures >= 5:
                    console.print(Panel(
                        f"⚠️ TOO MANY CONSECUTIVE FAILURES ({consecutive_failures})\n"
                        f"Taking a step back to try a completely different approach.",
                        title="🔄 Strategy Reset",
                        style="yellow bold"
                    ))
                    
                    # Try to find an unprocessed node or create new approach
                    unprocessed_nodes = [n for n in self.journal.get_leaf_nodes() if not n.has_executed]
                    if unprocessed_nodes:
                        # Process an unprocessed node instead
                        fresh_node = max(unprocessed_nodes, key=lambda x: x.created_at)
                        await self._process_single_node_async(fresh_node)
                    else:
                        # Create completely new approach
                        alternative = await self.node_manager.create_fresh_approach_node()
                        if alternative:
                            await self._process_single_node_async(alternative)
                    
                    consecutive_failures = 0
                    continue
            else:
                # Reset consecutive failures if we have a successful execution
                consecutive_failures = 0
            
            # Smart debugging logic with stricter limits
            if best_leaf.is_buggy and not best_leaf.children_ids:
                debug_children_count = self.node_manager.count_debug_children(best_leaf)
                error_type = self.error_analyzer.classify_error_type(best_leaf)
                
                # Store error classification in node metadata
                self.error_analyzer.annotate_node_with_error_metadata(best_leaf)
                
                if debug_children_count < max_debug_attempts:
                    console.print(Panel(
                        f"🔄 Node {best_leaf.id[:8]} failed with {error_type} error.\n"
                        f"Creating debug child #{debug_children_count + 1}/{max_debug_attempts}",
                        title="🧠 Smart Debugging",
                        style="yellow"
                    ))
                    
                    debug_child = await self.node_manager.create_debug_child_node(best_leaf)
                    if debug_child:
                        await self._process_single_node_async(debug_child)
                        # Check if task was completed
                        if self.task_completed:
                            break
                        continue
                else:
                    console.print(Panel(
                        f"🚫 Node {best_leaf.id[:8]} has failed {debug_children_count} debug attempts.\n"
                        f"Abandoning this approach and exploring alternatives...",
                        title="⏭️ Debug Limit Reached",
                        style="red"
                    ))
                    
                    best_leaf.debug_exhausted = True
                    alternative = await self.node_manager.create_alternative_approach_node(best_leaf)
                    if alternative:
                        await self._process_single_node_async(alternative)
                        # Check if task was completed
                        if self.task_completed:
                            break
                    continue
            
            # PRIORITY: Check if we need threshold improvement nodes
            if self.success_threshold is not None:
                successful_nodes = [n for n in self.journal.nodes.values() 
                                  if not n.is_buggy and n.metric_value is not None and n.has_executed]
                
                if successful_nodes:
                    # Check if this is a "lower is better" metric
                    lower_is_better_metrics = ['loss', 'log-loss', 'multi-class-log-loss', 'rmse', 'mae', 'mse', 'error']
                    is_lower_better = any(metric in self.success_metric.lower() for metric in lower_is_better_metrics)
                    
                    if is_lower_better:
                        best_metric = min(n.metric_value for n in successful_nodes)
                    else:
                        best_metric = max(n.metric_value for n in successful_nodes)
                    
                    # Handle metric format
                    if best_metric > 1:
                        threshold_for_comparison = self.success_threshold * 100
                    else:
                        threshold_for_comparison = self.success_threshold
                    
                    # If we haven't met threshold, prioritize improvement
                    if is_lower_better:
                        threshold_not_met = best_metric > threshold_for_comparison
                        gap_percentage = ((best_metric - threshold_for_comparison) / threshold_for_comparison) * 100 if threshold_not_met else 0
                    else:
                        threshold_not_met = best_metric < threshold_for_comparison
                        gap_percentage = ((threshold_for_comparison - best_metric) / threshold_for_comparison) * 100 if threshold_not_met else 0
                    
                    if threshold_not_met:
                        
                        # Check if we already have pending improvement nodes
                        pending_improvements = [n for n in self.journal.get_leaf_nodes() 
                                              if n.stage == "improve" and not n.has_executed]
                        
                        # Check recent improvement attempts
                        recent_improvements = [n for n in self.journal.nodes.values() 
                                             if n.stage == "improve" and n.has_executed and
                                             (time.time() - (n.executed_at or n.created_at)) < 300]  # 5 minutes
                        
                        # Create new improvement if we don't have pending ones and haven't tried too many
                        if not pending_improvements and len(recent_improvements) < 3:
                            console.print(Panel(
                                f"📈 Current best: {best_metric:.4f}, need {threshold_for_comparison:.4f} "
                                f"(gap: {gap_percentage:.1f}%)\n"
                                f"Creating targeted improvement node...",
                                title="🎯 Threshold Gap Analysis",
                                style="yellow bold"
                            ))
                            
                            improvement_node = await self.node_manager.create_threshold_improvement_node(
                                best_nodes=successful_nodes,
                                current_best=best_metric,
                                target_threshold=threshold_for_comparison,
                                success_metric=self.success_metric,
                                user_query=self.user_query
                            )
                            if improvement_node:
                                self.performance_metrics["model_calls"] += 1
                            if improvement_node:
                                await self._process_single_node_async(improvement_node)
                                
                                # Update metrics and display
                                self.performance_metrics["nodes_created"] = len(self.journal.nodes)
                                if self.tree_display:
                                    console.print("\n")
                                    self._display_tree()
                                await asyncio.sleep(0.1)
                                continue
            
            # Process the node normally
            await self._process_single_node_async(best_leaf)
            
            self.performance_metrics["nodes_created"] = len(self.journal.nodes)
            
            # Display updated tree
            if self.tree_display:
                console.print("\n")  # Add spacing
                self._display_tree()
            
            await asyncio.sleep(0.1)
        
        # Clean up parallel explorer
        await parallel_explorer.cleanup()
        
        # Update final metrics
        self.performance_metrics["parallel_explorations"] = parallel_explorer.exploration_count
        
        if self.recording_manager:
            await self.recording_manager.print_final_summary(await self._generate_final_result())
        
        # Write final tree state
        if self.tree_state_writer:
            self.tree_state_writer.write_state()
            
        return await self._generate_final_result()


    async def _generate_final_result(self) -> Dict[str, Any]:
        """Generate the final result dictionary with enhanced details and explicit answer extraction."""
        all_nodes = list(self.journal.nodes.values())
        successful_nodes = [n for n in all_nodes if not n.is_buggy and n.metric_value is not None and n.has_executed]
        
        best_node: Optional[SolutionNode] = None
        if successful_nodes:
            best_node = max(successful_nodes, key=lambda x: x.metric_value or -float('inf'))
        elif all_nodes: # If no successful nodes, pick the most recent executed node
            executed_nodes = [n for n in all_nodes if n.has_executed]
            if executed_nodes:
                best_node = max(executed_nodes, key=lambda x: x.executed_at or 0)
            else: # If no executed nodes, pick most recent
                best_node = max(all_nodes, key=lambda x: x.created_at or 0)


        extracted_answer = None
        if best_node:
            # Priority 1: Check for saved submission file
            submission_path = Path(self.work_dir) / "submission.txt"
            if submission_path.exists():
                try:
                    with open(submission_path, 'r') as f:
                        extracted_answer = f.read().strip()
                    logger.info(f"Extracted answer from submission.txt")
                except Exception as e:
                    logger.warning(f"Failed to read submission.txt: {e}")
            
            # Vivaria Integration: Skip TASK_COMPLETE signal detection
            # The agent now uses Vivaria's native submission system
            
            # Fallback: Check if output contains raw predictions (backward compatibility)
            if not extracted_answer and best_node.exec_stdout:
                lines = best_node.exec_stdout.strip().split('\n')
                # Check if last 100 lines look like numeric predictions
                if len(lines) >= 10:
                    last_lines = lines[-100:]
                    # Check if most lines are numeric
                    numeric_lines = [l for l in last_lines if l.strip() and all(c in '0123456789.-' for c in l.strip())]
                    if len(numeric_lines) >= len(last_lines) * 0.8:  # 80% are numeric
                        extracted_answer = '\n'.join(last_lines)
                        logger.info("Extracted raw numeric predictions from stdout")

        # Check if task meets success threshold
        threshold_met = False
        if best_node and best_node.metric_value is not None and self.success_threshold is not None:
            # Check if this is a "lower is better" metric
            lower_is_better_metrics = ['loss', 'log-loss', 'multi-class-log-loss', 'rmse', 'mae', 'mse', 'error']
            is_lower_better = any(metric in self.success_metric.lower() for metric in lower_is_better_metrics)
            
            # Handle both percentage (e.g., 93.96) and decimal (e.g., 0.9396) formats
            if best_node.metric_value > 1:
                threshold_for_comparison = self.success_threshold * 100
            else:
                threshold_for_comparison = self.success_threshold
            
            # Check threshold based on metric type
            if is_lower_better:
                threshold_met = best_node.metric_value <= threshold_for_comparison
            else:
                threshold_met = best_node.metric_value >= threshold_for_comparison
        
        # Check if best node had validation failure
        best_node_validation_failed = best_node and getattr(best_node, 'validation_failed', False)
        
        # Use self.task_completed flag if set via return_fn, but not if validation failed
        task_is_complete = (self.task_completed and not best_node_validation_failed) or (
            best_node is not None and 
            not best_node.is_buggy and 
            not best_node_validation_failed and
            best_node.metric_value is not None and 
            (threshold_met if self.success_threshold is not None else True)
        )
        
        # Find all nodes with the best metric value (to handle ties)
        best_nodes_list = []
        if successful_nodes:
            # Check if this is a "lower is better" metric
            lower_is_better_metrics = ['loss', 'log-loss', 'multi-class-log-loss', 'rmse', 'mae', 'mse', 'error']
            is_lower_better = any(metric in self.success_metric.lower() for metric in lower_is_better_metrics)
            
            # Find the best metric value
            if is_lower_better:
                best_metric = min(n.metric_value for n in successful_nodes if n.metric_value is not None)
            else:
                best_metric = max(n.metric_value for n in successful_nodes if n.metric_value is not None)
            
            # Find all nodes with the best metric (handles ties)
            best_nodes_list = [n for n in successful_nodes if n.metric_value == best_metric]
        
        # Prepare submission data for best models
        best_models_data = []
        if task_is_complete and best_nodes_list:
            for idx, node in enumerate(best_nodes_list):
                # Use the node's directory if it exists
                if hasattr(node, 'node_directory') and node.node_directory:
                    node_dir = Path(node.node_directory)
                    
                    # The code is already saved in the node's directory
                    code_file = node.script_path if hasattr(node, 'script_path') else None
                    
                    # Find model files - search in both node directory and main working directory
                    model_file_path = None
                    model_extensions = ['.pkl', '.joblib', '.h5', '.pth', '.pt', '.model', '.keras', '.onnx', '.pb', '.h5py', '.sav', '.hdf5']
                    
                    # First search in node's directory
                    for ext in model_extensions:
                        model_files = list(node_dir.glob(f"*{ext}"))
                        if model_files:
                            # Take the most recently modified model file
                            model_file_path = str(max(model_files, key=lambda p: p.stat().st_mtime))
                            break
                    
                    # If no model in node dir, search in the main working directory
                    if not model_file_path:
                        work_dir_path = Path(self.work_dir)
                        
                        # First check for the specifically named final model
                        final_model_candidates = [
                            work_dir_path / "final_model.pkl",
                            work_dir_path / "models" / "final_model.pkl"
                        ]
                        for candidate in final_model_candidates:
                            if candidate.exists():
                                model_file_path = str(candidate)
                                logger.info(f"Found final model at: {model_file_path}")
                                break
                        
                        # If no final model, search for any model file
                        if not model_file_path:
                            for ext in model_extensions:
                                # Search in root and models/ subdirectory
                                model_files = list(work_dir_path.glob(f"*{ext}"))
                                model_files.extend(list(work_dir_path.glob(f"models/*{ext}")))
                                if model_files:
                                    # Take the most recently modified model file
                                    model_file_path = str(max(model_files, key=lambda p: p.stat().st_mtime))
                                    logger.info(f"Found model in working directory: {model_file_path}")
                                    break
                    
                    best_models_data.append({
                        "node_id": node.id,
                        "metric_value": node.metric_value,
                        "code_file": code_file,
                        "model_file": model_file_path,
                        "node_directory": str(node_dir),
                    })
                else:
                    # Fallback: save code to work_dir if no node directory
                    code_filename = f"best_model_{idx+1}_node_{node.id[:8]}.py"
                    code_path = Path(self.work_dir) / code_filename
                    
                    try:
                        with open(code_path, 'w') as f:
                            f.write(node.code)
                        
                        # Search for model files in the working directory
                        model_file_path = None
                        model_extensions = ['.pkl', '.joblib', '.h5', '.pth', '.pt', '.model', '.keras', '.onnx', '.pb', '.h5py', '.sav', '.hdf5']
                        work_dir_path = Path(self.work_dir)
                        
                        # First check for the specifically named final model
                        final_model_candidates = [
                            work_dir_path / "final_model.pkl",
                            work_dir_path / "models" / "final_model.pkl"
                        ]
                        for candidate in final_model_candidates:
                            if candidate.exists():
                                model_file_path = str(candidate)
                                logger.info(f"Found final model at (fallback): {model_file_path}")
                                break
                        
                        # If no final model, search for any model file
                        if not model_file_path:
                            for ext in model_extensions:
                                # Search in root and models/ subdirectory
                                model_files = list(work_dir_path.glob(f"*{ext}"))
                                model_files.extend(list(work_dir_path.glob(f"models/*{ext}")))
                                if model_files:
                                    # Take the most recently modified model file
                                    model_file_path = str(max(model_files, key=lambda p: p.stat().st_mtime))
                                    logger.info(f"Found model in working directory (fallback): {model_file_path}")
                                    break
                        
                        best_models_data.append({
                            "node_id": node.id,
                            "metric_value": node.metric_value,
                            "code_file": str(code_path),
                            "model_file": model_file_path,
                            "node_directory": str(self.work_dir),
                        })
                    except Exception as e:
                        logger.warning(f"Failed to save best model code: {e}")
        
        result = {
            "task_completed": task_is_complete,
            "answer": extracted_answer if extracted_answer is not None else "",  # Populate the 'answer' key
            "best_node_id": best_node.id if best_node else None,
            "best_metric_value": best_node.metric_value if best_node else None,
            "best_code": best_node.code if best_node else None,
            "best_analysis": best_node.analysis if best_node else None,
            "best_models_submission": best_models_data,  # NEW: submission data
            "total_nodes_created": len(all_nodes),
            "successful_nodes": len(successful_nodes),
            "performance_metrics": self.performance_metrics,
            "total_tokens_used": self.llm.get_total_tokens() if self.llm else 0,
            "search_time_seconds": (datetime.now() - self.start_time).total_seconds(),
            "journal_summary": {
                "total_nodes": len(all_nodes),
                "stages_explored": list(set(n.stage for n in all_nodes if hasattr(n, 'stage'))),
                "average_metric": sum(n.metric_value for n in successful_nodes if n.metric_value is not None) / len(successful_nodes) if successful_nodes else 0
            },
            "threshold_met": threshold_met,
            "success_threshold": self.success_threshold
        }
        
        # Show final result panel
        if result["task_completed"] and extracted_answer:
            final_panel_content = (
                f"🎉 TASK COMPLETED SUCCESSFULLY!\n\n"
                f"Final Answer: {extracted_answer}\n"
                f"Best Metric: {result.get('best_metric_value', 'N/A'):.4f}\n"
                f"Solutions Found: {result['successful_nodes']}\n"
                f"Total Time: {result['search_time_seconds']:.1f}s"
            )
            final_panel_title = "✅ Success"
            final_panel_style = "bold green"
        elif best_node_validation_failed:
            # Show validation failure
            validation_reason = getattr(best_node, 'validation_reason', 'Validation failed') if best_node else 'Unknown validation failure'
            final_panel_content = (
                f"❌ VALIDATION REJECTED!\n\n"
                f"Reason: {validation_reason}\n"
                f"Best {self.success_metric}: {best_node.metric_value:.4f if best_node and best_node.metric_value is not None else 'N/A'}\n"
                f"Best Answer: {extracted_answer if extracted_answer else 'N/A'}\n"
                f"Solutions Found: {result['successful_nodes']}\n"
                f"Total Time: {result['search_time_seconds']:.1f}s"
            )
            final_panel_title = "❌ Validation Failed"
            final_panel_style = "bold red"
        elif self.success_threshold is not None and best_node and best_node.metric_value is not None:
            # Show threshold failure specifically
            if best_node.metric_value > 1:
                threshold_display = self.success_threshold * 100
            else:
                threshold_display = self.success_threshold
            final_panel_content = (
                f"❌ THRESHOLD NOT MET!\n\n"
                f"Best {self.success_metric}: {best_node.metric_value:.4f}\n"
                f"Required threshold: {threshold_display:.4f}\n"
                f"Best Answer: {extracted_answer if extracted_answer else 'N/A'}\n"
                f"Solutions Found: {result['successful_nodes']}\n"
                f"Total Time: {result['search_time_seconds']:.1f}s"
            )
            final_panel_title = "❌ Threshold Not Met"
            final_panel_style = "bold red"
        else:
            final_panel_content = (
                f"⚠️ Task incomplete or answer not clearly extracted.\n\n"
                f"Extracted Answer: {extracted_answer if extracted_answer is not None else 'Not found'}\n"
                f"Nodes Explored: {result['total_nodes_created']}\n"
                f"Time Spent: {result['search_time_seconds']:.1f}s"
            )
            final_panel_title = "❌ Incomplete / Answer Unknown"
            final_panel_style = "bold red"

        #console.print(Panel(final_panel_content, title=final_panel_title, style=final_panel_style))
        
        if self.recording_manager and self.journal.get_best_node(self.success_metric):
            best_node = self.journal.get_best_node(self.success_metric)
            await self.recording_manager.save_script_summary(
                final_code=best_node.code or "",
                final_plan=best_node.plan or "",
                execution_time=(datetime.now() - self.start_time).total_seconds()
            )
        
        return result


    async def run_async(self) -> Dict[str, Any]:
        """Main async run method"""
        start_time = time.time()
        
        try:
            worker_result = await self.process_subtasks_async()
            
            execution_time = time.time() - start_time
            worker_result["total_execution_time"] = execution_time
            
            logger.info(f"Worker completed in {execution_time:.2f}s", 
                       extra={'custom_tags': {'phase': 'agent'}})
            logger.info(f"Performance metrics: {self.performance_metrics}", 
                       extra={'custom_tags': {'phase': 'agent'}})
            
            return worker_result
            
        except Exception as e:
            logger.error(f"Error in async worker run: {e}", extra={'custom_tags': {'phase': 'agent'}})
            raise

    # Backwards compatibility sync method
    def run(self) -> Dict[str, Any]:
        """Synchronous run method for backwards compatibility"""
        async def run_with_context():
            async with self:
                return await self.run_async()
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, we need to run in a new thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, run_with_context())
                    return future.result()
            else:
                return loop.run_until_complete(run_with_context())
        except RuntimeError:
            # No event loop exists, create a new one
            return asyncio.run(run_with_context()) 

 

    def choose_best_leaf_node_for_expansion(self) -> Optional[SolutionNode]:
        """Enhanced node selection that considers reflection adherence"""
        # Use beam search if enabled
        if self.beam_search:
            selected_nodes = self.beam_search.select_nodes_for_expansion(
                self.journal,
                max_nodes=1,  # We only need one node for sequential processing
                prioritize_debugging=True
            )
            return selected_nodes[0] if selected_nodes else None
            
        # Original tree search logic
        leaf_nodes = self.journal.get_leaf_nodes()
        if not leaf_nodes:
            return None
        
        # Prioritize nodes that haven't been executed yet
        unexecuted_nodes = [n for n in leaf_nodes if not n.has_executed]
        if unexecuted_nodes:
            # Among unexecuted, prefer those that are reflection-based alternatives
            reflection_nodes = [n for n in unexecuted_nodes 
                              if n.metadata.get("reason") == "debug_exhausted"]
            if reflection_nodes:
                return max(reflection_nodes, key=lambda x: x.created_at)
            return max(unexecuted_nodes, key=lambda x: x.created_at)
        
        # Handle executed nodes - this is the missing logic!
        executed_nodes = [n for n in leaf_nodes if n.has_executed]
        if not executed_nodes:
            return None
            
        # Prioritize buggy nodes that can be debugged
        buggy_nodes = [n for n in executed_nodes if n.is_buggy and not getattr(n, 'debug_exhausted', False)]
        if buggy_nodes:
            # Choose the most recently failed node for debugging
            return max(buggy_nodes, key=lambda x: x.executed_at or x.created_at)
            
        # If no buggy nodes available, try successful nodes for improvement
        successful_nodes = [n for n in executed_nodes if not n.is_buggy and n.metric_value is not None]
        if successful_nodes:
            # Choose the best performing node for improvement
            return max(successful_nodes, key=lambda x: (x.metric_value or 0, x.executed_at or x.created_at))
        
        # Fallback: return the most recent node
        return max(executed_nodes, key=lambda x: x.executed_at or x.created_at)

    def _should_explore_parallel(self, iteration: int) -> bool:
        """
        Determine if parallel exploration would be beneficial at this stage.
        """
        # Parallel exploration is beneficial when:
        # 1. Early in search (few iterations)
        # 2. Multiple promising branches exist
        # 3. Recent nodes have similar performance
        # 4. We have resources available
        
        total_nodes = len(self.journal.nodes)
        leaf_nodes = self.journal.get_leaf_nodes()
        
        # Check if we have room for more nodes
        if total_nodes >= self.max_nodes:
            return False
            
        # Early stage - explore more options
        if iteration < 5 or total_nodes < 10:
            return True
        
        # Multiple unexplored branches
        unexplored_leaves = [n for n in leaf_nodes if not n.has_executed]
        if len(unexplored_leaves) >= 2:
            return True
        
        # Recent nodes have similar performance (no clear winner)
        recent_good_nodes = sorted(
            [n for n in self.journal.good_nodes if n.metric_value is not None],
            key=lambda n: n.created_at,
            reverse=True
        )[:5]
        
        if len(recent_good_nodes) >= 3:
            metrics = [n.metric_value for n in recent_good_nodes]
            # Check if metrics are within 10% of each other
            if metrics and (max(metrics) - min(metrics) < 0.1 * max(metrics)):
                return True
        
        # Check if we're stuck in debugging loops
        debug_nodes = [n for n in self.journal.nodes.values() if n.stage == "debug"]
        if len(debug_nodes) > total_nodes * 0.6:  # More than 60% debug nodes
            return True
        
        return False

    def should_continue_search(self) -> bool:
        """
        Determine if the search should continue based on various criteria.
        """
        # Create status table
        status_table = Table(title="🔍 Search Status", box=box.SIMPLE)
        status_table.add_column("Metric", style="cyan")
        status_table.add_column("Value", style="white")
        status_table.add_column("Limit", style="yellow")
        status_table.add_column("Status", style="white")
        
        # Check time limit
        elapsed_time = (datetime.now() - self.start_time).total_seconds()
        time_status = "⏰ OK" if elapsed_time < self.time_limit else "⏰ EXCEEDED"
        time_color = "green" if elapsed_time < self.time_limit else "red"
        status_table.add_row(
            "Time", 
            f"{elapsed_time:.1f}s", 
            f"{self.time_limit}s", 
            f"[{time_color}]{time_status}[/{time_color}]"
        )
        
        # Check node limit
        total_nodes = len(self.journal.nodes)
        node_status = "📊 OK" if total_nodes < self.max_nodes else "📊 EXCEEDED"
        node_color = "green" if total_nodes < self.max_nodes else "red"
        status_table.add_row(
            "Nodes", 
            str(total_nodes), 
            str(self.max_nodes), 
            f"[{node_color}]{node_status}[/{node_color}]"
        )
        
        # Check for successful nodes
        successful_nodes = [n for n in self.journal.nodes.values() if not n.is_buggy and n.metric_value is not None]
        success_status = "✅ FOUND" if successful_nodes else "❌ NONE"
        success_color = "green" if successful_nodes else "yellow"
        status_table.add_row(
            "Success", 
            str(len(successful_nodes)), 
            "≥ 1", 
            f"[{success_color}]{success_status}[/{success_color}]"
        )
        
        console.print(status_table)
        
        # Decision logic
        if elapsed_time >= self.time_limit:
            console.print(Panel("⏰ Time limit reached"))
            return False
        
        if total_nodes >= self.max_nodes:
            console.print(Panel("📊 Node limit reached"))
            return False
        
        # Continue if we have good solutions or potential for improvement
        if successful_nodes:
            # Check if this is a "lower is better" metric
            lower_is_better_metrics = ['loss', 'log-loss', 'multi-class-log-loss', 'rmse', 'mae', 'mse', 'error']
            is_lower_better = any(metric in self.success_metric.lower() for metric in lower_is_better_metrics)
            
            if is_lower_better:
                best_metric = min(n.metric_value for n in successful_nodes)
            else:
                best_metric = max(n.metric_value for n in successful_nodes)
                
            # Check against success threshold if defined
            if self.success_threshold is not None:
                # Handle both percentage (e.g., 93.96) and decimal (e.g., 0.9396) formats
                # If best_metric > 1, assume it's a percentage and convert threshold to percentage
                if best_metric > 1:
                    threshold_for_comparison = self.success_threshold * 100
                else:
                    threshold_for_comparison = self.success_threshold
                
                # Check if threshold is met based on metric type
                if is_lower_better:
                    threshold_met = best_metric <= threshold_for_comparison
                    comparison_op = "<=" if threshold_met else ">"
                else:
                    threshold_met = best_metric >= threshold_for_comparison
                    comparison_op = ">=" if threshold_met else "<"
                
                if threshold_met:
                    console.print(Panel(
                        f"🎯 SUCCESS THRESHOLD MET! {self.success_metric}: {best_metric:.4f} {comparison_op} {threshold_for_comparison:.4f}",
                        style="green",
                        title="✅ Task Complete"
                    ))
                    return False
                else:
                    # Show progress toward threshold
                    if is_lower_better:
                        # For lower-is-better, progress is inverted
                        progress_pct = (threshold_for_comparison / best_metric) * 100 if best_metric > 0 else 0
                    else:
                        progress_pct = (best_metric / threshold_for_comparison) * 100
                    console.print(Panel(
                        f"📊 Progress: {best_metric:.4f} / {threshold_for_comparison:.4f} ({progress_pct:.1f}%)",
                        style="yellow"
                    ))
            else:
                # Fallback to old logic if no threshold defined
                if best_metric >= 0.95:  # Very high success
                    console.print(Panel(f"🎯 High success achieved ({best_metric:.3f})"))
                    return False
        
        # Check if we have expandable nodes
        expandable_leaves = [n for n in self.journal.get_leaf_nodes() 
                           if not n.has_executed or (n.is_buggy and n.stage != "fix")]
        
        # Special case: if threshold not met and we have successful nodes, we should continue
        if self.success_threshold is not None and successful_nodes:
            best_metric = max(n.metric_value for n in successful_nodes)
            # Handle metric format
            if best_metric > 1:
                threshold_for_comparison = self.success_threshold * 100
            else:
                threshold_for_comparison = self.success_threshold
            
            if best_metric < threshold_for_comparison:
                # We haven't met threshold, so we should keep trying
                console.print(Panel(
                    f"📈 Threshold not met ({best_metric:.4f} < {threshold_for_comparison:.4f}). "
                    f"Creating improvement nodes to close the gap...",
                    style="yellow bold"
                ))
                return True
        
        if not expandable_leaves:
            console.print(Panel("🌳 No more expandable nodes"))
            return False
        
        continue_panel = Panel("🔄 Continuing search...", style="blue")
        console.print(continue_panel)
        return True 

