"""
ML-specific error recovery using LLM intelligence instead of regex patterns.
"""

import asyncio
from typing import Dict, List, Optional, Any
from agent.core.solution_tree import SolutionNode


class LLMMLErrorRecovery:
    """Provides ML-specific error recovery strategies using LLM intelligence."""
    
    def __init__(self, llm_caller=None):
        """Initialize with an LLM caller"""
        self.llm_caller = llm_caller
    
    async def analyze_ml_error(self, error_text: str, code: str, error_type: str) -> Dict[str, Any]:
        """
        Use LLM to analyze ML errors and suggest fixes intelligently.
        """
        if not self.llm_caller:
            return self._fallback_strategy(error_type)
        
        prompt = f"""You are an ML debugging expert. Analyze this {error_type} error and provide specific fixes.

ERROR:
```
{error_text}
```

CODE:
```python
{code}
```

Provide a detailed analysis with:
1. Root cause of the error
2. Specific code changes needed (with exact replacements)
3. Best practices to prevent this error
4. Priority level (critical/high/medium/low)

Format your response as JSON:
{{
    "strategy": "brief_strategy_name",
    "root_cause": "explanation of why this happened",
    "suggestions": ["list", "of", "actionable", "suggestions"],
    "code_modifications": [
        {{
            "find": "exact code to find",
            "replace": "exact replacement",
            "description": "why this change helps"
        }}
    ],
    "priority": "high/medium/low/critical"
}}
"""
        
        try:
            response = await self.llm_caller(
                system=f"You are an expert at debugging {error_type} errors in ML code. Be specific and actionable.",
                user=prompt,
                temperature=0.2
            )
            
            # Parse response
            import json
            import re
            
            # Extract JSON from response
            json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', response)
            if json_match:
                return json.loads(json_match.group(1))
            
            # Try direct parse
            try:
                return json.loads(response)
            except:
                # Fallback to extracting key information
                return self._parse_text_response(response, error_type)
                
        except Exception as e:
            print(f"LLM error analysis failed: {e}")
            return self._fallback_strategy(error_type)
    
    async def check_experiment_tracking(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Use LLM to check if experiment tracking is properly integrated.
        """
        if not self.llm_caller:
            return None
        
        prompt = f"""Analyze this ML training code for experiment tracking setup:

```python
{code}
```

Check if the code has:
1. Proper experiment tracking (W&B, MLflow, TensorBoard, etc.)
2. Metrics logging at appropriate intervals
3. Hyperparameter logging
4. Model checkpointing

If tracking is missing or incomplete, provide specific code to add.

Return JSON with format:
{{
    "has_tracking": true/false,
    "tracking_system": "wandb/mlflow/tensorboard/none",
    "missing_components": ["list of missing tracking features"],
    "code_additions": [
        {{
            "location": "after imports/before training/in training loop",
            "code": "exact code to add"
        }}
    ]
}}
"""
        
        try:
            response = await self.llm_caller(
                system="You are an expert at ML experiment tracking best practices.",
                user=prompt,
                temperature=0.1
            )
            
            # Parse and return
            import json
            import re
            json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', response)
            if json_match:
                result = json.loads(json_match.group(1))
                
                # Convert to recovery format if tracking is missing
                if not result.get("has_tracking", True):
                    return {
                        "strategy": "add_experiment_tracking",
                        "suggestions": result.get("missing_components", ["Add experiment tracking"]),
                        "code_modifications": [
                            {
                                "find": "import torch",
                                "replace": "import torch\nimport wandb  # Auto-added for tracking",
                                "description": "Add experiment tracking import"
                            }
                        ] + self._convert_additions_to_mods(result.get("code_additions", [])),
                        "priority": "critical"
                    }
        except:
            pass
        
        return None
    
    async def analyze_cuda_oom(self, error_text: str, code: str) -> Dict[str, Any]:
        """
        Use LLM to analyze CUDA OOM errors with full context.
        """
        prompt = f"""Analyze this CUDA out-of-memory error and suggest specific fixes:

ERROR:
```
{error_text}
```

CODE:
```python
{code}
```

Consider:
1. Current batch size and how much to reduce it
2. Model size and potential optimizations
3. Gradient accumulation as an alternative
4. Mixed precision training
5. Gradient checkpointing for large models

Provide specific code changes, not generic advice.
"""
        
        response = await self.analyze_ml_error(error_text, code, "cuda_oom")
        
        # Enhance with CUDA-specific suggestions
        if "suggestions" in response:
            response["suggestions"].insert(0, "Monitor GPU memory with gpu_monitor before training")
        
        return response
    
    def _parse_text_response(self, response: str, error_type: str) -> Dict[str, Any]:
        """Parse non-JSON LLM responses into structured format."""
        # Extract suggestions (lines starting with - or numbers)
        import re
        suggestions = re.findall(r'(?:^|\n)(?:[-•*]|\d+\.)\s*(.+)', response)
        
        return {
            "strategy": f"llm_{error_type}_fix",
            "suggestions": suggestions if suggestions else ["Review the error and fix the issue"],
            "code_modifications": [],
            "priority": "medium"
        }
    
    def _fallback_strategy(self, error_type: str) -> Dict[str, Any]:
        """Fallback strategy when LLM is not available."""
        strategies = {
            "cuda_oom": {
                "strategy": "reduce_memory",
                "suggestions": ["Reduce batch size", "Enable gradient checkpointing", "Use mixed precision"],
                "code_modifications": [],
                "priority": "high"
            },
            "shape_mismatch": {
                "strategy": "fix_shapes", 
                "suggestions": ["Add shape debugging", "Check tensor dimensions"],
                "code_modifications": [],
                "priority": "high"
            },
            "nan_loss": {
                "strategy": "fix_nan",
                "suggestions": ["Reduce learning rate", "Check for division by zero", "Add gradient clipping"],
                "code_modifications": [],
                "priority": "critical"
            }
        }
        
        return strategies.get(error_type, {
            "strategy": "generic",
            "suggestions": ["Review the error message and fix the issue"],
            "code_modifications": [],
            "priority": "medium"
        })
    
    def _convert_additions_to_mods(self, additions: List[Dict]) -> List[Dict]:
        """Convert code additions to modification format."""
        mods = []
        for add in additions:
            location = add.get("location", "")
            code = add.get("code", "")
            
            if "after imports" in location:
                mods.append({
                    "find": "import torch",
                    "replace": f"import torch\n{code}",
                    "description": "Add after imports"
                })
            elif "training loop" in location:
                mods.append({
                    "find": "for epoch in",
                    "replace": f"{code}\nfor epoch in",
                    "description": "Add before training loop"
                })
        
        return mods