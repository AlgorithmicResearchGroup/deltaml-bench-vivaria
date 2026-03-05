# Cloud Storage Integration

This module provides a unified interface for working with cloud storage providers (Google Cloud Storage and AWS S3) in the agent system.

## Features

- **Unified Interface**: Single API for both GCS and S3
- **Async Operations**: Non-blocking I/O for better performance
- **Streaming Support**: Handle large files efficiently
- **Directory Operations**: Upload/download entire directories
- **Progress Tracking**: Monitor transfer progress
- **Automatic Retries**: Built-in retry logic with exponential backoff
- **Caching Support**: Optional local caching of frequently accessed files

## Architecture

```
agent/storage/
├── __init__.py              # Package exports
├── storage_interface.py     # Abstract base class
├── gcs_storage.py          # Google Cloud Storage implementation
├── s3_storage.py           # AWS S3 implementation
├── storage_factory.py      # Factory for creating storage instances
├── AUTHENTICATION.md       # Authentication guide
└── README.md              # This file
```

## Usage in Agent

The cloud storage tool is automatically registered and available to the agent:

```python
# Download from GCS
cloud_storage(action="download", source_url="gs://bucket/file.csv", destination="./file.csv")

# Upload to S3
cloud_storage(action="upload", source="./results.pkl", destination_url="s3://bucket/results.pkl")

# List objects
cloud_storage(action="list", url="gs://bucket/prefix/")

# Check existence
cloud_storage(action="exists", url="s3://bucket/file.txt")

# Get metadata
cloud_storage(action="metadata", url="gs://bucket/file.csv")

# Delete object
cloud_storage(action="delete", url="s3://bucket/old-file.txt")
```

## Configuration

Configure in `config/async_config.yaml`:

```yaml
cloud_storage:
  providers:
    gcs:
      enabled: true
      credentials_path: ${GCS_CREDENTIALS_PATH}
    s3:
      enabled: true
      access_key: ${AWS_ACCESS_KEY_ID}
      secret_key: ${AWS_SECRET_ACCESS_KEY}
  cache:
    enabled: true
    path: /tmp/cloud_cache
    max_size_gb: 10
```

## Integration with Existing Tools

The cloud storage integration extends existing tools:

1. **Bash Tool**: Can use `gsutil` and `aws s3` commands
2. **Code Tool**: Can read/write files from cloud URLs
3. **Python Tool**: Scripts can access cloud data

## Performance Optimization

- Connection pooling for reusing connections
- Concurrent uploads/downloads for directories
- Chunk-based streaming for large files
- Local caching to avoid repeated downloads

## Error Handling

- Automatic retries with exponential backoff
- Graceful fallback for authentication failures
- Detailed error messages for debugging

## Security

- Supports service account authentication (GCS)
- Supports IAM roles and access keys (S3)
- Server-side encryption support
- Credential rotation capabilities

## Future Enhancements

- Azure Blob Storage support
- Multi-cloud data sync
- Bandwidth throttling
- Cost tracking and optimization
- Enhanced caching with TTL and LRU eviction