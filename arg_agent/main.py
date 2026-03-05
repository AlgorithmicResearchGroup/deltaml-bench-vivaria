#!/usr/bin/env python3
"""
Vivaria wrapper for ARG (Algorithmic Research Group) Agent
Integrates the sophisticated AsyncWorker agent with Vivaria platform
"""
import asyncio
import json
import os
import sys
import re
import time
import traceback
from pathlib import Path
from typing import Any, Optional

# Add the local arg_agent directory to path to import the agent
ARG_AGENT_DIR = Path(__file__).resolve().parent
if str(ARG_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(ARG_AGENT_DIR))

from pyhooks import Hooks, Actions
from agent.workers.base_worker import AsyncWorker
from agent.core.task_context import TaskContext
from agent.utils.general import logger
from agent.config import (
    get_active_config, get_model_name, override_config_from_env,
    get_max_concurrent_nodes, get_time_limit_seconds, get_search_policy
)

# Apply Vivaria patches for tool integration and validation bypass
import vivaria_tool_patch  # This patches the tool execution system (includes return_fn)

# Vivaria hooks
hooks = Hooks()
actions = Actions()

# Configuration constants now loaded from manifest.json via get_active_config()

# VivariaTool class removed - now using direct tool patching via vivaria_tool_patch.py

class ARGAgentWorker(AsyncWorker):
    """Extended ARG agent for Vivaria integration"""
    
    def __init__(self, task_instructions: str, max_iterations: Optional[int] = None, **kwargs):
        # Store task instructions first
        self.task_instructions = task_instructions
        self.submission_intercepted = False
        
        # Set Vivaria mode environment variable early
        os.environ["VIVARIA_MODE"] = "true"
        
        # Load configuration from manifest.json (single source of truth)
        try:
            # Allow environment variable overrides
            override_config_from_env()
            config = get_active_config()
            logger.info(f"Loaded configuration: {config.description}")
        except Exception as e:
            logger.error(f"Failed to load configuration from manifest: {e}")
            # Fallback to basic configuration
            from agent.config.manifest_config import AgentConfig
            config = AgentConfig(
                model="o3-mini", 
                max_iterations=50,
                context_window_tokens=16000,
                description="Fallback configuration"
            )
        
        # Use manifest configuration with runtime overrides
        model_name = kwargs.get('model_name') or config.model
        max_iterations = max_iterations or config.max_iterations
        context_window_tokens = kwargs.get('context_window_tokens') or config.context_window_tokens
        
        # Create task context BEFORE setting up tools
        self.task_context = TaskContext(
            task_description=task_instructions,
            workspace_dir="/home/agent/solution",
            max_iterations=max_iterations
        )
        
        # Determine provider based on model name
        provider = 'openai' if any(x in model_name for x in ['gpt', 'o1', 'o3']) else 'anthropic'
        
        # Create search policy config from manifest (single source of truth)
        search_policy = config.search_policy
        search_policy_config = {
            "num_drafts": max(kwargs.get('num_initial_drafts', search_policy.num_drafts), search_policy.num_drafts),
            "debug_prob": search_policy.debug_prob,
            "max_debug_depth": search_policy.max_debug_depth,
            "min_debug_attempts": search_policy.min_debug_attempts,
            "target_metric_name": "score",
            "target_metric_lower_is_better": False,
            "search_strategy": kwargs.get('search_strategy', search_policy.search_strategy),
            "force_continue_on_incomplete": search_policy.force_continue_on_incomplete,
            "min_iterations_before_stop": search_policy.min_iterations_before_stop,
        }
        
        # Storage configuration (disabled for Vivaria)
        storage_config = {
            'enabled': False,
            'provider': 'local',
            'output_dir': '/home/agent/solution'
        }
        
        # Initialize with proper AsyncWorker parameters (matching run_agent.py)
        super().__init__(
            user_id=1,
            run_id=os.getenv('RUN_ID', 'vivaria_run'),
            user_query=task_instructions,
            plan=task_instructions,  # Use instructions as plan
            worker_number=0,
            email="vivaria@example.com",
            provider=provider,
            max_iterations=max_iterations,
            model_name=model_name,
            enable_tool_use=True,
            time_limit=kwargs.get('timeout', config.time_limit_seconds),
            search_policy_config=search_policy_config,
            storage_config=storage_config,
            enable_parallel_exploration=kwargs.get('enable_parallel', True),
            max_concurrent_nodes=kwargs.get('max_concurrent_nodes', config.max_concurrent_nodes),
            task_name="vivaria_task",
            auto_complete=False,
            success_metric="score",
            success_threshold=None,
            repeat_error_threshold=10
        )
        
        # Set up Vivaria tool integration
        self._setup_vivaria_tools()
        
        # Override system prompt for Vivaria compatibility
        self._setup_vivaria_prompts()
        
    def _setup_vivaria_tools(self):
        """Set up Vivaria tool integration by patching the ARG agent tool system"""
        try:
            # Set the Vivaria hooks reference for the tool patch system
            vivaria_tool_patch.set_vivaria_hooks(hooks)
            
            # Apply the tool patches to integrate Vivaria execution
            success = vivaria_tool_patch.apply_vivaria_tool_patches()
            
            if success:
                hooks.log("✅ Vivaria tool integration successful")
            else:
                hooks.log("❌ Vivaria tool integration failed")
                
        except Exception as e:
            hooks.log(f"⚠️ Error setting up Vivaria tools: {e}")
            # Continue anyway - the agent may still work with reduced functionality
    
    def _setup_vivaria_prompts(self):
        """Set up Vivaria-compatible prompts for the agent"""
        from vivaria_prompts import get_vivaria_worker_system_prompt
        
        # Override the system prompt used by the LLM interface
        vivaria_system_prompt = get_vivaria_worker_system_prompt()
        
        # Store the Vivaria prompt for use in LLM calls
        if hasattr(self, 'llm_interface') and self.llm_interface:
            # Update the system prompt in the LLM interface if it exists
            self.llm_interface.system_prompt = vivaria_system_prompt
        
        # Also store it as an instance variable for later use
        self.vivaria_system_prompt = vivaria_system_prompt
        
        hooks.log("🎯 Vivaria-compatible prompts loaded")
    
    async def _handle_submission_output(self, stdout_text: str, node) -> bool:
        """
        Override submission detection to use Vivaria hooks instead of custom validation
        Returns True if submission was handled, False otherwise
        """
        if self.submission_intercepted:
            return False
            
        # Check for the ARG agent's completion signal
        has_completion_signal = "TASK_COMPLETE:" in stdout_text
        
        if has_completion_signal and not node.exec_error:
            hooks.log("🎯 Detected task completion signal - intercepting for Vivaria...")
            
            # Extract submission info using regex
            completion_match = re.search(r"TASK_COMPLETE:\s*submission_path=(\S+)\s+score=(\S+)", stdout_text)
            
            if completion_match:
                submission_path = completion_match.group(1)
                score_str = completion_match.group(2)
                
                try:
                    score = float(score_str)
                except ValueError:
                    score = 0.0
                
                hooks.log(f"📄 Submission file: {submission_path}")
                hooks.log(f"📊 Score: {score}")
                
                # Read the submission content
                submission_content = ""
                try:
                    if os.path.exists(submission_path):
                        with open(submission_path, 'r') as f:
                            submission_content = f.read()
                    else:
                        hooks.log(f"⚠️ Submission file not found: {submission_path}")
                        submission_content = f"File not found: {submission_path}"
                except Exception as e:
                    hooks.log(f"❌ Error reading submission: {e}")
                    submission_content = f"Error reading file: {e}"
                
                # Submit to Vivaria
                try:
                    hooks.log("📤 Submitting to Vivaria...")
                    await hooks.submit(submission_content)
                    hooks.log("✅ Successfully submitted to Vivaria!")
                    
                    # Mark as intercepted to prevent duplicate processing
                    self.submission_intercepted = True
                    
                    # Update node for proper tracking
                    node.is_buggy = False
                    node.metric_value = score
                    node.metric_name = self.success_metric or "accuracy"
                    node.analysis = f"Task completed successfully via Vivaria. Score: {score}"
                    node.reviewed_at = time.time()
                    
                    # Mark task as completed
                    self.task_completed = True
                    
                    return True
                    
                except Exception as e:
                    hooks.log(f"❌ Error submitting to Vivaria: {e}")
                    # Fall back to original behavior
                    return False
            else:
                hooks.log("⚠️ TASK_COMPLETE signal found but couldn't parse submission info")
                return False
        
        return False
    
    async def _review_execution_async(self, node) -> None:
        """
        Override execution review to intercept submissions for Vivaria
        """
        # First check if we should handle submission through Vivaria
        stdout_text = node.exec_stdout if node.exec_stdout else ""
        
        # Try to handle submission via Vivaria
        submission_handled = await self._handle_submission_output(stdout_text, node)
        
        if submission_handled:
            # If we successfully submitted to Vivaria, skip the original review
            hooks.log("🎯 Submission handled by Vivaria - skipping original review")
            return
        
        # Otherwise, call the parent's review but bypass custom validation
        hooks.log("📊 Continuing with standard execution review...")
        
        # Set environment to signal we're in Vivaria mode
        original_env = os.environ.get("VIVARIA_MODE")
        os.environ["VIVARIA_MODE"] = "true"
        
        try:
            # Call parent review processing
            return await super()._review_execution_async(node)
        finally:
            # Restore environment
            if original_env is None:
                os.environ.pop("VIVARIA_MODE", None)
            else:
                os.environ["VIVARIA_MODE"] = original_env
    
    async def solve_task(self):
        """Main solve_task method for Vivaria - leverages ARG agent's full capabilities"""
        try:
            hooks.log("🧠 Starting ARG Agent's sophisticated problem-solving...")
            
            # Use ARG agent's sync run method which includes proper component initialization
            # The sync method wraps run_async with the necessary async context manager
            import asyncio
            loop = asyncio.get_event_loop()
            
            def run_worker():
                return self.run()  # This includes the async context manager
            
            # Run in executor to avoid blocking the event loop
            result = await loop.run_in_executor(None, run_worker)
            
            hooks.log("✅ ARG Agent solving completed")
            return result
            
        except Exception as e:
            hooks.log(f"❌ Error in ARG Agent solving: {e}")
            logger.error(f"Error in solve_task: {e}")
            # Try fallback approach
            return await self._solve_with_agent_logic()
    
    async def _solve_with_agent_logic(self) -> None:
        """Use ARG agent's sophisticated solving logic"""
        try:
            # Initialize the agent's async components
            await self.initialize_async_components()
            
            # Set up the problem-solving context
            from agent.core.solution_tree import SolutionNode
            
            # Create or get root node
            if not self.journal.root_node_ids:
                # Create initial root node for the task
                import uuid
                root_node = SolutionNode(
                    id=uuid.uuid4().hex,  # Ensure unique ID
                    stage="initial_plan",
                    plan=f"Solve task: {self.task_instructions}",
                    code="# Task analysis and planning will go here"
                )
                if root_node.id not in self.journal.nodes:
                    self.journal.add_node(root_node)
            else:
                # Get existing root node
                root_node = self.journal.get_node(self.journal.root_node_ids[0])
                
            hooks.log(f"🌳 Solution tree initialized with root node: {root_node.id[:8]}")
            
            # For now, use a simplified approach since we're inside Vivaria
            # The AsyncWorker's full run() method is designed for standalone execution
            hooks.log("🧠 Starting ARG agent problem-solving using simplified approach...")
            
            # Generate initial draft using the agent's prompt system
            await self._generate_and_execute_solution()
            
            # Get the best result so far
            best_node = self.journal.get_best_node("score", lower_is_better=False)
            if best_node and best_node.metric_value:
                hooks.log(f"✅ Best solution found with score: {best_node.metric_value}")
                return f"Solution completed with score: {best_node.metric_value}"
            else:
                hooks.log("⚠️ No successful solution found yet")
                return "Working on solution..."
            
        except Exception as e:
            logger.error(f"Error in agent logic: {e}")
            # Fallback to simpler approach
            return await self._simple_solve()
    
    async def _generate_and_execute_solution(self):
        """Generate and execute solution using ARG agent's workflow"""
        try:
            hooks.log("🔬 Generating solution using ARG agent's advanced workflow...")
            
            # Get the task description and create a draft node
            from vivaria_prompts import get_vivaria_tool_enhanced_draft_prompt
            
            draft_prompt = get_vivaria_tool_enhanced_draft_prompt(
                task_desc=self.task_instructions,
                journal_summary="Starting fresh solution",
                success_metric="score",
                success_threshold=None
            )
            
            # Create an implement node (AsyncWorker uses "implement", not "draft")
            from agent.core.solution_tree import SolutionNode
            import uuid
            draft_node = SolutionNode(
                id=uuid.uuid4().hex,  # Ensure unique ID
                stage="implement",     # Use "implement" stage that AsyncWorker supports
                generation_prompt=draft_prompt,
                parent_id=self.journal.root_node_ids[0] if self.journal.root_node_ids else None
            )
            
            # Add to journal (check if not already exists)
            if draft_node.id not in self.journal.nodes:
                self.journal.add_node(draft_node)
                hooks.log(f"📝 Created draft node: {draft_node.id[:8]}")
            else:
                hooks.log(f"📝 Using existing draft node: {draft_node.id[:8]}")
                draft_node = self.journal.get_node(draft_node.id)
            
            # Generate plan and code using the ARG agent's method
            await self._generate_node_content_async(draft_node)
            hooks.log("💡 Generated plan and code")
            
            # Execute the generated code
            await self._execute_generated_code_async(draft_node)
            hooks.log("⚡ Executed generated solution")
            
            # Review the execution
            await self._review_execution_async(draft_node)
            hooks.log("🔍 Reviewed execution results")
            
            # If there were errors, try to debug
            if draft_node.is_buggy and draft_node.exec_error:
                hooks.log(f"🐛 Solution has bugs, attempting to debug...")
                await self._attempt_debug(draft_node)
            
        except Exception as e:
            logger.error(f"Error in solution generation: {e}")
            hooks.log(f"❌ Error in solution generation: {str(e)}")
    
    async def _attempt_debug(self, buggy_node):
        """Attempt to debug a buggy solution"""
        try:
            from agent.core.prompts import get_debug_prompt
            from agent.core.solution_tree import SolutionNode
            
            # Create debug prompt
            buggy_node_dict = {
                'exec_error': buggy_node.exec_error,
                'exec_stderr': buggy_node.exec_stderr,
                'code': buggy_node.code
            }
            
            debug_prompt = get_debug_prompt(
                task_desc=self.task_instructions,
                buggy_node_dict=buggy_node_dict,
                journal_summary=self.journal.generate_summary_for_llm(max_entries=3)
            )
            
            # Create debug node
            import uuid
            debug_node = SolutionNode(
                id=uuid.uuid4().hex,  # Ensure unique ID
                stage="debug", 
                generation_prompt=debug_prompt,
                parent_id=buggy_node.id
            )
            
            # Add to journal (check if not already exists)
            if debug_node.id not in self.journal.nodes:
                self.journal.add_node(debug_node)
                hooks.log(f"🔧 Created debug node: {debug_node.id[:8]}")
            else:
                hooks.log(f"🔧 Using existing debug node: {debug_node.id[:8]}")
                debug_node = self.journal.get_node(debug_node.id)
            
            # Generate, execute, and review debug solution
            await self._generate_node_content_async(debug_node)
            await self._execute_generated_code_async(debug_node)
            await self._review_execution_async(debug_node)
            
            if not debug_node.is_buggy:
                hooks.log("✅ Debug attempt successful!")
            else:
                hooks.log("⚠️ Debug attempt still has issues")
                
        except Exception as e:
            logger.error(f"Error in debug attempt: {e}")
    
    def _extract_best_solution(self) -> str:
        """Extract the best solution from the agent's exploration"""
        try:
            # Get the best scoring node
            best_node = self.journal.get_best_node("score", lower_is_better=False)
            if best_node and best_node.metric_value:
                return f"Best solution achieved score: {best_node.metric_value}"
            else:
                return "No successful solution found yet"
                
        except Exception as e:
            logger.error(f"Error extracting solution: {e}")
            return "Basic solution due to extraction error"
    
    async def _extract_best_solution_for_submission(self) -> str:
        """Extract the best solution for Vivaria submission"""
        try:
            # Look for the most recent solution file created by the agent
            import os
            from pathlib import Path
            
            # Check common solution file locations
            solution_files = ['solution.py', 'submission.txt', 'answer.py', 'main.py']
            
            for filename in solution_files:
                if os.path.exists(filename):
                    hooks.log(f"📄 Found solution file: {filename}")
                    with open(filename, 'r') as f:
                        content = f.read()
                    if content.strip():  # Only submit if file has content
                        return content
            
            # If no files found, try to extract code from the journal
            if hasattr(self, 'journal') and self.journal:
                # Get the most recent nodes with code
                recent_nodes = self.journal.all_nodes_chronological[-10:]  # Last 10 nodes
                for node in reversed(recent_nodes):  # Check most recent first
                    if hasattr(node, 'code') and node.code and len(node.code.strip()) > 50:
                        hooks.log(f"📝 Extracting code from node {node.id[:8]}")
                        return f"# Solution extracted from agent exploration\n{node.code}"
            
            # Last resort: provide a basic template
            return '''# ARG Agent was unable to complete the solution
# The agent detected issues with code generation and stopped
# This is a placeholder submission

def prefix_sum(x):
    """Placeholder implementation"""
    # TODO: Implement the required prefix sum logic
    return x  # This is incomplete
'''
                
        except Exception as e:
            logger.error(f"Error extracting solution for submission: {e}")
            return f"# Error extracting solution: {str(e)}"
    
    async def _simple_solve(self) -> str:
        """Simplified solving approach as fallback"""
        hooks.log("🔄 Using simplified solving approach...")
        
        # Basic problem analysis
        analysis = f"Analyzing task: {self.task_instructions}"
        hooks.log(f"🔍 {analysis}")
        
        # Generate a basic solution
        solution = "ARG Agent solution - adapted for Vivaria"
        
        return solution

async def main(*args):
    """Main entry point for Vivaria"""
    logger.info("ARG Agent starting in Vivaria environment...")
    
    try:
        # Get task from Vivaria
        task = await hooks.getTask()
        task_instructions = task.instructions.strip()
        
        hooks.log("🚀 ARG Agent starting...")
        hooks.log(f"�� Task received: {len(task_instructions)} characters")
        
        # Get usage info
        usage_info = await hooks.get_usage()
        token_limit = usage_info.usageLimits.tokens
        time_limit = usage_info.usageLimits.total_seconds
        
        hooks.log(f"💰 Token limit: {token_limit:,}")
        hooks.log(f"⏰ Time limit: {time_limit} seconds") 
        
        # Load configuration to determine optimal settings
        config = get_active_config()
        
        # Initialize ARG agent with manifest-based configuration 
        agent = ARGAgentWorker(
            task_instructions=task_instructions,
            max_iterations=config.max_iterations,  # Use manifest setting
            context_window_tokens=min(token_limit // 2, config.context_window_tokens),  # Use manifest setting but respect token limits
            timeout=min(time_limit - 60, config.time_limit_seconds)  # Use manifest time limit but respect Vivaria limits
        )
        
        # Save initial state
        hooks.save_state({
            "status": "initialized",
            "agent_type": "ARG_Agent",
            "task_length": len(task_instructions),
            "token_limit": token_limit
        })
        
        # Solve the task (now handles submission internally)
        result = await agent.solve_task()
        
        # Check if agent actually submitted to Vivaria
        # Also check the global flag from vivaria_tool_patch as a backup
        submission_occurred = agent.submission_intercepted or vivaria_tool_patch.vivaria_submission_attempted
        
        if not submission_occurred:
            hooks.log("⚠️ Agent completed but didn't submit - forcing submission of best solution...")
            
            # Try to find and submit the best solution the agent found
            best_solution = await agent._extract_best_solution_for_submission()
            if best_solution:
                hooks.log("📤 Submitting best available solution...")
                await hooks.submit(best_solution)
                hooks.log("✅ Fallback submission completed!")
            else:
                hooks.log("❌ No solution found to submit - submitting error message")
                await hooks.submit("ARG Agent completed but did not produce a valid solution.")
        
        # Save final state
        hooks.save_state({
            "status": "completed", 
            "submission_completed": True,
            "submission_method": "intercepted" if agent.submission_intercepted else "fallback"
        })
        
        hooks.log("✅ ARG Agent completed successfully!")
        
    except Exception as e:
        error_msg = f"Fatal error in ARG Agent: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        hooks.log(f"💥 Fatal error: {str(e)}")
        
        # Try to submit error information
        try:
            await hooks.submit(f"ARG Agent encountered an error: {str(e)}")
        except:
            pass
        
        # Save error state
        hooks.save_state({
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        })

if __name__ == "__main__":
    hooks.main(main)
