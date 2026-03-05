"""
Response parser for extracting structured data from LLM responses.
"""

import re
import json
import logging
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger(__name__)


class ResponseParser:
    """Parses LLM responses to extract plan, code, and other structured data"""
    
    def parse_direct_response(self, response_data: Any) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse a direct text response to extract plan and code.
        
        Args:
            response_data: Raw response from LLM
            
        Returns:
            Tuple of (plan, code)
        """
        # Extract text from response
        response_text = self._extract_text(response_data)
        if not response_text:
            return None, None
        
        # Try to extract plan and code sections
        plan = self._extract_section(response_text, "PLAN", "CODE")
        code = self._extract_code_block(response_text)
        
        # If no explicit sections, treat the whole response as code if it looks like code
        if not plan and not code and self._looks_like_code(response_text):
            code = response_text
            plan = "Execute the provided code"
        
        return plan, code
    
    def extract_tool_calls(self, response_data: Any) -> List[Dict[str, Any]]:
        """
        Extract tool calls from LLM response.
        
        Args:
            response_data: Raw response from LLM
            
        Returns:
            List of tool call dictionaries
        """
        tool_calls = []
        
        # Handle Anthropic format
        if hasattr(response_data, 'content') and isinstance(response_data.content, list):
            for item in response_data.content:
                if hasattr(item, 'type') and item.type == 'tool_use':
                    tool_calls.append({
                        'id': getattr(item, 'id', None),
                        'name': getattr(item, 'name', None),
                        'input': getattr(item, 'input', {})
                    })
        
        # Handle OpenAI format
        elif hasattr(response_data, 'choices') and response_data.choices:
            choice = response_data.choices[0]
            if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                for tool_call in choice.message.tool_calls:
                    tool_calls.append({
                        'id': tool_call.id,
                        'name': tool_call.function.name,
                        'input': json.loads(tool_call.function.arguments)
                    })
        
        # Handle list format (for compatibility)
        elif isinstance(response_data, list):
            for item in response_data:
                if isinstance(item, dict) and item.get('type') == 'tool_use':
                    tool_calls.append({
                        'id': item.get('id'),
                        'name': item.get('name'),
                        'input': item.get('input', {})
                    })
        
        return tool_calls
    
    def parse_review_response(self, response_data: Any) -> Dict[str, Any]:
        """
        Parse code review response.
        
        Args:
            response_data: Raw response from LLM
            
        Returns:
            Dictionary with review results
        """
        # Try to extract from function call first
        if hasattr(response_data, 'content') and isinstance(response_data.content, list):
            for item in response_data.content:
                if hasattr(item, 'type') and item.type == 'tool_use' and item.name == 'submit_code_review':
                    return item.input
        
        # Fallback to text parsing
        text = self._extract_text(response_data)
        if not text:
            return {
                'execution_status': 'error',
                'is_correct': False,
                'metric_value': None,
                'summary': 'Failed to parse review response'
            }
        
        # Try to extract structured data from text
        review = {
            'execution_status': 'error',
            'is_correct': False,
            'metric_value': None,
            'summary': text[:200]
        }
        
        # Look for patterns in text
        if 'success' in text.lower() and 'error' not in text.lower():
            review['execution_status'] = 'success'
        
        # Extract metric value
        metric_match = re.search(r'(?:score|accuracy|metric)[:\s]+([0-9.]+)', text, re.IGNORECASE)
        if metric_match:
            try:
                review['metric_value'] = float(metric_match.group(1))
            except ValueError:
                pass
        
        return review
    
    def extract_text(self, response_data: Any) -> str:
        """Public method to extract text from response"""
        return self._extract_text(response_data)
    
    def _extract_text(self, response_data: Any) -> str:
        """
        Extract text content from various response formats.
        
        Args:
            response_data: Raw response from LLM
            
        Returns:
            Extracted text string
        """
        if isinstance(response_data, str):
            return response_data
        
        # Handle Anthropic format
        if hasattr(response_data, 'content'):
            if isinstance(response_data.content, str):
                return response_data.content
            elif isinstance(response_data.content, list):
                text_parts = []
                for item in response_data.content:
                    if hasattr(item, 'type') and item.type == 'text' and hasattr(item, 'text'):
                        text_parts.append(item.text)
                return '\n'.join(text_parts)
        
        # Handle OpenAI format
        if hasattr(response_data, 'choices') and response_data.choices:
            choice = response_data.choices[0]
            if hasattr(choice, 'message') and hasattr(choice.message, 'content'):
                return choice.message.content
        
        # Handle list format
        if isinstance(response_data, list) and response_data:
            if hasattr(response_data[0], 'text'):
                return response_data[0].text
            elif isinstance(response_data[0], dict) and 'text' in response_data[0]:
                return response_data[0]['text']
        
        # Handle dict format
        if isinstance(response_data, dict):
            # Check if it's a tool use dict (from our processing)
            if response_data.get('type') == 'tool_use':
                # This is expected for tool responses, no need to warn
                return f"Tool use: {response_data.get('name', 'unknown')}"
            if 'content' in response_data:
                return response_data['content']
            elif 'text' in response_data:
                return response_data['text']
            # Only warn for unexpected dict formats
            logger.debug(f"Received dict response without text content: {response_data.get('type', 'unknown type')}")
            return ""
        
        logger.warning(f"Could not extract text from response: {type(response_data)}")
        return ""
    
    def _extract_section(self, text: str, start_marker: str, end_marker: Optional[str] = None) -> Optional[str]:
        """Extract a section between markers"""
        pattern = f"{start_marker}[:\s]*\n(.*?)(?:{end_marker}|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
    
    def _extract_code_block(self, text: str) -> Optional[str]:
        """Extract code from markdown code blocks or CODE section"""
        # Try markdown code blocks first
        code_block_match = re.search(r'```python\n(.*?)```', text, re.DOTALL)
        if code_block_match:
            return code_block_match.group(1).strip()
        
        # Try CODE section
        code_section = self._extract_section(text, "CODE", None)
        if code_section:
            # Remove markdown if present
            code_section = re.sub(r'^```python\n|```$', '', code_section.strip())
            return code_section
        
        return None
    
    def _looks_like_code(self, text: str) -> bool:
        """Check if text looks like Python code"""
        code_indicators = ['import ', 'def ', 'class ', 'if __name__', 'print(', '=', '(', ')']
        indicator_count = sum(1 for indicator in code_indicators if indicator in text)
        return indicator_count >= 3