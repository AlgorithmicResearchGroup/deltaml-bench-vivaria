"""Factory for creating cloud storage instances."""

from typing import Dict, Optional
from urllib.parse import urlparse

from .storage_interface import CloudStorageInterface
from .gcs_storage import GCSStorage
from .s3_storage import S3Storage


class StorageFactory:
    """Factory for creating cloud storage instances based on provider or URL."""

    _providers = {
        'gcs': GCSStorage,
        's3': S3Storage,
    }

    @classmethod
    def create(cls, provider: str, config: Dict) -> CloudStorageInterface:
        """Create a storage instance for a specific provider.
        
        Args:
            provider: Provider name ('gcs' or 's3')
            config: Provider configuration
            
        Returns:
            CloudStorageInterface instance
        """
        if provider not in cls._providers:
            raise ValueError(f"Unknown storage provider: {provider}")
        
        storage_class = cls._providers[provider]
        return storage_class(config)

    @classmethod
    def from_url(cls, url: str, config: Optional[Dict] = None) -> CloudStorageInterface:
        """Create a storage instance based on URL scheme.
        
        Args:
            url: Cloud storage URL (gs:// or s3://)
            config: Optional provider configuration
            
        Returns:
            CloudStorageInterface instance
        """
        parsed = urlparse(url)
        
        if parsed.scheme == 'gs':
            provider = 'gcs'
        elif parsed.scheme == 's3':
            provider = 's3'
        else:
            raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
        
        return cls.create(provider, config or {})

    @classmethod
    def register_provider(cls, name: str, storage_class: type):
        """Register a new storage provider.
        
        Args:
            name: Provider name
            storage_class: Storage class implementing CloudStorageInterface
        """
        if not issubclass(storage_class, CloudStorageInterface):
            raise TypeError("Storage class must implement CloudStorageInterface")
        
        cls._providers[name] = storage_class