"""
Tool executor for handling tool-based solution generation.
"""

import json
import logging
import re
from typing import Dict, Any, Optional, Tuple, List
from agent.tools.tool_registry_async import AsyncTool, all_tools
# Removed submit_solution_spec import for Vivaria compatibility
from rich.console import Console
from rich.panel import Panel

logger = logging.getLogger(__name__)
console = Console()


class ToolExecutor:
    """Handles tool-based solution generation for the agent"""
    
    def __init__(self, worker_context: Any, memory_manager: Optional[Any] = None):
        """
        Initialize tool executor.
        
        Args:
            worker_context: The AsyncWorker instance for context
            memory_manager: Optional memory manager for saving tool executions
        """
        self.worker_context = worker_context
        self.memory_manager = memory_manager
        
    async def generate_solution_with_tools(
        self, 
        prompt: str, 
        max_iterations: int = 5
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate a solution using tools, then return plan and code for the existing pipeline.
        This allows tool use while maintaining all the existing validation and retry logic.
        
        Args:
            prompt: The prompt to start generation
            max_iterations: Maximum tool interaction iterations
            
        Returns:
            Tuple of (plan, code) or (None, None) if generation fails
        """
        messages = []
        iteration = 0
        collected_code = []
        plan_summary = []
        
        console.print(Panel(
            "🔧 Generating solution using tools",
            title="Tool-Enabled Generation",
            style="cyan"
        ))
        
        # Modified prompt to ask for solution generation
        generation_prompt = prompt + """

VIVARIA ENVIRONMENT INSTRUCTIONS:
- Work within the Vivaria environment using available tools
- Save your solution to solution.py in the working directory
- Use Vivaria's built-in actions for evaluation and submission
- Focus on implementing an optimal solution for the task

IMPLEMENTATION APPROACH:
1. Analyze the task requirements thoroughly
2. Design and implement your solution using appropriate tools
3. Save your final solution as solution.py
4. Test and validate your implementation
5. Use Vivaria's scoring system to evaluate performance
"""
        
        while iteration < max_iterations:
            iteration += 1
            
            try:
                # Build prompt with conversation history
                if iteration == 1:
                    current_prompt = generation_prompt
                else:
                    # Build conversation context
                    conversation_parts = [generation_prompt, "\n\nConversation history:"]
                    for msg in messages:
                        if msg["role"] == "assistant":
                            # Format assistant messages properly - show tool calls, not JSON
                            content = msg['content']
                            if isinstance(content, list) and len(content) > 0 and isinstance(content[0], dict) and content[0].get('type') == 'tool_use':
                                tool_info = content[0]
                                conversation_parts.append(f"\nAssistant used tool: {tool_info.get('name')} with arguments: {tool_info.get('arguments', {})}")
                            elif isinstance(content, dict) and content.get('type') == 'tool_use':
                                conversation_parts.append(f"\nAssistant used tool: {content.get('name')} with arguments: {content.get('arguments', {})}")
                            else:
                                conversation_parts.append(f"\nAssistant: {content}")
                        elif msg["role"] == "user":
                            conversation_parts.append(f"\nUser: {msg['content']}")
                    current_prompt = "\n".join(conversation_parts)
                
                # Call the LLM with available tools for Vivaria
                # Use model directly since we need tools support
                # TODO: Add tool support to LLM interface
                if not hasattr(self.worker_context, 'llm') or not self.worker_context.llm:
                    logger.error("LLM not initialized in worker context")
                    return None, None
                    
                response_data, total_tokens, _, _ = await self.worker_context.llm.model.generate_response(
                    current_prompt,
                    tools=all_tools,
                    max_output_tokens=8192
                )
                
                self.worker_context.llm.token_count.append(total_tokens)
                
                # Check if it's a tool call
                if isinstance(response_data, dict) and response_data.get("type") == "tool_use":
                    tool_name = response_data.get("name")
                    tool_params = response_data.get("arguments", {})
                    
                    console.print(f"🔧 Tool called: {tool_name}")
                    
                    # Removed submit_solution check for Vivaria compatibility
                    
                    # Execute other tools
                    tool_result = await self._execute_tool(tool_name, tool_params)
                    
                    # Track code writes for summary
                    if tool_name == "write_code":
                        collected_code.append(f"# Written to {tool_params.get('path', 'unknown')}:\n{tool_params.get('code', '')}")
                        plan_summary.append(f"Created {tool_params.get('path', 'file')}")
                    elif tool_name == "run_bash":
                        plan_summary.append(f"Executed: {tool_params.get('script', 'command')[:50]}...")
                    
                    # Add to conversation
                    messages.append({
                        "role": "assistant",
                        "content": response_data  # Store as dict, not wrapped in list
                    })
                    messages.append({
                        "role": "user", 
                        "content": f"Tool result: {json.dumps(tool_result)}"
                    })
                    
                elif isinstance(response_data, str):
                    console.print("📝 LLM provided text response instead of using tools")
                    # Print the actual response to help debug
                    console.print(Panel(
                        response_data[:500] + "..." if len(response_data) > 500 else response_data,
                        title="[red]Text Response (INCORRECT)[/red]",
                        border_style="red"
                    ))
                    messages.append({
                        "role": "assistant",
                        "content": response_data
                    })
                    messages.append({
                        "role": "user",
                        "content": """STOP! You are providing text responses, which is INCORRECT.

You MUST use tools ONLY. NO TEXT RESPONSES ALLOWED.

If you need to run more code or commands, use run_python, run_bash, or write_code tools.
NEVER respond with plain text. ONLY use tool calls."""
                    })
                    
            except Exception as e:
                logger.error(f"Error in tool-based generation: {e}")
                return None, None
        
        # If we exhausted iterations, compile collected code from tools
        if not collected_code:
            # Check if the LLM provided any code in text responses
            for msg in messages:
                if msg["role"] == "assistant" and isinstance(msg["content"], str):
                    content = msg["content"]
                    # Look for code blocks in the text
                    code_blocks = re.findall(r'```python\n(.*?)```', content, re.DOTALL)
                    if code_blocks:
                        collected_code.extend(code_blocks)
                        plan_summary.append("Extracted code from text response")
        
        if collected_code:
            plan = "Tool-based exploration:\n" + "\n".join(plan_summary)
            code = "\n\n".join(collected_code)
            return plan, code
            
        return None, None
    
    async def _execute_tool(self, tool_name: str, tool_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool and save the execution to memory.
        
        Args:
            tool_name: Name of the tool to execute
            tool_params: Parameters for the tool
            
        Returns:
            Tool execution result
        """
        tool_task = {
            "type": "function",
            "function": {
                "name": tool_name,
                "parameters": tool_params
            }
        }
        
        tool_instance = AsyncTool(tool_task, worker_context=self.worker_context)
        tool_result = await tool_instance.run_async()
        
        # Save tool execution to database immediately
        if self.memory_manager:
            await self.memory_manager.save_tool_execution(
                tool_name=tool_name,
                tool_params=tool_params,
                tool_result=tool_result
            )
        
        return tool_result