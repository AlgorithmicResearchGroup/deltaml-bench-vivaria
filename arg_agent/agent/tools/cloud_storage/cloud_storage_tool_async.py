"""Cloud storage tool for downloading and uploading files to/from cloud storage."""

import os
import asyncio
from typing import Optional, Dict, Any, Union, List
from pathlib import Path
import yaml
import json

from agent.storage import StorageFactory, CloudStorageInterface


class CloudStorageTool:
    """Tool for interacting with cloud storage (GCS, S3)."""

    name = "cloud_storage"
    description = "Download/upload files and directories from/to cloud storage (GCS, S3)"

    def __init__(self, config_path: Optional[str] = None):
        """Initialize cloud storage tool.
        
        Args:
            config_path: Path to configuration file
        """
        self.config = self._load_config(config_path)
        self._storage_instances = {}

    def _load_config(self, config_path: Optional[str] = None) -> Dict:
        """Load cloud storage configuration."""
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                return config.get('cloud_storage', {})
        
        # Default configuration
        return {
            'providers': {
                'gcs': {
                    'enabled': True,
                    'credentials_path': os.environ.get('GCS_CREDENTIALS_PATH', ''),
                    'project_id': os.environ.get('GCP_PROJECT_ID', '')
                },
                's3': {
                    'enabled': True,
                    'access_key': os.environ.get('AWS_ACCESS_KEY_ID', ''),
                    'secret_key': os.environ.get('AWS_SECRET_ACCESS_KEY', ''),
                    'region': os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
                }
            },
            'cache': {
                'enabled': True,
                'path': '/tmp/cloud_cache',
                'max_size_gb': 10
            }
        }

    async def _get_storage(self, url: str) -> CloudStorageInterface:
        """Get or create storage instance for URL."""
        # Determine provider from URL
        if url.startswith('gs://'):
            provider = 'gcs'
        elif url.startswith('s3://'):
            provider = 's3'
        else:
            raise ValueError(f"Unsupported URL format: {url}")
        
        # Get or create instance
        if provider not in self._storage_instances:
            provider_config = self.config['providers'].get(provider, {})
            if not provider_config.get('enabled', False):
                raise ValueError(f"Provider {provider} is not enabled in configuration")
            
            storage = StorageFactory.create(provider, provider_config)
            await storage.initialize()
            self._storage_instances[provider] = storage
        
        return self._storage_instances[provider]

    async def download(
        self,
        source_url: str,
        destination: Optional[str] = None,
        recursive: bool = False,
        worker_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Download file or directory from cloud storage.
        
        Args:
            source_url: Cloud storage URL (gs:// or s3://)
            destination: Local destination path (defaults to current directory)
            recursive: Whether to download directories recursively
            worker_context: Worker context containing working directory
            
        Returns:
            Result dictionary with downloaded paths
        """
        try:
            storage = await self._get_storage(source_url)
            bucket, key = storage.parse_url(source_url)
            
            # Determine destination
            if not destination:
                if worker_context and 'working_dir' in worker_context:
                    destination = worker_context['working_dir']
                else:
                    destination = os.getcwd()
            
            destination = Path(destination)
            
            # Check if source is a directory (ends with / or recursive flag)
            is_directory = key.endswith('/') or recursive
            
            if is_directory:
                # Download directory
                local_path = await storage.download_directory(
                    bucket, key.rstrip('/'), destination
                )
                return {
                    'success': True,
                    'message': f"Downloaded directory from {source_url} to {local_path}",
                    'local_path': str(local_path),
                    'type': 'directory'
                }
            else:
                # Download single file
                if destination.is_dir():
                    # If destination is a directory, use the source filename
                    filename = os.path.basename(key)
                    local_path = destination / filename
                else:
                    local_path = destination
                
                local_path = await storage.download_file(bucket, key, local_path)
                return {
                    'success': True,
                    'message': f"Downloaded {source_url} to {local_path}",
                    'local_path': str(local_path),
                    'type': 'file'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f"Failed to download from {source_url}: {str(e)}"
            }

    async def upload(
        self,
        source: str,
        destination_url: str,
        recursive: bool = False,
        worker_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Upload file or directory to cloud storage.
        
        Args:
            source: Local source path
            destination_url: Cloud storage URL (gs:// or s3://)
            recursive: Whether to upload directories recursively
            worker_context: Worker context containing working directory
            
        Returns:
            Result dictionary with uploaded URLs
        """
        try:
            storage = await self._get_storage(destination_url)
            bucket, key = storage.parse_url(destination_url)
            
            # Resolve source path
            if worker_context and 'working_dir' in worker_context:
                source_path = Path(worker_context['working_dir']) / source
            else:
                source_path = Path(source)
            
            source_path = source_path.resolve()
            
            if not source_path.exists():
                raise FileNotFoundError(f"Source path does not exist: {source_path}")
            
            if source_path.is_dir():
                if not recursive:
                    raise ValueError("Use recursive=True to upload directories")
                
                # Upload directory
                urls = await storage.upload_directory(source_path, bucket, key)
                return {
                    'success': True,
                    'message': f"Uploaded directory {source_path} to {destination_url}",
                    'urls': urls,
                    'type': 'directory',
                    'count': len(urls)
                }
            else:
                # Upload single file
                url = await storage.upload_file(source_path, bucket, key)
                return {
                    'success': True,
                    'message': f"Uploaded {source_path} to {url}",
                    'url': url,
                    'type': 'file'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f"Failed to upload {source} to {destination_url}: {str(e)}"
            }

    async def list(
        self,
        url: str,
        max_results: Optional[int] = None,
        worker_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """List objects in cloud storage.
        
        Args:
            url: Cloud storage URL (gs:// or s3://)
            max_results: Maximum number of results to return
            worker_context: Worker context
            
        Returns:
            Result dictionary with object list
        """
        try:
            storage = await self._get_storage(url)
            bucket, prefix = storage.parse_url(url)
            
            objects = await storage.list_objects(bucket, prefix, max_results)
            
            return {
                'success': True,
                'message': f"Listed {len(objects)} objects in {url}",
                'objects': objects,
                'count': len(objects)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f"Failed to list objects in {url}: {str(e)}"
            }

    async def delete(
        self,
        url: str,
        worker_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Delete object from cloud storage.
        
        Args:
            url: Cloud storage URL (gs:// or s3://)
            worker_context: Worker context
            
        Returns:
            Result dictionary
        """
        try:
            storage = await self._get_storage(url)
            bucket, key = storage.parse_url(url)
            
            await storage.delete_object(bucket, key)
            
            return {
                'success': True,
                'message': f"Deleted {url}"
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f"Failed to delete {url}: {str(e)}"
            }

    async def exists(
        self,
        url: str,
        worker_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Check if object exists in cloud storage.
        
        Args:
            url: Cloud storage URL (gs:// or s3://)
            worker_context: Worker context
            
        Returns:
            Result dictionary with existence status
        """
        try:
            storage = await self._get_storage(url)
            bucket, key = storage.parse_url(url)
            
            exists = await storage.exists(bucket, key)
            
            return {
                'success': True,
                'exists': exists,
                'message': f"Object {'exists' if exists else 'does not exist'}: {url}"
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f"Failed to check existence of {url}: {str(e)}"
            }

    async def get_metadata(
        self,
        url: str,
        worker_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Get metadata for object in cloud storage.
        
        Args:
            url: Cloud storage URL (gs:// or s3://)
            worker_context: Worker context
            
        Returns:
            Result dictionary with metadata
        """
        try:
            storage = await self._get_storage(url)
            bucket, key = storage.parse_url(url)
            
            metadata = await storage.get_object_metadata(bucket, key)
            
            return {
                'success': True,
                'metadata': metadata,
                'message': f"Retrieved metadata for {url}"
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f"Failed to get metadata for {url}: {str(e)}"
            }

    async def run(
        self,
        action: str,
        params: Dict[str, Any],
        worker_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Main entry point for the tool.
        
        Args:
            action: Action to perform (download, upload, list, delete, exists, metadata)
            params: Parameters for the action
            worker_context: Worker context
            
        Returns:
            Result dictionary
        """
        action_map = {
            'download': self.download,
            'upload': self.upload,
            'list': self.list,
            'delete': self.delete,
            'exists': self.exists,
            'metadata': self.get_metadata
        }
        
        if action not in action_map:
            return {
                'success': False,
                'error': f"Unknown action: {action}",
                'message': f"Supported actions: {', '.join(action_map.keys())}"
            }
        
        handler = action_map[action]
        return await handler(**params, worker_context=worker_context)

    async def cleanup(self):
        """Clean up storage instances."""
        for storage in self._storage_instances.values():
            await storage.close()
        self._storage_instances.clear()