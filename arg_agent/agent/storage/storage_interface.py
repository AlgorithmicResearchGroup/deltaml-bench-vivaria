"""Abstract interface for cloud storage providers."""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, AsyncIterator, Union
from pathlib import Path
import asyncio


class CloudStorageInterface(ABC):
    """Abstract base class for cloud storage providers."""

    def __init__(self, config: Dict):
        """Initialize storage provider with configuration.
        
        Args:
            config: Provider-specific configuration dictionary
        """
        self.config = config
        self._client = None

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the storage client connection."""
        pass

    @abstractmethod
    async def download_file(
        self, 
        bucket: str, 
        key: str, 
        local_path: Union[str, Path],
        progress_callback: Optional[callable] = None
    ) -> Path:
        """Download a file from cloud storage.
        
        Args:
            bucket: Bucket name
            key: Object key/path in bucket
            local_path: Local destination path
            progress_callback: Optional callback for progress updates
            
        Returns:
            Path to downloaded file
        """
        pass

    @abstractmethod
    async def upload_file(
        self, 
        local_path: Union[str, Path], 
        bucket: str, 
        key: str,
        progress_callback: Optional[callable] = None
    ) -> str:
        """Upload a file to cloud storage.
        
        Args:
            local_path: Local file path
            bucket: Bucket name
            key: Object key/path in bucket
            progress_callback: Optional callback for progress updates
            
        Returns:
            Cloud storage URL
        """
        pass

    @abstractmethod
    async def download_directory(
        self, 
        bucket: str, 
        prefix: str, 
        local_dir: Union[str, Path],
        progress_callback: Optional[callable] = None
    ) -> Path:
        """Download a directory from cloud storage.
        
        Args:
            bucket: Bucket name
            prefix: Directory prefix in bucket
            local_dir: Local destination directory
            progress_callback: Optional callback for progress updates
            
        Returns:
            Path to downloaded directory
        """
        pass

    @abstractmethod
    async def upload_directory(
        self, 
        local_dir: Union[str, Path], 
        bucket: str, 
        prefix: str,
        progress_callback: Optional[callable] = None
    ) -> List[str]:
        """Upload a directory to cloud storage.
        
        Args:
            local_dir: Local directory path
            bucket: Bucket name
            prefix: Directory prefix in bucket
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of uploaded object URLs
        """
        pass

    @abstractmethod
    async def list_objects(
        self, 
        bucket: str, 
        prefix: Optional[str] = None,
        max_results: Optional[int] = None
    ) -> List[Dict[str, any]]:
        """List objects in a bucket.
        
        Args:
            bucket: Bucket name
            prefix: Optional prefix to filter objects
            max_results: Maximum number of results
            
        Returns:
            List of object metadata dictionaries
        """
        pass

    @abstractmethod
    async def delete_object(self, bucket: str, key: str) -> None:
        """Delete an object from cloud storage.
        
        Args:
            bucket: Bucket name
            key: Object key/path in bucket
        """
        pass

    @abstractmethod
    async def exists(self, bucket: str, key: str) -> bool:
        """Check if an object exists in cloud storage.
        
        Args:
            bucket: Bucket name
            key: Object key/path in bucket
            
        Returns:
            True if object exists
        """
        pass

    @abstractmethod
    async def get_object_metadata(self, bucket: str, key: str) -> Dict[str, any]:
        """Get metadata for an object.
        
        Args:
            bucket: Bucket name
            key: Object key/path in bucket
            
        Returns:
            Object metadata dictionary
        """
        pass

    @abstractmethod
    async def stream_download(
        self, 
        bucket: str, 
        key: str,
        chunk_size: int = 8192
    ) -> AsyncIterator[bytes]:
        """Stream download an object.
        
        Args:
            bucket: Bucket name
            key: Object key/path in bucket
            chunk_size: Size of chunks to yield
            
        Yields:
            Chunks of bytes
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the storage client connection."""
        pass

    @abstractmethod
    def parse_url(self, url: str) -> tuple[str, str]:
        """Parse a cloud storage URL into bucket and key.
        
        Args:
            url: Cloud storage URL (e.g., gs://bucket/path or s3://bucket/path)
            
        Returns:
            Tuple of (bucket, key)
        """
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()