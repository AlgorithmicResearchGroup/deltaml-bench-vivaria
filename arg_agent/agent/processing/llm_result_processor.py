"""
Result processing using LLM intelligence for better answer extraction.
"""

from typing import Optional, Dict, List, Any
from agent.core.solution_tree import SolutionNode
import asyncio


class LLMResultProcessor:
    """Processes results using LLM for intelligent answer extraction."""
    
    def __init__(self, llm_caller=None):
        """Initialize with an LLM caller"""
        self.llm_caller = llm_caller
    
    async def extract_answer(self, node: SolutionNode, task_description: str) -> Optional[str]:
        """
        Use LLM to intelligently extract the answer from execution output.
        """
        if not self.llm_caller:
            return self._fallback_extraction(node)
        
        # Gather all available context
        context = {
            "stdout": node.exec_stdout or "",
            "stderr": node.exec_stderr or "",
            "analysis": node.analysis or "",
            "code": node.code or ""
        }
        
        prompt = f"""Extract the final answer from this execution output.

TASK DESCRIPTION:
{task_description}

EXECUTION OUTPUT:
```
{context['stdout']}
```

ERROR OUTPUT (if any):
```
{context['stderr']}
```

ANALYSIS/REVIEW:
{context['analysis']}

Based on the task description, what is the FINAL ANSWER that should be submitted?
- For numerical tasks: extract the final number
- For classification: extract the class label or prediction
- For yes/no questions: extract the boolean answer
- For code tasks: extract the complete solution code
- For lists/arrays: extract the full list

Return ONLY the answer, nothing else. If you cannot determine the answer, return "UNABLE_TO_EXTRACT".
"""
        
        try:
            response = await self.llm_caller(
                system="You are an expert at extracting answers from program output. Be precise and extract only the final answer.",
                user=prompt,
                temperature=0.0  # Deterministic extraction
            )
            
            answer = response.strip()
            if answer and answer != "UNABLE_TO_EXTRACT":
                return answer
                
        except Exception as e:
            print(f"LLM answer extraction failed: {e}")
        
        # Fallback to simple extraction
        return self._fallback_extraction(node)
    
    async def extract_metrics(self, node: SolutionNode, metric_name: str) -> Optional[float]:
        """
        Use LLM to extract specific metrics from output.
        """
        if not self.llm_caller or not node.exec_stdout:
            return None
        
        prompt = f"""Extract the {metric_name} value from this output:

```
{node.exec_stdout}
```

Look for patterns like:
- {metric_name}: 0.95
- {metric_name} = 0.95
- Final {metric_name}: 95%
- Test {metric_name}: 0.95

Return ONLY the numeric value (as a decimal between 0 and 1 for percentages).
If the value is given as a percentage (e.g., 95%), convert it to decimal (0.95).
If you cannot find the metric, return "NOT_FOUND".
"""
        
        try:
            response = await self.llm_caller(
                system=f"You are an expert at extracting {metric_name} metrics from ML output.",
                user=prompt,
                temperature=0.0
            )
            
            value = response.strip()
            if value and value != "NOT_FOUND":
                try:
                    # Handle percentage conversion
                    if '%' in value:
                        return float(value.replace('%', '')) / 100.0
                    return float(value)
                except ValueError:
                    pass
                    
        except Exception:
            pass
        
        return None
    
    async def classify_output_type(self, output: str, task_description: str) -> str:
        """
        Use LLM to classify what type of output this is.
        """
        if not self.llm_caller:
            return "unknown"
        
        prompt = f"""Classify the type of output based on the task and output content.

TASK:
{task_description}

OUTPUT:
```
{output[:1000]}  # First 1000 chars
```

Classify as one of:
- "numeric" (single number answer)
- "classification" (class label/category)
- "regression" (continuous value)
- "code" (programming solution)
- "list" (array/list of values)
- "text" (free-form text answer)
- "boolean" (yes/no, true/false)
- "error" (execution failed)

Return ONLY the classification type.
"""
        
        try:
            response = await self.llm_caller(
                system="You are an expert at classifying program output types.",
                user=prompt,
                temperature=0.0
            )
            
            return response.strip().lower()
            
        except Exception:
            return "unknown"
    
    def _fallback_extraction(self, node: SolutionNode) -> Optional[str]:
        """Simple fallback extraction when LLM is not available."""
        if node.exec_stdout:
            lines = node.exec_stdout.strip().split('\n')
            
            # Look for answer patterns
            for line in reversed(lines):  # Start from end
                line_lower = line.lower()
                if any(marker in line_lower for marker in ['answer:', 'result:', 'final:']):
                    # Extract after marker
                    for marker in [':', '=']:
                        if marker in line:
                            return line.split(marker, 1)[1].strip()
            
            # Return last non-empty line
            for line in reversed(lines):
                if line.strip():
                    return line.strip()
        
        return None
    
    async def validate_answer_format(self, answer: str, expected_format: str) -> Dict[str, Any]:
        """
        Use LLM to validate if the answer matches expected format.
        """
        if not self.llm_caller:
            return {"valid": True, "issues": []}
        
        prompt = f"""Validate if this answer matches the expected format.

ANSWER:
{answer}

EXPECTED FORMAT:
{expected_format}

Check for:
1. Correct data type
2. Proper formatting
3. Valid range/constraints
4. Completeness

Return JSON:
{{
    "valid": true/false,
    "issues": ["list of any format issues"],
    "corrected_answer": "properly formatted answer if fixable, or null"
}}
"""
        
        try:
            response = await self.llm_caller(
                system="You are an expert at validating answer formats.",
                user=prompt,
                temperature=0.0
            )
            
            import json
            import re
            json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', response)
            if json_match:
                return json.loads(json_match.group(1))
                
        except Exception:
            pass
        
        return {"valid": True, "issues": []}