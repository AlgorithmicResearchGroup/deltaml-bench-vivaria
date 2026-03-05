import os
import json
import asyncio
import aiohttp
import tiktoken
from typing import Dict, Any, Tuple, Optional, List
from dotenv import load_dotenv
from agent.utils.general import count_tokens, logger
import traceback

# Import config reader for single source of truth (fallback for non-OpenAI models)
try:
    from agent.config import get_model_name
except ImportError:
    # Fallback if config module not available
    def get_model_name():
        return "claude-3-opus-20240229"
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

load_dotenv(override=False)  # Don't override existing environment variables

class AsyncAnthropicModel:
    def __init__(self, system_prompt: str, all_tools: Optional[list] = None, model_name: Optional[str] = None):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment variables.")
        
        # Clean the API key of any whitespace/newlines
        self.api_key = self.api_key.strip().replace('\n', '').replace('\r', '').replace('"', '')
        self.system_prompt = system_prompt
        self.all_tools = all_tools if all_tools is not None else []
        # Allow model override via parameter or env variable
        # Default to the best available model
        # Use provided model_name, then environment variable, then manifest config as fallback
        # Note: For Anthropic models, we use Claude as fallback if manifest specifies OpenAI model
        fallback_model = get_model_name() if not get_model_name().startswith(('gpt', 'o1', 'o3')) else "claude-3-opus-20240229"
        self.model_name = model_name or os.getenv("ANTHROPIC_MODEL", fallback_model)
        
        # Set limits based on model
        if "claude-3-5" in self.model_name:
            self.max_tokens_api_limit = 8192  # Claude 3.5 supports 8K output
            self.model_context_window = 200000
        elif "claude-3-opus" in self.model_name:
            self.max_tokens_api_limit = 4096
            self.model_context_window = 200000
        else:
            self.max_tokens_api_limit = 4096
            self.model_context_window = 200000
            
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.base_url = "https://api.anthropic.com/v1/messages"
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        self.console = Console()

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    connector = aiohttp.TCPConnector(
                        limit=100,
                        limit_per_host=30,
                        ttl_dns_cache=300,
                        use_dns_cache=True,
                    )
                    timeout = aiohttp.ClientTimeout(total=180)
                    self._session = aiohttp.ClientSession(
                        connector=connector,
                        timeout=timeout,
                        headers={
                            "Content-Type": "application/json",
                            "x-api-key": self.api_key,
                            "anthropic-version": "2023-06-01"
                        }
                    )
        return self._session

    def encode_text(self, text: str) -> list:
        """Encode text to tokens"""
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
                        tool_choice: Optional[Dict[str, Any]] = None, max_output_tokens: int = 2048):
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
                tools_text.append(f"- {tool.get('name', 'Unknown')}\n")
            if len(tools) > 5:
                tools_text.append(f"... and {len(tools) - 5} more tools")
            content_parts.append(tools_text)
        
        # Add tool choice if present
        if tool_choice:
            content_parts.append(Text("\n" + "="*80 + "\n", style="dim"))
            choice_text = Text("TOOL CHOICE:\n", style="bold magenta")
            choice_text.append(json.dumps(tool_choice, indent=2))
            content_parts.append(choice_text)
        
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
        tool_choice: Optional[Dict[str, Any]] = None,
        max_output_tokens: int = 2048,
        temperature: Optional[float] = None,
    ) -> Tuple[Any, int, int, int]:
        """
        Generate async response from Anthropic API.
        Can handle:
        - General text generation (if tools/tool_choice are None).
        - Specific tool calling (if tools and tool_choice are provided).
        - Forced JSON object output if model and prompt supports it.
        """
        try:
            # Log what the model is seeing
            self._log_model_input(prompt, tools, tool_choice, max_output_tokens)
            system_prompt_tokens = len(self.encode_text(self.system_prompt)) if self.system_prompt else 0
            available_tokens_for_user_content = self.model_context_window - system_prompt_tokens - max_output_tokens - 100
            
            truncated_user_content = await self.truncate_prompt_async(prompt, available_tokens_for_user_content)
            user_content_tokens = len(self.encode_text(truncated_user_content))

            messages = [{"role": "user", "content": truncated_user_content}]

            payload = {
                "model": self.model_name,
                "messages": messages,
                "temperature": temperature if temperature is not None else 0.7,  # Use provided temp or default
                "max_tokens": min(max_output_tokens, self.max_tokens_api_limit),
            }
            if self.system_prompt:
                payload["system"] = self.system_prompt

            if tools:
                payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

            logger.debug(f"Anthropic payload: {json.dumps(payload, indent=2)[:500]}...")

            session = await self.get_session()
            async with session.post(self.base_url, json=payload) as response:
                response_text_for_error = ""
                try:
                    response_json = await response.json()
                except aiohttp.ContentTypeError:
                    response_text_for_error = await response.text()
                    logger.error(f"Anthropic API non-JSON response ({response.status}): {response_text_for_error}")
                    raise Exception(f"Anthropic API error {response.status}: Non-JSON response. Body: {response_text_for_error}")

                if response.status != 200:
                    error_details = response_json.get("error", {})
                    error_message = error_details.get("message", str(response_json))
                    logger.error(f"Anthropic API error {response.status}: {error_message}")
                    raise Exception(f"Anthropic API error {response.status}: {error_message}")
                
            processed_response, response_tokens_count = self._process_anthropic_response_content(response_json)

            api_input_tokens = response_json.get("usage", {}).get("input_tokens", 0)
            api_output_tokens = response_json.get("usage", {}).get("output_tokens", response_tokens_count)

            logged_prompt_tokens = system_prompt_tokens + user_content_tokens
            
            return processed_response, api_input_tokens + api_output_tokens, logged_prompt_tokens, api_output_tokens

        except Exception as e:
            logger.error(f"Error in async Anthropic response generation: {e}")
            traceback.print_exc()
            raise

    def _process_anthropic_response_content(self, response_json: Dict[str, Any]) -> Tuple[Any, int]:
        """
        Processes the 'content' block from an Anthropic API response.
        Handles text, tool_use, and aims to extract the primary intended output.
        Returns the processed data (str, dict for tool input) and an estimated token count for the output.
        """
        if "content" not in response_json or not isinstance(response_json["content"], list):
            logger.error(f"Unexpected response structure: 'content' is missing or not a list. Response: {response_json}")
            raise ValueError("Malformed response from Anthropic API: 'content' block issue.")

        content_blocks = response_json["content"]
        output_data = None
        
        # Check for tool_use blocks first, regardless of stop_reason
        tool_use_blocks = [block for block in content_blocks if block.get("type") == "tool_use"]
        if tool_use_blocks:
            first_tool_use = tool_use_blocks[0]
            tool_name = first_tool_use.get("name")
            tool_input = first_tool_use.get("input", {})
            output_data = {"type": "tool_use", "name": tool_name, "arguments": tool_input}
        else:
            # No tool use, check for text
            text_blocks = [block for block in content_blocks if block.get("type") == "text"]
            if text_blocks:
                full_text = "".join([block.get("text", "") for block in text_blocks]).strip()
                output_data = full_text
        
        if output_data is None:
            logger.warning(f"No processable content (tool_use or text) found in Anthropic response. Content: {content_blocks}")
            raise ValueError("No usable text or tool_use content found in Anthropic response.")

        estimated_output_tokens = len(self.encode_text(json.dumps(output_data) if isinstance(output_data, dict) else str(output_data)))
        
        return output_data, estimated_output_tokens

    async def close(self):
        """Close the HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close() 