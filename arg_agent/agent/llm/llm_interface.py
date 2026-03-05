"""
Main LLM interface for handling all model interactions.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass

from agent.models.anthropic_async import AsyncAnthropicModel
from agent.models.openai_async import AsyncOpenAIModel
from agent.core.solution_tree import SolutionNode
from agent.core import prompts
from .response_parser import ResponseParser

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Structured response from LLM"""
    plan: Optional[str] = None
    code: Optional[str] = None
    analysis: Optional[str] = None
    raw_response: Optional[Any] = None
    total_tokens: int = 0
    tool_calls: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


class LLMInterface:
    """Handles all LLM interactions for the agent"""
    
    def __init__(
        self,
        model_provider: str,
        model_name: Optional[str] = None,
        system_prompt: str = "",
        run_id: str = "",
        success_metric: str = "accuracy",
        success_threshold: Optional[float] = None,
        enable_tool_use: bool = False
    ):
        """
        Initialize LLM interface.
        
        Args:
            model_provider: Provider name (anthropic, openai, google)
            model_name: Specific model version
            system_prompt: System prompt for the model
            run_id: Current run ID
            success_metric: Metric to optimize
            success_threshold: Target threshold
            enable_tool_use: Whether to enable tool usage
        """
        self.model_provider = model_provider.lower()
        self.model_name = model_name
        self.system_prompt = system_prompt
        self.run_id = run_id
        self.success_metric = success_metric
        self.success_threshold = success_threshold
        self.enable_tool_use = enable_tool_use
        
        self.model = None
        self.response_parser = ResponseParser()
        self.token_count = []
        
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize the appropriate model based on provider"""
        if self.model_provider in ['anthropic', 'claude']:
            self.model = AsyncAnthropicModel(
                self.system_prompt, 
                all_tools=None, 
                model_name=self.model_name
            )
        elif self.model_provider in ['openai', 'gpt']:
            self.model = AsyncOpenAIModel(
                self.system_prompt, 
                all_tools=None, 
                model_name=self.model_name
            )
        elif self.model_provider in ['google', 'gemini']:
            from agent.models.google_async import AsyncGoogleModel
            self.model = AsyncGoogleModel(
                self.system_prompt, 
                all_tools=None, 
                model_name=self.model_name
            )
        else:
            logger.warning(f"Unknown provider '{self.model_provider}', defaulting to Anthropic")
            self.model = AsyncAnthropicModel(
                self.system_prompt, 
                all_tools=None, 
                model_name=self.model_name
            )
            
        logger.info(f"Initialized model with provider: {self.model_provider}, model: {self.model_name or 'default'}")
    
    async def generate_solution(
        self,
        user_query: str,
        stage: str = "implement",
        node: Optional[SolutionNode] = None,
        previous_attempts: Optional[str] = None,
        data_overview: Optional[str] = None,
        approach_hint: Optional[str] = None,
        max_retries: int = 3
    ) -> LLMResponse:
        """
        Generate a solution (plan and code) for the given query.
        
        Args:
            user_query: The problem to solve
            stage: Current stage (implement, debug, improve)
            node: Current solution node
            previous_attempts: Summary of previous attempts
            data_overview: Data information
            approach_hint: Hint for approach
            max_retries: Maximum retries for API calls
            
        Returns:
            LLMResponse with plan and code
        """
        # Get appropriate prompt based on stage
        if stage == "implement":
            if self.enable_tool_use:
                prompt = prompts.get_tool_enhanced_draft_prompt(
                    task_desc=user_query,
                    journal_summary=previous_attempts or "",
                    data_overview=data_overview,
                    approach_hint=approach_hint,
                    success_metric=self.success_metric,
                    success_threshold=self.success_threshold
                )
            else:
                prompt = prompts.get_draft_prompt(
                    task_desc=user_query,
                    journal_summary=previous_attempts or "",
                    data_overview=data_overview,
                    approach_hint=approach_hint,
                    success_metric=self.success_metric,
                    success_threshold=self.success_threshold
                )
        elif stage == "debug" and node:
            node_dict = self._node_to_dict(node)
            prompt = prompts.get_debug_prompt(
                task_desc=user_query,
                buggy_node_dict=node_dict,
                journal_summary=previous_attempts or ""
            )
        elif stage == "improve" and node:
            node_dict = self._node_to_dict(node)
            prompt = prompts.get_improve_prompt(
                task_desc=user_query,
                parent_node_dict=node_dict,
                journal_summary=previous_attempts or "",
                data_overview=data_overview
            )
        else:
            raise ValueError(f"Invalid stage '{stage}' or missing node")
        
        # Generate response with retries
        for attempt in range(max_retries):
            try:
                if self.enable_tool_use and stage == "implement":
                    return await self._generate_with_tools(prompt)
                else:
                    return await self._generate_direct(prompt)
            except Exception as e:
                logger.error(f"LLM generation failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    return LLMResponse(error=str(e))
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
    
    async def _generate_direct(self, prompt: str) -> LLMResponse:
        """Generate response without tool usage"""
        try:
            # Standard text generation for Vivaria environment
            response_data, total_tokens, _, _ = await self.model.generate_response(
                prompt=prompt,
                max_output_tokens=16384
            )
            
            self.token_count.append(total_tokens)
            
            # Parse text response instead of tool calls for Vivaria compatibility
            # In Vivaria, solutions are saved as files rather than submitted via tools
            
            # Fallback to text parsing
            plan, code = self.response_parser.parse_direct_response(response_data)
            
            return LLMResponse(
                plan=plan,
                code=code,
                raw_response=response_data,
                total_tokens=total_tokens
            )
        except Exception as e:
            logger.error(f"Direct generation failed: {e}")
            return LLMResponse(error=str(e))
    
    async def _generate_with_tools(self, prompt: str) -> LLMResponse:
        """Generate response using tool calls"""
        try:
            response_data, total_tokens, _, _ = await self.model.generate_response(
                prompt=prompt,
                max_output_tokens=16384,
                tools=[prompts.get_submit_solution_spec()]
            )
            
            self.token_count.append(total_tokens)
            
            # Parse tool calls
            tool_calls = self.response_parser.extract_tool_calls(response_data)
            
            # For Vivaria compatibility, parse all tool calls normally
            # (submit_solution not used in Vivaria environment)
            
            # Parse text response for solution content
            plan, code = self.response_parser.parse_direct_response(response_data)
            
            return LLMResponse(
                plan=plan,
                code=code,
                raw_response=response_data,
                total_tokens=total_tokens,
                tool_calls=tool_calls
            )
            
        except Exception as e:
            logger.error(f"Tool generation failed: {e}")
            return LLMResponse(error=str(e))
    
    async def review_execution(
        self,
        node: SolutionNode,
        user_query: str
    ) -> Dict[str, Any]:
        """
        Review execution results and provide analysis.
        
        Args:
            node: Node with execution results
            user_query: Original problem
            
        Returns:
            Dictionary with review results
        """
        prompt = prompts.get_review_prompt(
            task_desc=user_query,
            code=node.code or "",
            stdout=node.exec_stdout or "",
            stderr=node.exec_stderr or "",
            error=node.exec_error or ""
        )
        
        try:
            review_spec = prompts.get_review_function_spec(
                metric_name=self.success_metric,
                metric_description=f"The {self.success_metric} value achieved"
            )
            
            response_data, total_tokens, _, _ = await self.model.generate_response(
                prompt=prompt,
                max_output_tokens=8192,
                tools=[review_spec]
            )
            
            self.token_count.append(total_tokens)
            
            # Parse review response
            review = self.response_parser.parse_review_response(response_data)
            
            # Ensure we have all required fields
            if 'execution_status' not in review:
                review['execution_status'] = 'error' if node.is_buggy else 'success'
            if 'metric_value' not in review:
                review['metric_value'] = None
            if 'summary' not in review:
                review['summary'] = "Review failed to generate summary"
            
            return review
            
        except Exception as e:
            logger.error(f"Review failed: {e}")
            return {
                'execution_status': 'error',
                'is_correct': False,
                'metric_value': None,
                'summary': f'Review failed: {str(e)}'
            }
    
    async def perform_reflection(
        self,
        failing_node: SolutionNode,
        error_type: str,
        error_count: int,
        user_query: str
    ) -> str:
        """
        Perform reflection on repeated failures.
        
        Args:
            failing_node: Node that failed
            error_type: Type of error
            error_count: Number of times this error occurred
            user_query: Original problem
            
        Returns:
            Reflection text with suggestions
        """
        prompt = f"""You are reflecting on repeated failures in solving a task.

TASK: {user_query}

ERROR TYPE: {error_type}
ERROR COUNT: {error_count} occurrences

FAILING CODE:
```python
{failing_node.code if failing_node.code else "# No code"}
```

ERROR MESSAGE:
{failing_node.exec_error if failing_node.exec_error else "No error message"}

STDOUT:
{failing_node.exec_stdout[:500] if failing_node.exec_stdout else "No output"}

Please provide:
1. Analysis of why this error keeps occurring
2. Specific suggestions for a different approach
3. Common pitfalls to avoid

Be concise and actionable."""
        
        try:
            response_data, total_tokens, _, _ = await self.model.generate_response(
                prompt=prompt,
                max_output_tokens=8192
            )
            
            self.token_count.append(total_tokens)
            
            return self.response_parser.extract_text(response_data)
        except Exception as e:
            logger.error(f"Reflection failed: {e}")
            return f"Reflection failed: {str(e)}"
    
    async def perform_threshold_reflection(
        self,
        best_node: SolutionNode,
        current_best: float,
        target_threshold: float,
        user_query: str
    ) -> str:
        """
        Reflect on why the current best doesn't meet threshold.
        
        Args:
            best_node: Best performing node
            current_best: Current best metric value
            target_threshold: Target threshold
            user_query: Original problem
            
        Returns:
            Reflection text with improvement suggestions
        """
        prompt = f"""You are an expert AI optimization specialist.
The current task is: {user_query}

We have achieved {self.success_metric}: {current_best:.4f}
But we need to reach the threshold: {target_threshold:.4f}
This is a gap of {((target_threshold - current_best) / target_threshold) * 100:.1f}%

Current best solution details:
- Plan: {best_node.plan[:500] if best_node.plan else 'N/A'}
- Code approach: {best_node.code[:500] if best_node.code else 'N/A'}...
- Analysis: {best_node.analysis if best_node.analysis else 'N/A'}

CRITICAL TASK:
1. Analyze why the current solution falls short of the threshold
2. Identify specific areas where performance can be improved
3. Suggest 2-3 concrete, actionable improvements that could close the gap

For machine learning tasks, consider:
- Model architecture improvements (deeper networks, different architectures)
- Hyperparameter tuning (learning rate, batch size, epochs)
- Data augmentation or preprocessing improvements
- Regularization techniques (dropout, batch normalization)
- Optimization algorithm changes
- Ensemble methods

Provide a focused analysis and specific recommendations."""
        
        try:
            response_data, total_tokens, _, _ = await self.model.generate_response(
                prompt=prompt,
                max_output_tokens=8192
            )
            
            self.token_count.append(total_tokens)
            
            return self.response_parser.extract_text(response_data)
        except Exception as e:
            logger.error(f"Threshold reflection failed: {e}")
            return f"Threshold reflection failed: {str(e)}"
    
    def get_total_tokens(self) -> int:
        """Get total tokens used"""
        return sum(self.token_count)
    
    def _node_to_dict(self, node: SolutionNode) -> Dict[str, Any]:
        """Convert SolutionNode to dictionary for prompts"""
        return {
            "id": node.id,
            "plan": node.plan,
            "code": node.code,
            "exec_stdout": node.exec_stdout,
            "exec_stderr": node.exec_stderr,
            "exec_error": node.exec_error,
            "analysis": node.analysis,
            "metric_name": node.metric_name,
            "metric_value": node.metric_value,
            "is_buggy": node.is_buggy,
        }
    
    async def close(self):
        """Close model connections"""
        if self.model:
            await self.model.close()