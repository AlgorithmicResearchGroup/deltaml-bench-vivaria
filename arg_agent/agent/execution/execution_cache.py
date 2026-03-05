"""
Execution cache for avoiding redundant code executions.
"""

import hashlib
import time
from typing import Dict, Optional, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class CachedExecutionInfo:
    """Information about a cached execution"""
    content_hash: str
    stdout: str
    stderr: str
    error: Optional[str]
    is_buggy: bool
    timestamp: float
    hit_count: int = 1


class ExecutionCache:
    """Cache for script execution results"""
    
    def __init__(self, ttl_seconds: float = 3600.0):
        """
        Initialize execution cache.
        
        Args:
            ttl_seconds: Time to live for cache entries in seconds
        """
        self._cache: Dict[str, CachedExecutionInfo] = {}
        self._ttl_seconds = ttl_seconds
    
    def get_content_hash(self, code: str) -> str:
        """
        Get hash of code content.
        
        Args:
            code: Python code to hash
            
        Returns:
            MD5 hash of normalized code
        """
        try:
            # Normalize content: remove comments, extra whitespace, empty lines
            lines = []
            for line in code.split('\n'):
                stripped = line.strip()
                # Keep non-empty lines that aren't just comments
                if stripped and not stripped.startswith('#'):
                    lines.append(stripped)
            
            normalized_content = '\n'.join(lines)
            return hashlib.md5(normalized_content.encode()).hexdigest()
            
        except Exception as e:
            logger.warning(f"Could not hash code: {e}")
            # Return a hash of the raw code as fallback
            return hashlib.md5(code.encode()).hexdigest()
    
    def get(self, code: str) -> Optional[CachedExecutionInfo]:
        """
        Get cached execution result if available.
        
        Args:
            code: Python code to look up
            
        Returns:
            Cached execution info if found and not expired, None otherwise
        """
        content_hash = self.get_content_hash(code)
        
        if content_hash in self._cache:
            cached_info = self._cache[content_hash]
            
            # Check if cache entry has expired
            age = time.time() - cached_info.timestamp
            if age > self._ttl_seconds:
                logger.debug(f"Cache entry expired for hash {content_hash[:8]} (age: {age:.1f}s)")
                del self._cache[content_hash]
                return None
            
            # Update hit count
            cached_info.hit_count += 1
            logger.info(f"Cache hit for hash {content_hash[:8]} (hits: {cached_info.hit_count})")
            return cached_info
        
        return None
    
    def put(
        self,
        code: str,
        stdout: str,
        stderr: str,
        error: Optional[str],
        is_buggy: bool
    ) -> str:
        """
        Store execution result in cache.
        
        Args:
            code: Python code that was executed
            stdout: Standard output from execution
            stderr: Standard error from execution
            error: Error message if any
            is_buggy: Whether the execution had bugs
            
        Returns:
            Content hash of the code
        """
        content_hash = self.get_content_hash(code)
        
        self._cache[content_hash] = CachedExecutionInfo(
            content_hash=content_hash,
            stdout=stdout,
            stderr=stderr,
            error=error,
            is_buggy=is_buggy,
            timestamp=time.time()
        )
        
        logger.debug(f"Cached execution result for hash {content_hash[:8]}")
        return content_hash
    
    def clear_expired(self) -> int:
        """
        Clear expired cache entries.
        
        Returns:
            Number of entries cleared
        """
        current_time = time.time()
        expired_keys = [
            key for key, info in self._cache.items()
            if current_time - info.timestamp > self._ttl_seconds
        ]
        
        for key in expired_keys:
            del self._cache[key]
        
        if expired_keys:
            logger.info(f"Cleared {len(expired_keys)} expired cache entries")
        
        return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_hits = sum(info.hit_count for info in self._cache.values())
        return {
            'size': len(self._cache),
            'total_hits': total_hits,
            'ttl_seconds': self._ttl_seconds
        }