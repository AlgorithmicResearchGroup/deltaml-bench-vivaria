"""
Error analyzer for classifying and analyzing execution errors.
"""

import re
import logging
from typing import Optional
from agent.core.solution_tree import SolutionNode

logger = logging.getLogger(__name__)


class ErrorAnalyzer:
    """Analyzes and classifies execution errors for targeted debugging"""
    
    def classify_error_type(self, node: SolutionNode) -> str:
        """
        Classify the type of error to apply targeted debugging strategies.
        
        Args:
            node: Solution node with execution results
            
        Returns:
            Error type classification string
        """
        error_text = ""
        
        # Check multiple error sources
        if node.exec_error:
            error_text = node.exec_error.lower()
        elif node.exec_stderr:
            error_text = node.exec_stderr.lower()
        else:
            return "unknown"
        
        # More comprehensive error classification
        if "filenotfounderror" in error_text or "no such file" in error_text:
            return "missing_file"
        elif "importerror" in error_text or "modulenotfounderror" in error_text:
            return "missing_import"
        elif "nameerror" in error_text or "name" in error_text and "not defined" in error_text:
            return "undefined_variable"
        elif "syntaxerror" in error_text or "invalid syntax" in error_text:
            return "syntax_error"
        elif "timeout" in error_text or "timed out" in error_text:
            return "timeout"
        elif "permission" in error_text or "access denied" in error_text:
            return "permission_error"
        elif "json" in error_text and ("parse" in error_text or "decode" in error_text):
            return "json_parse_error"
        elif "torch.load" in error_text and "weights_only" in error_text:
            return "torch_load_error"
        elif "cuda" in error_text and "not available" in error_text:
            return "cuda_not_available"
        elif "torch" in error_text and "dtype" in error_text:
            return "dtype_mismatch"
        elif "assertionerror" in error_text:
            return "assertion_error"
        elif "indexerror" in error_text or "list index out of range" in error_text:
            return "index_error"
        elif "keyerror" in error_text:
            return "key_error"
        elif "valueerror" in error_text:
            return "value_error"
        elif "typeerror" in error_text:
            return "type_error"
        elif "attributeerror" in error_text:
            return "attribute_error"
        elif "zerodivisionerror" in error_text:
            return "zero_division"
        elif "memory" in error_text or "out of memory" in error_text:
            return "memory_error"
        elif "overflow" in error_text:
            return "overflow_error"
        else:
            return "general_runtime_error"
    
    def get_semantic_error_signature(self, node: SolutionNode, journal) -> str:
        """
        Create a context-aware error signature that considers specifics and progress.
        
        Args:
            node: Solution node with error
            journal: Solution journal for getting parent context
            
        Returns:
            Semantic error signature string
        """
        error_type = self.classify_error_type(node)
        error_text = (node.exec_error or node.exec_stderr or "").lower()
        
        # Extract specific identifiers from common errors
        specific_id = ""
        
        # For NameError/undefined variables - include the variable name
        if "name" in error_text and "is not defined" in error_text:
            match = re.search(r"name '(\w+)' is not defined", error_text)
            if match:
                specific_id = f":var_{match.group(1)}"
        
        # For FileNotFoundError - include the filename
        elif "filenotfounderror" in error_text or "no such file" in error_text:
            match = re.search(r"['\"]([^'\"]+\.[^'\"]+)['\"]", error_text)
            if match:
                specific_id = f":file_{match.group(1).replace('/', '_')}"
        
        # For ModuleNotFoundError - include the module name
        elif "no module named" in error_text:
            match = re.search(r"no module named ['\"]?(\w+)", error_text)
            if match:
                specific_id = f":module_{match.group(1)}"
        
        # For AttributeError - include the attribute name
        elif "attributeerror" in error_text:
            match = re.search(r"attribute ['\"]?(\w+)", error_text)
            if match:
                specific_id = f":attr_{match.group(1)}"
        
        # For KeyError - include the key
        elif "keyerror" in error_text:
            match = re.search(r"keyerror:? ['\"]?([^'\"\s]+)", error_text, re.IGNORECASE)
            if match:
                specific_id = f":key_{match.group(1)}"
        
        # Add context about what stage we're in
        stage_context = f"_stage_{node.stage}" if node.stage else ""
        
        # Include parent context to distinguish similar errors at different points
        parent_context = ""
        if node.parent_id:
            parent = journal.get_node(node.parent_id)
            if parent and hasattr(parent, 'approach_number'):
                parent_context = f"_approach_{parent.approach_number}"
        
        # Create a more specific signature
        signature = f"{error_type}{specific_id}{stage_context}{parent_context}"
        
        # For very generic errors, add a hash of the first line of code
        if not specific_id and node.code:
            first_line = node.code.split('\n')[0][:50]
            code_hash = str(hash(first_line))[-6:]
            signature += f"_code_{code_hash}"
        
        return signature
    
    def annotate_node_with_error_metadata(self, node: SolutionNode) -> None:
        """
        Annotate a node with error classification metadata.
        
        Args:
            node: Solution node to annotate
        """
        if node.is_buggy and (node.exec_error or node.exec_stderr):
            error_type = self.classify_error_type(node)
            
            # Store error classification in node metadata
            if not hasattr(node, 'error_metadata'):
                node.error_metadata = {}
            node.error_metadata['error_type'] = error_type
            
            logger.info(f"Node {node.id[:8]} classified with error type: {error_type}")