"""
Single source of truth configuration reader for ARG Agent.
Reads configuration from manifest.json to maintain consistency with Vivaria.
"""

import json
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class SearchPolicyConfig:
    """Search policy configuration"""
    num_drafts: int = 3
    debug_prob: float = 0.8
    max_debug_depth: int = 8
    min_debug_attempts: int = 3
    search_strategy: str = "tree_search"
    force_continue_on_incomplete: bool = True
    min_iterations_before_stop: int = 15

@dataclass
class ExecutionTimeouts:
    """Execution timeout configuration"""
    python_execution: int = 3600
    bash_execution: int = 600
    default_tool: int = 300

@dataclass
class AgentConfig:
    """Comprehensive configuration dataclass for ARG Agent settings"""
    model: str
    max_iterations: int
    context_window_tokens: int
    enable_reflection: bool = True
    enable_monitoring: bool = True
    max_concurrent_nodes: int = 8
    time_limit_seconds: int = 1800
    search_policy: SearchPolicyConfig = None
    execution_timeouts: ExecutionTimeouts = None
    beam_width: Optional[int] = None
    description: str = ""
    
    def __post_init__(self):
        """Initialize nested configs if not provided"""
        if self.search_policy is None:
            self.search_policy = SearchPolicyConfig()
        if self.execution_timeouts is None:
            self.execution_timeouts = ExecutionTimeouts()

class ManifestConfigReader:
    """Reads and provides access to manifest.json configuration"""
    
    def __init__(self, manifest_path: Optional[str] = None):
        self.manifest_path = manifest_path or self._find_manifest_path()
        self._config_cache: Optional[Dict[str, Any]] = None
        self._active_config: Optional[AgentConfig] = None
        
    def _find_manifest_path(self) -> str:
        """Find manifest.json in the project structure"""
        # Try current directory first
        current_dir = Path.cwd()
        env_manifest_path = os.getenv("ARG_AGENT_MANIFEST_PATH")
        
        # Common locations to check
        possible_paths = [
            Path(env_manifest_path) if env_manifest_path else None,
            current_dir / "manifest.json",
            current_dir / "arg_agent" / "manifest.json", 
            Path(__file__).parent.parent.parent / "manifest.json",  # Go up from agent/config/
        ]
        
        for path in [path for path in possible_paths if path is not None]:
            if path.exists():
                logger.info(f"Found manifest.json at: {path}")
                return str(path)
        
        raise FileNotFoundError(f"manifest.json not found in any of: {[str(p) for p in possible_paths]}")
    
    def _load_manifest(self) -> Dict[str, Any]:
        """Load and cache the manifest.json content"""
        if self._config_cache is not None:
            return self._config_cache
            
        try:
            with open(self.manifest_path, 'r') as f:
                self._config_cache = json.load(f)
            logger.info(f"Loaded manifest configuration from {self.manifest_path}")
            return self._config_cache
        except Exception as e:
            logger.error(f"Failed to load manifest from {self.manifest_path}: {e}")
            raise
    
    def get_settings_pack(self, pack_name: Optional[str] = None) -> AgentConfig:
        """
        Get configuration for a specific settings pack.
        If pack_name is None, uses the defaultSettingsPack.
        """
        manifest = self._load_manifest()
        
        # Use provided pack name or default
        if pack_name is None:
            pack_name = manifest.get("defaultSettingsPack", "arg_default")
        
        # Get the settings pack
        settings_packs = manifest.get("settingsPacks", {})
        if pack_name not in settings_packs:
            available_packs = list(settings_packs.keys())
            raise ValueError(f"Settings pack '{pack_name}' not found. Available: {available_packs}")
        
        pack_config = settings_packs[pack_name]
        
        # Convert to AgentConfig with validation
        try:
            # Parse search policy
            search_policy_data = pack_config.get("search_policy", {})
            search_policy = SearchPolicyConfig(
                num_drafts=search_policy_data.get("num_drafts", 3),
                debug_prob=search_policy_data.get("debug_prob", 0.8),
                max_debug_depth=search_policy_data.get("max_debug_depth", 8),
                min_debug_attempts=search_policy_data.get("min_debug_attempts", 3),
                search_strategy=search_policy_data.get("search_strategy", "tree_search"),
                force_continue_on_incomplete=search_policy_data.get("force_continue_on_incomplete", True),
                min_iterations_before_stop=search_policy_data.get("min_iterations_before_stop", 15)
            )
            
            # Parse execution timeouts
            timeout_data = pack_config.get("execution_timeouts", {})
            execution_timeouts = ExecutionTimeouts(
                python_execution=timeout_data.get("python_execution", 3600),
                bash_execution=timeout_data.get("bash_execution", 600),
                default_tool=timeout_data.get("default_tool", 300)
            )
            
            config = AgentConfig(
                model=pack_config["model"],
                max_iterations=pack_config["max_iterations"],
                context_window_tokens=pack_config["context_window_tokens"],
                enable_reflection=pack_config.get("enable_reflection", True),
                enable_monitoring=pack_config.get("enable_monitoring", True),
                max_concurrent_nodes=pack_config.get("max_concurrent_nodes", 8),
                time_limit_seconds=pack_config.get("time_limit_seconds", 1800),
                search_policy=search_policy,
                execution_timeouts=execution_timeouts,
                beam_width=pack_config.get("beam_width"),
                description=pack_config.get("description", f"Settings pack: {pack_name}")
            )
            logger.info(f"Loaded settings pack '{pack_name}': model={config.model}, iterations={config.max_iterations}")
            return config
        except KeyError as e:
            raise ValueError(f"Missing required configuration key in pack '{pack_name}': {e}")
    
    def get_active_config(self) -> AgentConfig:
        """Get the currently active configuration (caches result)"""
        if self._active_config is None:
            # Check if a specific pack is requested via environment variable
            requested_pack = os.getenv("ARG_SETTINGS_PACK")
            self._active_config = self.get_settings_pack(requested_pack)
        return self._active_config
    
    def list_available_packs(self) -> Dict[str, str]:
        """List all available settings packs with their descriptions"""
        manifest = self._load_manifest()
        settings_packs = manifest.get("settingsPacks", {})
        
        return {
            pack_name: pack_config.get("description", "No description")
            for pack_name, pack_config in settings_packs.items()
        }
    
    def reload(self):
        """Clear cache and reload configuration"""
        self._config_cache = None
        self._active_config = None
        logger.info("Configuration cache cleared - will reload on next access")

# Global instance for easy access throughout the codebase
_global_config_reader: Optional[ManifestConfigReader] = None

def get_config_reader() -> ManifestConfigReader:
    """Get the global configuration reader instance"""
    global _global_config_reader
    if _global_config_reader is None:
        _global_config_reader = ManifestConfigReader()
    return _global_config_reader

def get_active_config() -> AgentConfig:
    """Convenience function to get the active configuration"""
    return get_config_reader().get_active_config()

def get_model_name() -> str:
    """Convenience function to get just the model name"""
    return get_active_config().model

def get_max_iterations() -> int:
    """Convenience function to get max iterations"""
    return get_active_config().max_iterations

def get_context_window_tokens() -> int:
    """Convenience function to get context window size"""
    return get_active_config().context_window_tokens

def get_max_concurrent_nodes() -> int:
    """Convenience function to get max concurrent nodes"""
    return get_active_config().max_concurrent_nodes

def get_time_limit_seconds() -> int:
    """Convenience function to get time limit in seconds"""
    return get_active_config().time_limit_seconds

def get_search_policy() -> SearchPolicyConfig:
    """Convenience function to get search policy configuration"""
    return get_active_config().search_policy

def get_execution_timeouts() -> ExecutionTimeouts:
    """Convenience function to get execution timeout configuration"""
    return get_active_config().execution_timeouts

def get_search_strategy() -> str:
    """Convenience function to get search strategy"""
    return get_active_config().search_policy.search_strategy

def get_python_timeout() -> int:
    """Convenience function to get Python execution timeout"""
    return get_active_config().execution_timeouts.python_execution

def get_bash_timeout() -> int:
    """Convenience function to get Bash execution timeout"""
    return get_active_config().execution_timeouts.bash_execution

# Environment variable override support
def override_config_from_env() -> None:
    """Override configuration values from environment variables if present"""
    config = get_active_config()
    
    # Allow environment variables to override specific settings
    if "ARG_MODEL" in os.environ:
        config.model = os.environ["ARG_MODEL"]
        logger.info(f"Model overridden by ARG_MODEL env var: {config.model}")
    
    if "ARG_MAX_ITERATIONS" in os.environ:
        try:
            config.max_iterations = int(os.environ["ARG_MAX_ITERATIONS"])
            logger.info(f"Max iterations overridden by ARG_MAX_ITERATIONS: {config.max_iterations}")
        except ValueError:
            logger.warning(f"Invalid ARG_MAX_ITERATIONS value: {os.environ['ARG_MAX_ITERATIONS']}")
    
    if "ARG_CONTEXT_TOKENS" in os.environ:
        try:
            config.context_window_tokens = int(os.environ["ARG_CONTEXT_TOKENS"])
            logger.info(f"Context tokens overridden by ARG_CONTEXT_TOKENS: {config.context_window_tokens}")
        except ValueError:
            logger.warning(f"Invalid ARG_CONTEXT_TOKENS value: {os.environ['ARG_CONTEXT_TOKENS']}")
