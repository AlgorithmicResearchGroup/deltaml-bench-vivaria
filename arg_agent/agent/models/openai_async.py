import os
import json
import asyncio
import tiktoken
import traceback
from typing import Dict, Any, Tuple, Optional, List, Union
from openai import AsyncOpenAI
from dotenv import load_dotenv
from agent.utils.general import count_tokens, anthropic_to_openai, logger

# Import config reader for single source of truth
try:
    from agent.config import get_model_name
except ImportError:
    # Fallback if config module not available
    def get_model_name():
        return "o3"
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

load_dotenv(override=False)


class AsyncOpenAIModel:
    def __init__(self, system_prompt: str, all_tools: Optional[List[Dict[str, Any]]] = None, model_name: Optional[str] = None):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables.")
        self.system_prompt = system_prompt
        self.oai_client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE_URL")
        )
        self.default_tools = [anthropic_to_openai(tool) for tool in all_tools] if all_tools else []
        # Use provided model_name, then environment variable, then manifest config as fallback
        self.model_name = model_name or os.getenv("OPENAI_MODEL") or get_model_name()
        
        # Set limits based on model - be generous!
        if self.model_name.startswith("gpt-4"):
            self.max_tokens_model_limit = 128000
            self.max_output_tokens_api_limit = 16384  # GPT-4 can do 16K output
        elif self.model_name.startswith(("o1", "o3")):
            self.max_tokens_model_limit = 200000  # o-series have large contexts
            self.max_output_tokens_api_limit = 32768  # Allow up to 32K output
        else:
            self.max_tokens_model_limit = 128000
            self.max_output_tokens_api_limit = 16384
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.console = Console()

    def encode_text(self, text: str) -> list:
        """Encode text to tokens"""
        # Allow all special tokens to be encoded as normal text
        return self.encoding.encode(text, disallowed_special=())

    def decode_tokens(self, tokens: list) -> str:
        """Decode tokens to text"""
        return self.encoding.decode(tokens)

    async def truncate_prompt_async(self, prompt: str, max_tokens: int) -> str:
        """Async prompt truncation using thread pool"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.truncate_prompt, prompt, max_tokens
        )

    def truncate_prompt(self, prompt: str, max_tokens: int) -> str:
        """Truncate prompt to fit within token limit"""
        tokens = self.encode_text(prompt)
        if len(tokens) <= max_tokens:
            return prompt
        return self.decode_tokens(tokens[:max_tokens])
    
    def _log_model_input(self, prompt: str, tools: Optional[List[Dict[str, Any]]] = None, 
                        tool_choice: Optional[Union[str, Dict[str, Any]]] = None, 
                        force_json_object: bool = False, max_output_tokens: int = 2048):
        """Log what the model is seeing with rich formatting"""
        # Create the main panel
        content_parts = []
        
        # Add system prompt section
        if self.system_prompt:
            system_text = Text("SYSTEM PROMPT:\n", style="bold yellow")
            system_text.append(self.system_prompt)
            content_parts.append(system_text)
            content_parts.append(Text("\n" + "="*80 + "\n", style="dim"))
        
        # Add user prompt section
        user_text = Text("USER PROMPT:\n", style="bold cyan")
        user_text.append(prompt)
        content_parts.append(user_text)
        
        # Add tools section if present
        if tools:
            content_parts.append(Text("\n" + "="*80 + "\n", style="dim"))
            tools_text = Text("AVAILABLE TOOLS:\n", style="bold green")
            for tool in tools[:5]:  # Show first 5 tools
                # Handle both Anthropic and OpenAI formats
                if "function" in tool:
                    tool_name = tool.get('function', {}).get('name', 'Unknown')
                else:
                    tool_name = tool.get('name', 'Unknown')
                tools_text.append(f"- {tool_name}\n")
            if len(tools) > 5:
                tools_text.append(f"... and {len(tools) - 5} more tools")
            content_parts.append(tools_text)
        
        # Add tool choice if present
        if tool_choice:
            content_parts.append(Text("\n" + "="*80 + "\n", style="dim"))
            choice_text = Text("TOOL CHOICE:\n", style="bold magenta")
            choice_text.append(str(tool_choice) if isinstance(tool_choice, str) else json.dumps(tool_choice, indent=2))
            content_parts.append(choice_text)
        
        # Add JSON mode if enabled
        if force_json_object:
            content_parts.append(Text("\n" + "="*80 + "\n", style="dim"))
            json_text = Text("JSON MODE: ENABLED\n", style="bold red")
            content_parts.append(json_text)
        
        # Add token info
        content_parts.append(Text("\n" + "="*80 + "\n", style="dim"))
        token_text = Text("TOKEN INFO:\n", style="bold blue")
        token_text.append(f"Max output tokens: {max_output_tokens}\n")
        token_text.append(f"Model: {self.model_name}")
        content_parts.append(token_text)
        
        # Combine all parts
        final_content = Text()
        for part in content_parts:
            final_content.append(part)
        
        # Create and print the panel
        panel = Panel(
            final_content,
            title="[bold red]🔥 THIS IS WHAT THE MODEL IS SEEING 🔥[/bold red]",
            border_style="bold red",
            padding=(1, 2),
            expand=True
        )
        
        # self.console.print("\n")
        # self.console.print(panel)
        # self.console.print("\n")

    async def generate_response(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        force_json_object: bool = False,
        max_output_tokens: int = 2048,
        temperature: Optional[float] = None,
    ) -> Tuple[Any, int, int, int]:
        """Generate async response from OpenAI API."""
        try:
            # Log what the model is seeing
            self._log_model_input(prompt, tools, tool_choice, force_json_object, max_output_tokens)
            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            messages.append({"role": "user", "content": prompt})

            current_prompt_tokens = sum(len(self.encode_text(msg["content"])) for msg in messages)
            
            available_tokens_for_user_prompt_part = self.max_tokens_model_limit - (current_prompt_tokens - len(self.encode_text(prompt))) - max_output_tokens - 100
            
            if len(self.encode_text(prompt)) > available_tokens_for_user_prompt_part:
                truncated_user_prompt = await self.truncate_prompt_async(prompt, available_tokens_for_user_prompt_part)
                messages[-1]["content"] = truncated_user_prompt

            request_payload: Dict[str, Any] = {
                "model": self.model_name,
                "messages": messages,
            }
            
            # Use max_completion_tokens for o-series models
            if self.model_name.startswith(("o1", "o3")):
                request_payload["max_completion_tokens"] = min(max_output_tokens, self.max_output_tokens_api_limit)
                # o-series models don't support temperature
            else:
                request_payload["max_tokens"] = min(max_output_tokens, self.max_output_tokens_api_limit)
                # Add temperature for non-o-series models
                if temperature is not None:
                    request_payload["temperature"] = temperature
                else:
                    request_payload["temperature"] = 0.7  # Default temperature

            if force_json_object:
                request_payload["response_format"] = {"type": "json_object"}
                if tools or tool_choice:
                    logger.warning("JSON mode requested with tools/tool_choice. This may lead to unexpected behavior.")
            elif tools:
                # Convert tools to OpenAI format
                request_payload["tools"] = [anthropic_to_openai(tool) for tool in tools]
                # Convert tool_choice if provided
                if tool_choice:
                    if isinstance(tool_choice, dict) and tool_choice.get("type") == "tool":
                        # Convert Anthropic format to OpenAI format
                        request_payload["tool_choice"] = {
                            "type": "function",
                            "function": {"name": tool_choice["name"]}
                        }
                    else:
                        request_payload["tool_choice"] = tool_choice

            logger.debug(f"OpenAI payload: {json.dumps(request_payload, indent=2)[:500]}...")
            
            response = await self.oai_client.chat.completions.create(**request_payload)

            processed_response, response_tokens_count = self._process_openai_response(response)
            
            usage = response.usage
            api_prompt_tokens = usage.prompt_tokens if usage else 0
            api_completion_tokens = usage.completion_tokens if usage else response_tokens_count

            return processed_response, api_prompt_tokens + api_completion_tokens, api_prompt_tokens, api_completion_tokens

        except Exception as e:
            logger.error(f"Error in async OpenAI response generation: {e}")
            traceback.print_exc()
            raise

    def _process_openai_response(self, response) -> Tuple[Any, int]:
        """
        Process OpenAI response.
        Handles text, tool calls, and JSON object responses.
        """
        choice = response.choices[0]
        message = choice.message
        output_data: Any = None

        if message.tool_calls:
            tool_call = message.tool_calls[0]
            if tool_call.type == "function":
                output_data = {
                    "type": "tool_use",
                    "name": tool_call.function.name,
                    "arguments": self._safe_parse_json(tool_call.function.arguments) if isinstance(tool_call.function.arguments, str) else tool_call.function.arguments
                }
        elif message.content:
            output_data = message.content 
        else:
            logger.warning(f"OpenAI response has no tool_calls and no content. Finish reason: {choice.finish_reason}")
            raise ValueError(f"OpenAI response has no tool_calls or content. Finish reason: {choice.finish_reason}")

        estimated_output_tokens = len(self.encode_text(json.dumps(output_data) if isinstance(output_data, dict) else str(output_data)))
        return output_data, estimated_output_tokens

    def _safe_parse_json(self, json_str: str) -> Any:
        """Safely parse JSON with error handling and recovery attempts."""
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parsing error: {e}")
            
            # Try to fix common issues
            # 1. Truncated strings - close them
            if "Unterminated string" in str(e):
                # Add closing quote and bracket
                fixed = json_str + '"}' 
                try:
                    return json.loads(fixed)
                except:
                    pass
            
            # 2. Try to extract valid JSON from partial response
            try:
                # Find the last valid closing brace/bracket
                for i in range(len(json_str) - 1, -1, -1):
                    if json_str[i] in ['}', ']']:
                        try:
                            return json.loads(json_str[:i+1])
                        except:
                            continue
            except:
                pass
            
            # If all else fails, return a safe default
            logger.error(f"Could not parse JSON, returning default: {json_str[:100]}...")
            return {"error": "JSON parsing failed", "raw": json_str[:200]}
    
    async def close(self):
        """Close the OpenAI client"""
        await self.oai_client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close() 