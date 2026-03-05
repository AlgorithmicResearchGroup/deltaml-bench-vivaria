"""
General error parsing and fix extraction system using LLM intelligence.
Extracts actionable fixes from error messages using AI rather than brittle regex.
"""

import json
import re
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
import asyncio
from agent.utils.general import logger


@dataclass
class ErrorFix:
    """Represents an extracted fix from an error message"""
    find: str  # What to look for in code (exact string or description)
    replace: str  # What to replace it with
    description: str  # Human-readable description
    line_numbers: Optional[List[int]] = None  # Specific lines to fix if known
    confidence: float = 1.0  # How confident we are this fix is correct


class LLMErrorParser:
    """Uses LLM to intelligently parse error messages and extract fixes"""
    
    def __init__(self, llm_caller=None):
        """Initialize with an LLM caller (will be injected by worker)"""
        self.llm_caller = llm_caller
    
    async def extract_fixes_from_error(self, error_text: str, code: str) -> List[ErrorFix]:
        """
        Use LLM to extract actionable fixes from error messages.
        """
        if not self.llm_caller:
            return []  # Fallback if no LLM available
        
        prompt = f"""You are an expert debugger. Analyze this error message and extract SPECIFIC, ACTIONABLE fixes.

ERROR MESSAGE:
```
{error_text}
```

CODE THAT CAUSED THE ERROR:
```python
{code}
```

Extract all fixes suggested by the error message. For each fix, provide:
1. The EXACT code to find (or description if not exact)
2. The EXACT code to replace it with
3. A brief description
4. Line numbers if you can determine them

Return a JSON array of fixes. Each fix should have:
- "find": exact string to find or description
- "replace": exact replacement
- "description": brief description
- "line_numbers": array of line numbers (optional)

Example response:
```json
[
  {{
    "find": "torch.load('file.pt')",
    "replace": "torch.load('file.pt', weights_only=False)",
    "description": "Add weights_only=False parameter",
    "line_numbers": [7]
  }}
]
```

Focus on fixes that are EXPLICITLY mentioned in the error message. Be precise.
"""
        
        try:
            response = await self.llm_caller(
                system="You are a debugging expert. Extract actionable fixes from error messages.",
                user=prompt,
                temperature=0.1  # Low temperature for precise extraction
            )
            
            # Parse the JSON response
            fixes_data = self._extract_json_from_response(response)
            if fixes_data:
                return [ErrorFix(**fix) for fix in fixes_data]
        except Exception as e:
            # Log error but don't crash
            print(f"Error parsing fixes with LLM: {e}")
        
        return []
    
    async def suggest_fixes_for_pattern(self, error_text: str, code: str, error_type: str) -> List[ErrorFix]:
        """
        Use LLM to suggest fixes for specific error patterns.
        """
        if not self.llm_caller:
            return []
        
        prompt = f"""You are debugging a {error_type} error. Suggest fixes based on common patterns.

ERROR:
```
{error_text}
```

CODE:
```python
{code}
```

Suggest practical fixes for this type of error. Consider:
- Common causes of {error_type} errors
- Best practices to prevent this error
- Any specific hints in the error message

Return a JSON array of fixes with the same format as before.
"""
        
        try:
            response = await self.llm_caller(
                system=f"You are an expert at fixing {error_type} errors in Python.",
                user=prompt,
                temperature=0.3  # Slightly higher for creative solutions
            )
            
            fixes_data = self._extract_json_from_response(response)
            if fixes_data:
                return [ErrorFix(**fix) for fix in fixes_data]
        except Exception:
            pass
        
        return []
    
    def _extract_json_from_response(self, response: str) -> Optional[List[Dict[str, Any]]]:
        """Extract JSON from LLM response, handling markdown code blocks."""
        import re
        
        # Try to find JSON in code blocks
        json_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try to parse the whole response as JSON
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # Try to find array-like structure
        array_match = re.search(r'\[[\s\S]*?\]', response)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass
        
        return None


class SmartErrorFixer:
    """Applies fixes extracted by LLMErrorParser"""
    
    @staticmethod
    def apply_fixes(code: str, fixes: List[ErrorFix]) -> Tuple[str, List[str]]:
        """
        Apply extracted fixes to code intelligently.
        Returns (fixed_code, list_of_applied_fixes)
        """
        fixed_code = code
        applied_fixes = []
        code_lines = fixed_code.split('\n')
        
        # Sort fixes by confidence and specificity
        sorted_fixes = sorted(fixes, key=lambda f: (f.confidence, len(f.find)), reverse=True)
        
        for fix in sorted_fixes:
            try:
                # If we have specific line numbers, use them
                if fix.line_numbers:
                    for line_num in fix.line_numbers:
                        if 0 <= line_num - 1 < len(code_lines):
                            old_line = code_lines[line_num - 1]
                            if fix.find in old_line:
                                code_lines[line_num - 1] = old_line.replace(fix.find, fix.replace)
                                applied_fixes.append(fix.description)
                                fixed_code = '\n'.join(code_lines)
                else:
                    # Apply fix globally
                    if fix.find in fixed_code:
                        fixed_code = fixed_code.replace(fix.find, fix.replace)
                        applied_fixes.append(fix.description)
                        code_lines = fixed_code.split('\n')  # Update lines for future fixes
            except Exception:
                # Skip problematic fixes
                continue
        
        return fixed_code, applied_fixes
    
    @staticmethod
    def extract_code_fix_blocks(error_text: str) -> List[Tuple[str, str]]:
        """
        Extract code blocks showing 'wrong' and 'correct' examples.
        Many error messages include these.
        """
        fixes = []
        
        # Look for "WRONG/CORRECT" or "Instead of/Use" code blocks
        wrong_correct_pattern = r"(?:WRONG|Instead of|Don't):\s*```(?:python)?\s*([^`]+)```\s*(?:CORRECT|Use|Do):\s*```(?:python)?\s*([^`]+)```"
        for match in re.finditer(wrong_correct_pattern, error_text, re.IGNORECASE | re.DOTALL):
            wrong_code = match.group(1).strip()
            correct_code = match.group(2).strip()
            fixes.append((wrong_code, correct_code))
        
        return fixes
    
    @staticmethod
    def generate_fix_prompt(error_text: str, current_code: str) -> str:
        """
        Generate a focused prompt that extracts fixes from error messages.
        This could be used to ask an LLM to parse complex errors.
        """
        return f"""
The following error occurred:
```
{error_text}
```

Current code:
```python
{current_code}
```

Extract the SPECIFIC FIX from the error message:
1. What exact change does the error message suggest?
2. What line(s) of code need to be modified?
3. What should they be changed to?

Provide the fix in this format:
FIND: <exact line to replace>
REPLACE: <exact replacement line>
"""


class SmartErrorFixer:
    """Applies fixes extracted by ErrorParser"""
    
    @staticmethod
    def apply_fixes(code: str, fixes: List[ErrorFix]) -> Tuple[str, List[str]]:
        """
        Apply extracted fixes to code.
        Returns (fixed_code, list_of_applied_fixes)
        """
        fixed_code = code
        applied_fixes = []
        
        # Sort fixes by confidence, apply highest confidence first
        sorted_fixes = sorted(fixes, key=lambda f: f.confidence, reverse=True)
        
        for fix in sorted_fixes:
            try:
                # Check if the find pattern exists in the code
                if fix.find in fixed_code:
                    # Apply the fix with simple string replacement
                    new_code = fixed_code.replace(fix.find, fix.replace)
                    
                    # Verify the fix changed something
                    if new_code != fixed_code:
                        fixed_code = new_code
                        applied_fixes.append(fix.description)
                        
                        # For high-confidence fixes, stop after first application
                        if fix.confidence > 0.9:
                            break
            except Exception as e:
                # Skip any errors in applying fixes
                logger.debug(f"Error applying fix: {e}")
                continue
        
        return fixed_code, applied_fixes
    
    @staticmethod
    def apply_code_block_fixes(code: str, wrong_correct_pairs: List[Tuple[str, str]]) -> Tuple[str, int]:
        """
        Apply fixes based on wrong/correct code examples.
        Returns (fixed_code, number_of_fixes_applied)
        """
        fixed_code = code
        fixes_applied = 0
        
        for wrong, correct in wrong_correct_pairs:
            # Normalize whitespace for comparison
            wrong_normalized = ' '.join(wrong.split())
            
            # Look for the wrong pattern in the code
            # This is simplified - in practice would need better matching
            if wrong in fixed_code:
                fixed_code = fixed_code.replace(wrong, correct)
                fixes_applied += 1
            elif wrong_normalized in ' '.join(fixed_code.split()):
                # Try normalized matching
                fixed_code = fixed_code.replace(wrong, correct)
                fixes_applied += 1
        
        return fixed_code, fixes_applied