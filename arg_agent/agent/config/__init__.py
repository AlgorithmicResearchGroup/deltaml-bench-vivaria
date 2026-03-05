"""
Configuration module for ARG Agent.
Provides single source of truth configuration reading from manifest.json.
"""

from .manifest_config import (
    ManifestConfigReader,
    AgentConfig,
    SearchPolicyConfig,
    ExecutionTimeouts,
    get_config_reader,
    get_active_config,
    get_model_name,
    get_max_iterations,
    get_context_window_tokens,
    get_max_concurrent_nodes,
    get_time_limit_seconds,
    get_search_policy,
    get_execution_timeouts,
    get_search_strategy,
    get_python_timeout,
    get_bash_timeout,
    override_config_from_env
)

__all__ = [
    "ManifestConfigReader",
    "AgentConfig",
    "SearchPolicyConfig", 
    "ExecutionTimeouts",
    "get_config_reader",
    "get_active_config",
    "get_model_name",
    "get_max_iterations",
    "get_context_window_tokens",
    "get_max_concurrent_nodes",
    "get_time_limit_seconds",
    "get_search_policy",
    "get_execution_timeouts",
    "get_search_strategy",
    "get_python_timeout",
    "get_bash_timeout",
    "override_config_from_env"
]
