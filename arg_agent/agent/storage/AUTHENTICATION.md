# Cloud Storage Authentication Guide

This guide explains how to set up authentication for cloud storage providers.

## Google Cloud Storage (GCS)

### Method 1: Service Account JSON Key

1. Create a service account in the Google Cloud Console
2. Download the JSON key file
3. Set the environment variable:
   ```bash
   export GCS_CREDENTIALS_PATH=/path/to/service-account-key.json
   export GCP_PROJECT_ID=your-project-id
   ```

### Method 2: Application Default Credentials

1. Install gcloud CLI
2. Run: `gcloud auth application-default login`
3. The library will automatically use these credentials

### Method 3: Workload Identity (GKE)

If running on GKE, workload identity will be used automatically.

## AWS S3

### Method 1: Environment Variables

Set the following environment variables:
```bash
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=us-east-1
```

### Method 2: AWS CLI Configuration

1. Install AWS CLI
2. Run: `aws configure`
3. Enter your credentials when prompted

### Method 3: IAM Role (EC2/ECS/Lambda)

If running on AWS infrastructure, IAM roles will be used automatically.

## Security Best Practices

1. **Never commit credentials to version control**
2. **Use service accounts with minimal permissions**
3. **Rotate credentials regularly**
4. **Use workload identity/IAM roles when possible**
5. **Enable audit logging for cloud storage access**

## Testing Authentication

You can test your authentication setup using the cloud storage tool:

```python
# Test GCS
cloud_storage(action="list", url="gs://your-bucket/")

# Test S3
cloud_storage(action="list", url="s3://your-bucket/")
```

## Troubleshooting

### GCS Issues
- Ensure the service account has the required permissions (Storage Object Viewer/Admin)
- Check that the JSON key file path is correct
- Verify the project ID matches your bucket's project

### S3 Issues
- Verify IAM user/role has the required S3 permissions
- Check that the region is correct for your bucket
- Ensure credentials are not expired

## Configuration File

You can also configure credentials in `config/async_config.yaml`:

```yaml
cloud_storage:
  providers:
    gcs:
      enabled: true
      credentials_path: ${GCS_CREDENTIALS_PATH}
      project_id: ${GCP_PROJECT_ID}
    s3:
      enabled: true
      access_key: ${AWS_ACCESS_KEY_ID}
      secret_key: ${AWS_SECRET_ACCESS_KEY}
      region: ${AWS_DEFAULT_REGION}
```

The configuration supports environment variable expansion using `${VAR_NAME}` syntax.