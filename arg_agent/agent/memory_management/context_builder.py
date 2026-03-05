"""
Context builder for creating prompts with memory and journal information.
"""

import logging
from typing import Optional, Dict, Any
from agent.core.solution_tree import SolutionJournal, SolutionNode

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds context for LLM prompts from journal and memory"""
    
    def __init__(self, journal: SolutionJournal, user_query: str):
        self.journal = journal
        self.user_query = user_query
    
    def build_implement_context(
        self,
        memory_context: str,
        node: SolutionNode
    ) -> str:
        """Build context for implement stage"""
        # Get journal summary
        journal_summary = self.journal.generate_summary_for_llm(max_entries=15, include_code=True)
        
        # Combine contexts
        full_context = journal_summary + memory_context
        
        # Check for special cases
        if node.metadata.get("reason") == "debug_exhausted":
            reflection_text = node.metadata.get("reflection", "No specific reflection recorded.")
            
            warning_context = f"""
🚨 DEBUGGING REQUIRED 🚨

The previous approach failed repeatedly. Here's the debugging analysis:

{reflection_text}

🛑 YOUR TASK:
1. First, implement the IMMEDIATE FIX suggested above
2. Add the DEBUG STEPS to understand what's happening
3. If that doesn't work, implement the BACKUP PLAN
4. DO NOT repeat the same failing code without changes

⚠️ Follow the concrete debugging steps above. Don't philosophize - just fix the specific issue.

"""
            
            # Minimal context to avoid contamination
            minimal_context = "\n💡 Focus on your reflection above rather than repeating past attempts.\n"
            return warning_context + minimal_context
        
        return full_context
    
    def build_debug_context(
        self,
        memory_context: str,
        node: SolutionNode,
        parent_node: SolutionNode,
        error_type: str,
        debug_attempts: int,
        max_attempts: int = 10,
        repeat_error_threshold: int = 3
    ) -> str:
        """Build context for debug stage with error-specific guidance"""
        # Get journal summary
        journal_summary = self.journal.generate_summary_for_llm(max_entries=15, include_code=True)
        
        urgency_level = "LOW" if debug_attempts <= 3 else "MEDIUM" if debug_attempts <= 7 else "HIGH"
        
        enhanced_debug_context = f"""
🚨 DEBUGGING SESSION #{debug_attempts}/{max_attempts}
ERROR TYPE: {error_type}
URGENCY: {urgency_level}
REMAINING ATTEMPTS: {max_attempts - debug_attempts}

⚠️ CRITICAL: This is attempt #{debug_attempts} out of {max_attempts} maximum attempts.
If this debugging session fails, you only have {max_attempts - debug_attempts} more chances
before this approach is abandoned!

{"🔥 FINAL ATTEMPTS - BE EXTRA CAREFUL!" if debug_attempts > 7 else ""}
"""
        if debug_attempts > repeat_error_threshold:
            enhanced_debug_context += (
                f"\n\n!! URGENT: This is debug attempt #{debug_attempts} for this specific issue. "
                f"Previous fixes were not sufficient. Your new plan and code MUST try a "
                f"SUBSTANTIALLY DIFFERENT way to fix the '{error_type}' error. "
                f"Identify the core misunderstanding and address it. DO NOT make minor tweaks.\n"
            )
        
        # Add error-specific guidance
        enhanced_debug_context += self._get_error_specific_guidance(error_type, debug_attempts)
        
        return journal_summary + memory_context + enhanced_debug_context
    
    def build_improve_context(
        self,
        memory_context: str,
        node: SolutionNode,
        parent_node: SolutionNode
    ) -> str:
        """Build context for improve stage"""
        # Get journal summary
        journal_summary = self.journal.generate_summary_for_llm(max_entries=15, include_code=True)
        
        # Combine contexts
        full_context = journal_summary + memory_context
        
        # Check if this is a threshold-targeting improvement
        if node.metadata.get("improvement_type") == "threshold_targeting":
            threshold_context = f"""
🎯 CRITICAL THRESHOLD REQUIREMENT:
You MUST achieve at least {node.metadata['target_threshold']:.4f} {node.metadata.get('success_metric', 'metric')}.
Current best is only {node.metadata['current_best']:.4f} (gap: {node.metadata['gap_percentage']:.1f}%).

THRESHOLD IMPROVEMENT ANALYSIS:
{node.metadata.get('reflection', 'No reflection available')}

{node.metadata.get('approach_hint', '')}
"""
            return full_context + threshold_context
        
        return full_context
    
    def _get_error_specific_guidance(self, error_type: str, debug_attempts: int) -> str:
        """Get error-specific debugging guidance"""
        if error_type == "missing_file":
            return f"""
❌ MISSING FILE ERROR - SYSTEMATIC APPROACH REQUIRED!
STEP-BY-STEP DEBUGGING (attempt #{debug_attempts}):
1. FIRST - List ALL files in current directory:
   ```python
   import os
   print("=== CURRENT DIRECTORY ANALYSIS ===")
   print("Current dir:", os.getcwd())
   print("All files/dirs:", os.listdir('.'))
   # Check common data locations
   for check_dir in ['.', 'data', 'dataset', 'datasets', 'train', 'test']:
       if os.path.exists(check_dir):
           print(f"Found {{check_dir}}:", os.listdir(check_dir)) 
   ```
2. THEN - Check if dataset needs to be downloaded or path is incorrect.
3. FINALLY - Use ONLY files that actually exist or create missing ones!
⚠️ ATTEMPT #{debug_attempts}: Focus on finding the ACTUAL file structure, not assumptions!
"""
        elif error_type == "missing_import":
            return f"""
❌ IMPORT ERROR - SYSTEMATIC APPROACH REQUIRED!
STEP-BY-STEP DEBUGGING (attempt #{debug_attempts}):
1. Check the exact module name that failed.
2. Try to install it using `pip install failing_module_name`.
   ```python
   import subprocess
   import sys
   try:
       subprocess.check_call([sys.executable, "-m", "pip", "install", "name_of_module_that_failed"])
       print("Installation attempt complete. Try importing again.")
   except subprocess.CalledProcessError as e:
       print(f"Pip install failed: {{e}}")
   ```
⚠️ ATTEMPT #{debug_attempts}: Ensure the module is installed and the import statement is correct.
"""
        elif error_type == "undefined_variable":
            return f"""
❌ NAME ERROR - SYSTEMATIC APPROACH REQUIRED!
STEP-BY-STEP DEBUGGING (attempt #{debug_attempts}):
1. Identify the exact undefined variable from the error message.
2. Check for typos (case-sensitive) and ensure it was assigned before use.
3. Check variable scope.
⚠️ ATTEMPT #{debug_attempts}: Define all variables before use with correct spelling and scope!
"""
        elif error_type == "cuda_not_available":
            return f"""
❌ CUDA NOT AVAILABLE - SIMPLE FIX!
DIRECT FIX (attempt #{debug_attempts}):
PyTorch can't find CUDA. Use CPU instead:

```python
# Add this at the start of your code:
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Using device: {{device}}")

# Then use .to(device) on models and tensors:
model = model.to(device)
data = data.to(device)
```

⚠️ The code will run on CPU - might be slower but will work!
"""
        elif error_type == "dtype_mismatch":
            return f"""
❌ DTYPE MISMATCH - SIMPLE FIX!
DIRECT FIX (attempt #{debug_attempts}):
PyTorch tensors have mismatched data types. Common fixes:

```python
# Convert to float32 (most common for neural networks):
tensor = tensor.float()  # or tensor.to(torch.float32)

# Or match the model's dtype:
data = data.to(model.dtype)

# For mixed precision, ensure consistency:
model = model.float()
inputs = inputs.float()
```

⚠️ Neural networks typically expect float32 inputs!
"""
        
        return ""  # No specific guidance for other error types