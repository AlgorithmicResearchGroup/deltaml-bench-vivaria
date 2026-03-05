"""
LLM interface module for agent communication.
"""

from .llm_interface import LLMInterface, LLMResponse
from .response_parser import ResponseParser

__all__ = ['LLMInterface', 'LLMResponse', 'ResponseParser']