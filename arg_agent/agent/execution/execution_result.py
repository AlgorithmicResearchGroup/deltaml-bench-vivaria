"""
Data structures for code execution results.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime


class ExecutionStatus(Enum):
    """Status of code execution"""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    SYSTEM_ERROR = "system_error"


@dataclass
class ExecutionResult:
    """Result of code execution"""
    status: ExecutionStatus
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    execution_time: float = 0.0
    cached: bool = False
    gpu_used: Optional[int] = None
    script_path: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def success(self) -> bool:
        """Check if execution was successful"""
        return self.status == ExecutionStatus.SUCCESS
    
    @property
    def is_timeout(self) -> bool:
        """Check if execution timed out"""
        return self.status == ExecutionStatus.TIMEOUT
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'status': self.status.value,
            'stdout': self.stdout,
            'stderr': self.stderr,
            'error': self.error,
            'execution_time': self.execution_time,
            'cached': self.cached,
            'gpu_used': self.gpu_used,
            'script_path': self.script_path,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata
        }