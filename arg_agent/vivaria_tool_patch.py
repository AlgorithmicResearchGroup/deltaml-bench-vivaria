"""
Vivaria tool integration for ARG Agent.
Patches the tool execution functions to use Vivaria hooks instead of direct execution.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Add the local arg_agent directory to path
ARG_AGENT_DIR = Path(__file__).resolve().parent
if str(ARG_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(ARG_AGENT_DIR))

# Will be set by main.py when Vivaria hooks are available
vivaria_hooks = None

# Global flag to track if submission was attempted via return_fn
vivaria_submission_attempted = False

def set_vivaria_hooks(hooks_ref):
    """Set the Vivaria hooks reference for tool execution"""
    global vivaria_hooks
    vivaria_hooks = hooks_ref

async def vivaria_run_python_async(params: Dict[str, Any]) -> Dict[str, Any]:
    """Vivaria-compatible Python execution"""
    global vivaria_hooks
    
    if not vivaria_hooks:
        return {"subtask_result": "Vivaria hooks not available", "attempted": "no", "error": "No hooks"}
    
    try:
        # Extract code from various possible parameter formats
        code = params.get('code') or params.get('filepath') or params.get('script', '')
        
        if not code:
            return {"subtask_result": "No code provided to execute", "attempted": "no"}
        
        # If it's a filepath, try to read the file
        if 'filepath' in params and os.path.exists(code):
            with open(code, 'r') as f:
                code = f.read()
        
        # Execute via Vivaria
        result = await vivaria_hooks.action({
            "type": "python",
            "args": {"code": code}
        })
        
        # Format result consistent with ARG agent expectations
        result_str = str(result)
        return {
            "subtask_result": result_str,
            "attempted": "yes",
            "stdout": result_str,
            "stderr": "",
            "exit_code": 0
        }
        
    except Exception as e:
        error_msg = f"Python execution error: {str(e)}"
        return {
            "subtask_result": error_msg,
            "attempted": "yes", 
            "error": str(e),
            "stderr": error_msg,
            "exit_code": 1
        }

async def vivaria_run_bash_async(params: Dict[str, Any]) -> Dict[str, Any]:
    """Vivaria-compatible Bash execution"""
    global vivaria_hooks
    
    if not vivaria_hooks:
        return {"subtask_result": "Vivaria hooks not available", "attempted": "no", "error": "No hooks"}
    
    try:
        # Extract command from various possible parameter formats
        command = params.get('command') or params.get('script') or params.get('cmd', '')
        
        if not command:
            return {"subtask_result": "No command provided to execute", "attempted": "no"}
        
        # Execute via Vivaria
        result = await vivaria_hooks.action({
            "type": "bash",
            "args": {"command": command}
        })
        
        # Format result consistent with ARG agent expectations
        result_str = str(result)
        return {
            "subtask_result": result_str,
            "attempted": "yes",
            "stdout": result_str,
            "stderr": "",
            "exit_code": 0
        }
        
    except Exception as e:
        error_msg = f"Bash execution error: {str(e)}"
        return {
            "subtask_result": error_msg,
            "attempted": "yes",
            "error": str(e), 
            "stderr": error_msg,
            "exit_code": 1
        }

async def vivaria_return_fn_async(params: Dict[str, Any], worker_context=None) -> Dict[str, Any]:
    """Vivaria-compatible return function - submits directly to Vivaria"""
    global vivaria_hooks
    
    # Check if we're in Vivaria mode (replaces the old return_fn_patch.py logic)
    if os.environ.get("VIVARIA_MODE") == "true" or vivaria_hooks:
        if not vivaria_hooks:
            # Fallback if hooks not set but we're in Vivaria mode
            print("⚠️ Vivaria hooks not available - cannot submit properly")
            return {
                "tool": "return_fn",
                "status": "success",
                "attempt": f"Task completed via Vivaria mode (hooks unavailable). Score: {params.get('score', 0.0)}",
                "stdout": f"Submission: {params.get('submission_path', 'submission.txt')}, Score: {params.get('score', 0.0)}",
                "stderr": "",
                "score_path": "score.txt", 
                "submission_path": params.get('submission_path', 'submission.txt'),
                "score": params.get('score', 0.0),
                "vivaria_mode": True
            }
        
        try:
            submission_path = params.get('submission_path', 'submission.txt')
            score = params.get('score', 0.0)
            
            # Read submission content
            submission_content = ""
            if os.path.exists(submission_path):
                with open(submission_path, 'r') as f:
                    submission_content = f.read()
            else:
                submission_content = f"File not found: {submission_path}"
            
            # Log submission details BEFORE submitting (since submit() exits)
            print(f"📤 Submitting to Vivaria via return_fn tool...")
            print(f"   Submission path: {submission_path}")
            print(f"   Score: {score}")
            print(f"   Content length: {len(submission_content)} chars")
            
            # Mark submission as intercepted if we have access to worker context
            if worker_context and hasattr(worker_context, 'submission_intercepted'):
                worker_context.submission_intercepted = True
            
            # Set global flag to indicate submission was attempted
            global vivaria_submission_attempted
            vivaria_submission_attempted = True
            
            # Submit to Vivaria - THIS WILL EXIT THE PROCESS!
            await vivaria_hooks.submit(submission_content)
            
            # THIS CODE WILL NEVER BE REACHED - hooks.submit() calls exit(0)
            # But we keep it for completeness in case submit behavior changes
            return {
                "tool": "return_fn",
                "status": "success",
                "attempt": f"Submitted to Vivaria. Score: {score}",
                "stdout": f"Submission: {submission_path}, Score: {score}",
                "stderr": "",
                "score_path": "score.txt",
                "submission_path": submission_path,
                "score": score,
                "vivaria_mode": True
            }
            
        except Exception as e:
            error_msg = f"Vivaria submission error: {str(e)}"
            return {
                "tool": "return_fn",
                "status": "failure",
                "attempt": error_msg,
                "stdout": "",
                "stderr": error_msg,
                "score_path": "score.txt",
                "submission_path": params.get('submission_path', 'submission.txt'),
                "score": params.get('score', 0.0),
                "error": str(e)
            }
    else:
        # Not in Vivaria mode - use original function
        try:
            from agent.tools.return_fn.return_fn_tool_async import return_fn_async as original_return_fn_async
            if hasattr(original_return_fn_async, '_original_return_fn_async'):
                return await original_return_fn_async._original_return_fn_async(params, worker_context)
            else:
                # Fallback implementation
                return {
                    "tool": "return_fn",
                    "status": "success", 
                    "attempt": f"Task completed outside Vivaria. Score: {params.get('score', 0.0)}",
                    "stdout": f"Submission: {params.get('submission_path', 'submission.txt')}, Score: {params.get('score', 0.0)}",
                    "stderr": "",
                    "score_path": "score.txt",
                    "submission_path": params.get('submission_path', 'submission.txt'),
                    "score": params.get('score', 0.0)
                }
        except Exception as e:
            return {
                "tool": "return_fn",
                "status": "failure",
                "attempt": f"return_fn failed: {e}",
                "stdout": "",
                "stderr": str(e),
                "score_path": "score.txt",
                "submission_path": params.get('submission_path', 'submission.txt'),
                "score": params.get('score', 0.0),
                "error": str(e)
            }

def apply_vivaria_tool_patches():
    """Apply Vivaria tool patches to the ARG agent tool system"""
    try:
        # Import the tool registry module
        from agent.tools import tool_registry_async
        
        # Patch the async function mapping to use Vivaria tools
        original_mapping = tool_registry_async.AsyncTool.__dict__.get('_original_mapping', None)
        
        if not original_mapping:
            # Store original mapping for potential restoration
            if hasattr(tool_registry_async, 'AsyncTool'):
                # Get the async function mapping from the AsyncTool.run_async method
                # We'll need to patch the function mapping inside the run_async method
                pass
        
        # Monkey patch the tool functions by modifying the module's function mapping
        import agent.tools.python.python_tool_async as python_module
        import agent.tools.bash.bash_tool_async as bash_module
        import agent.tools.return_fn.return_fn_tool_async as return_fn_module
        
        # Store originals if not already stored
        if not hasattr(python_module, '_original_run_python_async'):
            python_module._original_run_python_async = python_module.run_python_async
        if not hasattr(bash_module, '_original_run_bash_async'):
            bash_module._original_run_bash_async = bash_module.run_bash_async  
        if not hasattr(return_fn_module, '_original_return_fn_async'):
            return_fn_module._original_return_fn_async = return_fn_module.return_fn_async
        
        # Apply patches
        python_module.run_python_async = vivaria_run_python_async
        bash_module.run_bash_async = vivaria_run_bash_async
        return_fn_module.return_fn_async = vivaria_return_fn_async
        
        print("✅ Vivaria tool patches applied successfully")
        return True
        
    except Exception as e:
        print(f"❌ Failed to apply Vivaria tool patches: {e}")
        return False

def restore_original_tools():
    """Restore original tool implementations"""
    try:
        import agent.tools.python.python_tool_async as python_module
        import agent.tools.bash.bash_tool_async as bash_module
        import agent.tools.return_fn.return_fn_tool_async as return_fn_module
        
        # Restore originals if they exist
        if hasattr(python_module, '_original_run_python_async'):
            python_module.run_python_async = python_module._original_run_python_async
        if hasattr(bash_module, '_original_run_bash_async'):
            bash_module.run_bash_async = bash_module._original_run_bash_async
        if hasattr(return_fn_module, '_original_return_fn_async'):
            return_fn_module.return_fn_async = return_fn_module._original_return_fn_async
        
        print("✅ Original tools restored")
        return True
        
    except Exception as e:
        print(f"❌ Failed to restore original tools: {e}")
        return False
