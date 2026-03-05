import os
import asyncio
import aiofiles
import json
import time
import uuid
from typing import Dict, Any, Optional
from agent.utils.general import logger, console
from rich.panel import Panel
from rich.text import Text

return_fn_tool_definitions = [
    {
        "name": "return_fn",
        "description": "Formats results of the subtask.",
        "input_schema": {
            "type": "object",
            "properties": {
                "score_path": {
                    "type": "string",
                    "description": "The path to the score.txt file.",
                },
                "submission_path": {
                    "type": "string",
                    "description": "Path to the csv file to be submitted",
                },
                "score": {  
                    "type": "number",
                    "description": "The score of the kaggle submission, surpassing the target score.",
                },
            },
            "required": ["submission_path", "score"],
        },
    }
]

async def return_fn_async(arguments, worker_context=None):
    """
    Async version of return_fn to signal task completion.
    Now includes validation step to check if task is truly complete and legitimate.
    """
    score_path = arguments.get("score_path", "task_complete.txt")
    submission_path = arguments.get("submission_path", "output.txt") 
    score = arguments.get("score", "1.0")

    try:
        # Read submission content asynchronously if file exists
        submission_content = ""
        if os.path.exists(submission_path):
            try:
                async with aiofiles.open(submission_path, 'r') as f:
                    submission_content = (await f.read()).strip()
            except Exception as e:
                logger.warning(f"Could not read submission file {submission_path}: {e}")
                submission_content = f"Error reading file: {e}"
        else:
            logger.warning(f"Submission file not found: {submission_path}")
            submission_content = "File not found"

        # 🔍 VIVARIA INTEGRATION: Skip validation in Vivaria mode
        # Vivaria handles validation and submission through hooks.submit()
        vivaria_mode = os.getenv('RUN_ID') is not None or os.getenv('VIVARIA_MODE') == 'true'
        
        if worker_context and not vivaria_mode:
            validation_result = await _validate_task_completion(
                worker_context, submission_path, score, submission_content
            )
            
            # If validation fails, create new node and inject rejection message
            if not validation_result["is_valid"]:
                await _handle_validation_failure(worker_context, validation_result)
                
                # Return a "continue" signal rather than completion
                return {
                    "tool": "return_fn",
                    "status": "validation_failed",
                    "attempt": f"Task completion rejected: {validation_result['reasoning']}",
                    "stdout": validation_result["feedback_message"],
                    "stderr": "",
                    "continue_execution": True,  # Signal to continue rather than terminate
                    "score_path": score_path,
                    "submission_path": submission_path,
                    "score": score
                }
        elif vivaria_mode:
            logger.info("Running in Vivaria mode - skipping custom validation, using hooks.submit()")

        # Original completion logic (only if validation passes or no worker context)
        try:
            async with aiofiles.open(score_path, 'w') as f:
                await f.write(f"Task completed with score: {score}\n")
                await f.write(f"Submission path: {submission_path}\n")
                await f.write(f"Submission content: {submission_content}\n")
        except Exception as e:
            logger.warning(f"Could not write score file: {e}")

        logger.info(f"Task completed - Score: {score}, Output: {submission_path}", 
                   extra={'custom_tags': {'phase': 'agent', 'tool': 'return_fn'}})

        return {
            "tool": "return_fn",
            "status": "success",
            "attempt": f"Task completed successfully! Score: {score}, Submission: {submission_path}",
            "stdout": submission_content,
            "stderr": "",
            "score_path": score_path,
            "submission_path": submission_path,
            "score": score
        }

    except Exception as e:
        logger.error(f"Error in return_fn_async: {e}", extra={'custom_tags': {'phase': 'agent', 'tool': 'return_fn'}})
        return {
            "tool": "return_fn",
            "status": "failure",
            "attempt": f"return_fn failed: {e}",
            "stdout": "",
            "stderr": str(e),
            "score_path": score_path,
            "submission_path": submission_path,
            "score": score
        }

async def _validate_task_completion(worker_context, submission_path: str, score: float, submission_content: str) -> Dict[str, Any]:
    """
    Use the model to validate if the task completion is sufficient and legitimate.
    """
    # Check if validation is disabled
    if os.environ.get('DISABLE_RETURN_VALIDATION', '').lower() == 'true':
        logger.info("Return validation disabled via DISABLE_RETURN_VALIDATION env var")
        return {"is_valid": True, "reasoning": "Validation disabled"}
    
    try:
        # Import here to avoid circular imports
        from agent.core.prompts import get_return_validation_prompt, get_return_validation_function_spec
        
        # Get the initial task from worker context
        initial_task = getattr(worker_context, 'user_query', 'Task information not available')
        
        # 🎯 Check success threshold FIRST
        success_metric = getattr(worker_context, 'success_metric', None)
        success_threshold = getattr(worker_context, 'success_threshold', None)
        
        if success_threshold is not None:
            try:
                score_float = float(score)
                if score_float < success_threshold:
                    threshold_fail_msg = (
                        f"❌ THRESHOLD NOT MET!\n\n"
                        f"Required {success_metric}: >= {success_threshold:.4f}\n"
                        f"Your {success_metric}: {score_float:.4f}\n\n"
                        f"You must improve the model to meet the threshold before submitting."
                    )
                    
                    # Show rejection immediately
                    rejection_panel = Panel(
                        threshold_fail_msg,
                        title="🚫 Submission Rejected - Below Threshold",
                        style="red"
                    )
                    console.print(rejection_panel)
                    
                    return {
                        "is_valid": False,
                        "reasoning": f"Score {score_float:.4f} is below required threshold {success_threshold:.4f}",
                        "feedback_message": threshold_fail_msg
                    }
            except (ValueError, TypeError):
                logger.warning(f"Could not parse score as float: {score}")
        
        # Get the last attempt (current node or recent activity) - INCLUDE FULL CODE FOR VALIDATION
        last_attempt = "Recent activity not available"
        last_code = ""
        if hasattr(worker_context, 'journal') and worker_context.journal:
            recent_nodes = worker_context.journal.all_nodes_chronological[-5:]  # Last 5 nodes
            if recent_nodes:
                last_node = recent_nodes[-1]
                # Include FULL code for cheating detection, not truncated
                last_code = last_node.code if last_node.code else ""
                last_attempt = f"Stage: {last_node.stage}, Output: {last_node.exec_stdout[:500] if last_node.exec_stdout else 'No output'}..."
        
        # Get journal summary
        journal_summary = "Journal not available"
        if hasattr(worker_context, 'journal') and worker_context.journal:
            journal_summary = worker_context.journal.generate_summary_for_llm(max_entries=10, include_code=False)
        
        # Create validation prompt (now includes full code for cheating detection)
        validation_prompt = get_return_validation_prompt(
            initial_task=initial_task,
            last_attempt=last_attempt,
            journal_summary=journal_summary,
            submission_path=submission_path,
            score=score,
            last_code=last_code  # Pass full code for hardcoded score detection
        )
        
        # Get function spec for validation
        validation_func_spec = get_return_validation_function_spec()
        
        # Show validation in progress
        validation_panel = Panel(
            "🔍 Validating task completion...\nChecking if answer is sufficient and legitimate...",
            title="⚖️ Return Validation",
            style="yellow"
        )
        console.print(validation_panel)
        
        # Make model call for validation with retry logic
        if hasattr(worker_context, 'model') and worker_context.model:
            max_retries = 3
            retry_count = 0
            last_error = None
            
            while retry_count < max_retries:
                try:
                    response_data, total_tokens, _, _ = await worker_context.model.generate_response(
                        validation_prompt,
                        tools=[validation_func_spec],
                        tool_choice={"type": "tool", "name": validation_func_spec["name"]},
                        max_output_tokens=1024
                    )
                    break  # Success, exit retry loop
                except Exception as e:
                    retry_count += 1
                    last_error = e
                    if "500" in str(e) or "Internal" in str(e):
                        logger.warning(f"⚠️ Validation API error (attempt {retry_count}/{max_retries}): {e}")
                        if retry_count < max_retries:
                            await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                            continue
                    raise  # Re-raise non-500 errors
            
            if retry_count >= max_retries:
                logger.error(f"❌ Validation failed after {max_retries} retries: {last_error}")
                # Fall back to accepting the submission on API errors
                return {
                    "is_valid": True,
                    "reasoning": f"Validation API unavailable after {max_retries} retries, accepting submission"
                }
            
            # Track tokens
            if hasattr(worker_context, 'num_tokens'):
                worker_context.num_tokens.append(total_tokens)
            
            # Parse validation response
            if isinstance(response_data, dict) and response_data.get("type") == "tool_use":
                args = response_data.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        logger.error(f"❌ Failed to parse validation arguments: {args}")
                        args = {"is_sufficient": False, "is_legitimate": False, "reasoning": "Failed to parse validation response"}
                
                is_sufficient = args.get("is_sufficient", False)
                is_legitimate = args.get("is_legitimate", False)
                reasoning = args.get("reasoning", "No reasoning provided")
                missing_requirements = args.get("missing_requirements", "")
                cheating_evidence = args.get("cheating_evidence", "")
                
                is_valid = is_sufficient and is_legitimate
                
                # Create feedback message for failed validation
                feedback_message = ""
                if not is_valid:
                    # Include threshold info if relevant
                    threshold_info = ""
                    if success_threshold is not None:
                        try:
                            score_float = float(score)
                            threshold_info = f"\nCurrent {success_metric}: {score_float:.4f} (Required: >= {success_threshold:.4f})\n"
                        except:
                            pass
                    
                    feedback_message = f"❌ TASK COMPLETION REJECTED\n\nReasoning: {reasoning}{threshold_info}\n"
                    if not is_sufficient and missing_requirements:
                        feedback_message += f"\nMissing Requirements: {missing_requirements}\n"
                    if not is_legitimate and cheating_evidence:
                        feedback_message += f"\nCheating Evidence: {cheating_evidence}\n"
                    feedback_message += "\nPlease address these issues and complete the task properly."
                
                # Show validation result
                result_style = "green" if is_valid else "red"
                result_icon = "✅" if is_valid else "❌"
                result_text = "ACCEPTED" if is_valid else "REJECTED"
                
                result_panel = Panel(
                    f"{result_icon} VALIDATION {result_text}\n\n{reasoning}",
                    title="⚖️ Validation Result",
                    style=result_style
                )
                console.print(result_panel)
                
                return {
                    "is_valid": is_valid,
                    "is_sufficient": is_sufficient,
                    "is_legitimate": is_legitimate,
                    "reasoning": reasoning,
                    "missing_requirements": missing_requirements,
                    "cheating_evidence": cheating_evidence,
                    "feedback_message": feedback_message
                }
            else:
                logger.error("❌ Invalid validation response format")
                return {
                    "is_valid": False,
                    "reasoning": "Failed to get proper validation response from model",
                    "feedback_message": "❌ Validation failed due to model response error. Please try again."
                }
        else:
            logger.warning("⚠️ No model available for validation, accepting by default")
            return {"is_valid": True, "reasoning": "No validation model available"}
            
    except Exception as e:
        logger.error(f"❌ Validation error: {e}")
        # In case of validation error, err on the side of caution and reject
        return {
            "is_valid": False,
            "reasoning": f"Validation error: {str(e)}",
            "feedback_message": f"❌ Validation failed due to error: {str(e)}. Please try again."
        }

async def _handle_validation_failure(worker_context, validation_result: Dict[str, Any]):
    """
    Create a new node and inject the validation failure message to continue execution.
    """
    try:
        # Import here to avoid circular imports
        from agent.core.solution_tree import SolutionNode
        
        if hasattr(worker_context, 'journal') and worker_context.journal:
            # Get the most recent node (the one that just failed validation)
            recent_nodes = worker_context.journal.all_nodes_chronological
            if recent_nodes:
                failed_node = recent_nodes[-1]
                
                # Update the failed node's analysis to include validation rejection
                rejection_msg = f"\n\n❌ VALIDATION REJECTED!\n"
                rejection_msg += f"REASON: {validation_result.get('reasoning', '')}"
                
                if validation_result.get("missing_requirements"):
                    rejection_msg += f"\nMISSING: {validation_result.get('missing_requirements')}"
                
                if validation_result.get("cheating_evidence"):
                    rejection_msg += f"\n🚨 CHEATING: {validation_result.get('cheating_evidence')}"
                    rejection_msg += "\nYou MUST compute scores from actual predictions!"
                
                # Update the node's analysis to include rejection
                if failed_node.analysis:
                    failed_node.analysis += rejection_msg
                else:
                    failed_node.analysis = rejection_msg
                
                # Mark it as buggy so it shows up as failed in the journal
                failed_node.is_buggy = True
                
            # Create a new "implement" node with the validation feedback
            feedback_node = SolutionNode(
                id=str(uuid.uuid4()),
                stage="implement",
                parent_id=None,  # Root level - fresh start based on feedback
                created_at=time.time()
            )
            
            # Add metadata indicating this is a validation feedback node
            # Create a comprehensive approach hint that includes ALL validation feedback
            approach_hint = f"❌ YOUR PREVIOUS SUBMISSION WAS REJECTED!\n\n"
            approach_hint += f"REASON: {validation_result.get('reasoning', '')}\n"
            
            if validation_result.get("missing_requirements"):
                approach_hint += f"\nMISSING REQUIREMENTS:\n{validation_result.get('missing_requirements')}\n"
            
            if validation_result.get("cheating_evidence"):
                approach_hint += f"\n🚨 CHEATING DETECTED:\n{validation_result.get('cheating_evidence')}\n"
                approach_hint += "\nYou MUST compute the score from actual model predictions, NOT hardcode it!\n"
            
            approach_hint += "\nFIX THESE ISSUES AND RESUBMIT YOUR SOLUTION."
            
            feedback_node.metadata = {
                "validation_feedback": True,
                "rejection_reason": validation_result.get("reasoning", ""),
                "missing_requirements": validation_result.get("missing_requirements", ""),
                "cheating_evidence": validation_result.get("cheating_evidence", ""),
                "approach_hint": approach_hint
            }
            
            # Add the node to the journal
            worker_context.journal.add_node(feedback_node)
            
            # Update performance metrics
            if hasattr(worker_context, 'performance_metrics'):
                worker_context.performance_metrics["nodes_created"] = len(worker_context.journal.nodes)
                worker_context.performance_metrics["validation_rejections"] = worker_context.performance_metrics.get("validation_rejections", 0) + 1
            
            # Show feedback injection
            feedback_panel = Panel(
                f"🔄 Created new node {feedback_node.id[:8]} with validation feedback\n\n"
                f"The agent will now address the issues identified in the validation.",
                title="🔄 Continuing Execution",
                style="yellow"
            )
            console.print(feedback_panel)
            
            logger.info(f"Created feedback node {feedback_node.id} due to validation failure",
                       extra={'custom_tags': {'phase': 'agent', 'tool': 'return_fn'}})
            
    except Exception as e:
        logger.error(f"❌ Failed to create validation feedback node: {e}")
        # If we can't create the feedback node, at least log the issue