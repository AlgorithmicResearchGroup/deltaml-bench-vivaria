import os
import json
import asyncio
import tiktoken
import traceback
from typing import Dict, Any, Tuple, Optional, List, Union
from openai import AsyncOpenAI
from dotenv import load_dotenv
from agent.utils.general import count_tokens, anthropic_to_openai, logger
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

load_dotenv(override=False)

class AsyncGoogleModel:
    def __init__(self, system_prompt: str, all_tools: Optional[List[Dict[str, Any]]] = None, model_name: Optional[str] = None):
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment variables.")
        self.system_prompt = system_prompt
        
        # Allow model override via parameter or env variable
        self.model_name = model_name or os.getenv("GOOGLE_MODEL", "gemini-2.5-pro-preview-03-25")
        
        self.oai_client = AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        self.default_tools = [anthropic_to_openai(tool) for tool in all_tools] if all_tools else []
        
        # Gemini 2.5 has massive context and output capabilities
        self.max_tokens_model_limit = 2097152  # 2M context window!
        self.max_output_tokens_api_limit = 32768  # Allow up to 32K output
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
            json_text = Text("JSON MODE: ENABLED (Depends on proxy support)\n", style="bold red")
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
        """Generate async response from Google API via OpenAI interface."""
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
                "temperature": temperature if temperature is not None else 0.7,  # Use provided temp or default
            }
            # Google's OpenAI proxy might not support max_tokens, following old_agent pattern

            if force_json_object:
                logger.info("Attempting JSON mode for Google; support depends on OpenAI proxy.")

            if tools:
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

            logger.debug(f"Google (OpenAI proxy) payload: {json.dumps(request_payload, indent=2)[:500]}...")

            # Add retry logic for Google API errors
            max_retries = 3
            retry_count = 0
            last_error = None
            
            while retry_count < max_retries:
                try:
                    response = await self.oai_client.chat.completions.create(**request_payload)
                    break  # Success, exit retry loop
                except Exception as e:
                    retry_count += 1
                    last_error = e
                    error_str = str(e)
                    
                    # Check if it's a retryable error
                    if any(err in error_str for err in ["500", "502", "503", "504", "Internal"]):
                        logger.warning(f"Google API error (attempt {retry_count}/{max_retries}): {e}")
                        if retry_count < max_retries:
                            # Exponential backoff: 2^retry_count seconds
                            await asyncio.sleep(2 ** retry_count)
                            continue
                    
                    # Not a retryable error, raise immediately
                    raise
            
            if retry_count >= max_retries:
                logger.error(f"Google API failed after {max_retries} retries")
                raise last_error

            processed_response, response_tokens_count = self._process_google_response(response)
            
            usage = response.usage
            api_prompt_tokens = usage.prompt_tokens if usage else 0
            api_completion_tokens = usage.completion_tokens if usage else response_tokens_count

            return processed_response, api_prompt_tokens + api_completion_tokens, api_prompt_tokens, api_completion_tokens

        except Exception as e:
            logger.error(f"Error in async Google response generation: {e}")
            traceback.print_exc()
            raise

    def _process_google_response(self, response) -> Tuple[Any, int]:
        """Process OpenAI-compatible response from Google endpoint."""
        choice = response.choices[0]
        message = choice.message
        output_data: Any = None

        if message.tool_calls:
            tool_call = message.tool_calls[0]
            if tool_call.type == "function":
                output_data = {
                    "type": "tool_use",
                    "name": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments) if isinstance(tool_call.function.arguments, str) else tool_call.function.arguments
                }
        elif message.content:
            output_data = message.content
        else:
            logger.warning(f"Google response has no tool_calls and no content. Finish reason: {choice.finish_reason}")
            raise ValueError(f"Google response has no tool_calls or content. Finish reason: {choice.finish_reason}")

        estimated_output_tokens = len(self.encode_text(json.dumps(output_data) if isinstance(output_data, dict) else str(output_data)))
        return output_data, estimated_output_tokens

    async def close(self):
        """Close the OpenAI client"""
        await self.oai_client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close() 