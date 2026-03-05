import json
from typing import Dict, Any

def evaluate_results(
    original_task: str,
    output_text: str,
    success_criteria: str = "",
    target_threshold: float = None
) -> Dict[str, Any]:
    """
    Tool for the model to evaluate if results meet task completion criteria.
    
    Args:
        original_task: The original task description
        output_text: The output text to evaluate
        success_criteria: Optional specific success criteria
        target_threshold: Optional numeric threshold
    
    Returns:
        Dictionary with evaluation results
    """
    
    # This tool is actually a placeholder - the real evaluation happens
    # in the model's reasoning when it calls this tool
    return {
        "tool_name": "evaluate_results",
        "original_task": original_task,
        "output_text": output_text,
        "success_criteria": success_criteria,
        "target_threshold": target_threshold,
        "evaluation_required": True
    }

# Tool definition for the registry
evaluate_results_tool_definition = {
    "type": "function",
    "function": {
        "name": "evaluate_results",
        "description": "Evaluate whether the output meets the original task requirements and determine if the task should be completed. Use this when you need to assess if results are satisfactory for task completion.",
        "parameters": {
            "type": "object",
            "properties": {
                "original_task": {
                    "type": "string",
                    "description": "The original task that was requested"
                },
                "output_text": {
                    "type": "string", 
                    "description": "The output text/results to evaluate"
                },
                "success_criteria": {
                    "type": "string",
                    "description": "Specific success criteria or requirements"
                },
                "target_threshold": {
                    "type": "number",
                    "description": "Numeric threshold for success (optional)"
                }
            },
            "required": ["original_task", "output_text"]
        }
    }
} 