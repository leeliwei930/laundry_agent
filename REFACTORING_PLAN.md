# Lambda Function Refactoring Plan: Image Path to R2 Object Key

## Overview
Refactor the Lambda function to consume R2 object keys instead of public image URLs, downloading images directly from private Cloudflare R2 object storage.

---

## Current Implementation Analysis

### Current Flow
1. Lambda receives `image_path` as a public URL (e.g., `https://storage.r2.homelab.iewileel.dev/camera_snapshot/20251008/180629_screenshot.jpg`)
2. Uses `requests.get()` to download the image from the public URL
3. Processes the image bytes for analysis

### Issues with Current Approach
- Requires images to be publicly accessible
- No authentication/authorization for image access
- Network overhead for external HTTP requests
- Security concerns with public image URLs

---

## Target Architecture

### New Flow
1. Lambda receives `object_key` (e.g., `camera_snapshot/20251008/180629_screenshot.jpg`)
2. Uses boto3 S3 client with R2-compatible endpoint to download image from private bucket
3. Processes the image bytes for analysis

### Benefits
- Images remain private in R2 storage
- Authenticated access using R2 credentials
- Direct S3-compatible API access
- Better security and access control

---

## Phase 1: Environment Variables Configuration

### 1.1 Add R2 Configuration to deployment.go

**File**: `/workspace/deployment/deployment.go`

**Changes Required**:
```go
Environment: &map[string]*string{
    "APPLICATION_INFERENCE_PROFILE_ARN": jsii.String("arn:aws:bedrock:ap-southeast-1:096778346036:application-inference-profile/m2yc3f0mbts3"),
    "APP_DEBUG":                         jsii.String("WARNING"),
    
    // Add R2 Configuration
    "R2_ACCESS_KEY_ID":     jsii.String(os.Getenv("R2_ACCESS_KEY_ID")),
    "R2_SECRET_ACCESS_KEY": jsii.String(os.Getenv("R2_SECRET_ACCESS_KEY")),
    "R2_ENDPOINT":          jsii.String(os.Getenv("R2_ENDPOINT")),
    "R2_BUCKET_NAME":       jsii.String(os.Getenv("R2_BUCKET_NAME")),
    "R2_PUBLIC_URL":        jsii.String(os.Getenv("R2_PUBLIC_URL")), // Optional: for constructing source URLs
},
```

**Environment Variables to Set** (before deployment):
```bash
export R2_ACCESS_KEY_ID="your-r2-access-key-id"
export R2_SECRET_ACCESS_KEY="your-r2-secret-access-key"
export R2_ENDPOINT="https://your-account-id.r2.cloudflarestorage.com"
export R2_BUCKET_NAME="your-bucket-name"
export R2_PUBLIC_URL="https://storage.r2.homelab.iewileel.dev" # Optional
```

### 1.2 Validation
- Ensure all required environment variables are set before deployment
- Add validation in deployment script or CDK context

---

## Phase 2: Lambda Function Refactoring

### 2.1 Update agent.py - R2 Client Initialization

**File**: `/workspace/src/agent.py`

**Add R2 configuration constants** (after line 18):
```python
# R2 Configuration from environment variables
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.environ.get("R2_ENDPOINT")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")
```

### 2.2 Create R2 Download Function

**Add new function** (after line 67):
```python
def download_image_from_r2(object_key: str) -> tuple[bytes, str]:
    """
    Download image from Cloudflare R2 object storage.
    
    Args:
        object_key: The object key in R2 (e.g., 'camera_snapshot/20251008/180629_screenshot.jpg')
    
    Returns:
        tuple: (image_bytes, image_format)
    """
    # Validate configuration
    if not all([R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT, R2_BUCKET_NAME]):
        raise ValueError("R2 configuration is incomplete. Check environment variables.")
    
    # Create S3 client configured for R2
    s3_client = boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name='auto',  # R2 uses 'auto' region
    )
    
    # Download object from R2
    l.info(f"Downloading object from R2: {object_key}")
    response = s3_client.get_object(Bucket=R2_BUCKET_NAME, Key=object_key)
    image_bytes = response['Body'].read()
    
    # Determine image format from object key or content type
    image = Image.open(io.BytesIO(image_bytes))
    image_format = image.format.lower() if image.format else 'jpeg'
    
    l.info(f"Downloaded {len(image_bytes)} bytes from R2, format: {image_format}")
    return image_bytes, image_format
```

### 2.3 Update Handler Function

**Modify handler function** (lines 68-138):

**Option A: Support Both image_path and object_key (Backward Compatible)**
```python
def handler(event: Dict[str, Any], _context) -> Dict[str, Any]:
    l.info(f"Using application inference profile ARN: {APPLICATION_INFERENCE_PROFILE_ARN}")
    
    # Support both old (image_path) and new (object_key) parameters
    object_key = event.get("object_key")
    image_path = event.get("image_path")  # Deprecated
    
    if object_key:
        # New path: Download from R2
        l.info(f"Processing object from R2: {object_key}")
        image_bytes, image_format = download_image_from_r2(object_key)
        
        # Construct source URL if R2_PUBLIC_URL is configured
        source_url = f"{R2_PUBLIC_URL}/{object_key}" if R2_PUBLIC_URL else object_key
    elif image_path:
        # Legacy path: Download from public URL (deprecated)
        l.warning("image_path parameter is deprecated. Use object_key instead.")
        l.info(f"Processing image from URL: {image_path}")
        
        response = requests.get(image_path, timeout=15)
        response.raise_for_status()
        
        image = Image.open(io.BytesIO(response.content))
        image_format = image.format.lower() if image.format else 'jpeg'
        image_bytes = response.content
        source_url = image_path
    else:
        raise ValueError("Either 'object_key' or 'image_path' must be provided")
    
    # Rest of the function remains the same...
    boto3_session = boto3.Session(region_name="ap-southeast-1")
    # ... (continue with existing logic)
```

**Option B: Only Support object_key (Clean Break)**
```python
def handler(event: Dict[str, Any], _context) -> Dict[str, Any]:
    l.info(f"Using application inference profile ARN: {APPLICATION_INFERENCE_PROFILE_ARN}")
    
    # Get object key from event
    object_key = event.get("object_key")
    if not object_key:
        raise ValueError("'object_key' parameter is required")
    
    # Download from R2
    l.info(f"Processing object from R2: {object_key}")
    image_bytes, image_format = download_image_from_r2(object_key)
    
    # Construct source URL if R2_PUBLIC_URL is configured
    source_url = f"{R2_PUBLIC_URL}/{object_key}" if R2_PUBLIC_URL else object_key
    
    # Rest of the function remains the same...
    boto3_session = boto3.Session(region_name="ap-southeast-1")
    # ... (continue with existing logic)
```

### 2.4 Update Main Test Block

**Update main block** (lines 142-146):
```python
if __name__ == "__main__":
    result = handler({
        "object_key": "camera_snapshot/20251008/180629_screenshot.jpg"
    }, None)
    print(json.dumps(result, indent=4))
```

---

## Phase 3: IAM Permissions (Optional)

### 3.1 S3 Policy for Lambda (if using AWS credentials)

**Note**: Since Cloudflare R2 uses its own access keys, IAM permissions are not required. The Lambda function will use the R2 credentials passed via environment variables.

However, ensure the Lambda execution role has permissions to:
- Read environment variables (default)
- Log to CloudWatch (already configured)

---

## Phase 4: Testing Strategy

### 4.1 Local Testing
```bash
# Set environment variables
export R2_ACCESS_KEY_ID="your-key"
export R2_SECRET_ACCESS_KEY="your-secret"
export R2_ENDPOINT="https://your-account.r2.cloudflarestorage.com"
export R2_BUCKET_NAME="your-bucket"
export R2_PUBLIC_URL="https://storage.r2.homelab.iewileel.dev"

# Run local test
python src/agent.py
```

### 4.2 Lambda Test Events

**Test Event 1: New object_key format**
```json
{
  "object_key": "camera_snapshot/20251008/180629_screenshot.jpg"
}
```

**Test Event 2: Legacy image_path format (if backward compatible)**
```json
{
  "image_path": "https://storage.r2.homelab.iewileel.dev/camera_snapshot/20251008/180629_screenshot.jpg"
}
```

### 4.3 Validation Checklist
- [ ] R2 credentials are correctly loaded from environment variables
- [ ] Image is successfully downloaded from R2
- [ ] Image format is correctly detected
- [ ] Source URL is correctly constructed
- [ ] Analysis results are returned successfully
- [ ] Error handling works for missing objects
- [ ] Error handling works for invalid credentials

---

## Phase 5: Deployment Steps

### 5.1 Pre-deployment
1. **Set environment variables** in your deployment environment:
   ```bash
   export R2_ACCESS_KEY_ID="..."
   export R2_SECRET_ACCESS_KEY="..."
   export R2_ENDPOINT="..."
   export R2_BUCKET_NAME="..."
   export R2_PUBLIC_URL="..."
   ```

2. **Verify R2 access** using AWS CLI or boto3:
   ```bash
   aws s3 ls s3://your-bucket/ --endpoint-url https://your-account.r2.cloudflarestorage.com
   ```

### 5.2 Build and Package
```bash
# Build dependencies and function package
./build.sh

# Or use the Python script
python package_for_lambda.py
```

### 5.3 Deploy with CDK
```bash
cd deployment
cdk deploy
```

### 5.4 Post-deployment Verification
1. Test Lambda function with new object_key parameter
2. Monitor CloudWatch logs for any errors
3. Verify image download and analysis works correctly

---

## Phase 6: Migration Strategy

### 6.1 For Backward Compatibility (Option A)
1. Deploy new version with both `object_key` and `image_path` support
2. Update clients to use `object_key` parameter gradually
3. Monitor usage of deprecated `image_path` parameter
4. After migration period, remove `image_path` support

### 6.2 For Clean Break (Option B)
1. Deploy new version with only `object_key` support
2. Update all clients to use `object_key` parameter immediately
3. No migration period needed

---

## Phase 7: Security Considerations

### 7.1 Credential Management
- **Never hardcode** R2 credentials in code
- Store credentials in AWS Systems Manager Parameter Store or Secrets Manager (recommended)
- Rotate R2 access keys periodically

### 7.2 Enhanced Security (Optional)
Update deployment to use AWS Secrets Manager:

**deployment.go enhancement**:
```go
// Import Secrets Manager
import "github.com/aws/aws-cdk-go/awscdk/v2/awssecretsmanager"

// Create secret
r2CredsSecret := awssecretsmanager.Secret_FromSecretNameV2(
    stack, 
    jsii.String("R2Credentials"),
    jsii.String("prod/r2/credentials"),
)

// Grant read permissions
r2CredsSecret.GrantRead(lambdaFunc, nil)

// Use in environment
Environment: &map[string]*string{
    "R2_CREDENTIALS_SECRET_ARN": r2CredsSecret.SecretArn(),
},
```

**agent.py enhancement**:
```python
# Load credentials from Secrets Manager
def get_r2_credentials():
    secret_arn = os.environ.get("R2_CREDENTIALS_SECRET_ARN")
    if secret_arn:
        secrets_client = boto3.client('secretsmanager')
        secret = secrets_client.get_secret_value(SecretId=secret_arn)
        return json.loads(secret['SecretString'])
    return {
        'access_key_id': os.environ.get('R2_ACCESS_KEY_ID'),
        'secret_access_key': os.environ.get('R2_SECRET_ACCESS_KEY'),
        # ...
    }
```

---

## Phase 8: Error Handling Improvements

### 8.1 R2-Specific Error Handling

Add comprehensive error handling for R2 operations:

```python
from botocore.exceptions import ClientError, NoCredentialsError

def download_image_from_r2(object_key: str) -> tuple[bytes, str]:
    try:
        # ... existing code ...
    except NoCredentialsError:
        l.error("R2 credentials not found")
        raise ValueError("R2 credentials not configured properly")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchKey':
            l.error(f"Object not found in R2: {object_key}")
            raise ValueError(f"Image not found: {object_key}")
        elif error_code == 'AccessDenied':
            l.error(f"Access denied to R2 object: {object_key}")
            raise ValueError("Access denied to R2 storage")
        else:
            l.error(f"R2 client error: {e}")
            raise
    except Exception as e:
        l.error(f"Unexpected error downloading from R2: {e}")
        raise
```

---

## Phase 9: Monitoring and Observability

### 9.1 CloudWatch Metrics

Add custom metrics for R2 operations:

```python
import boto3

cloudwatch = boto3.client('cloudwatch')

def put_metric(metric_name: str, value: float):
    cloudwatch.put_metric_data(
        Namespace='CameraFootageAnalysis',
        MetricData=[{
            'MetricName': metric_name,
            'Value': value,
            'Unit': 'Count'
        }]
    )

# In download_image_from_r2:
start_time = time.time()
# ... download logic ...
duration = time.time() - start_time
put_metric('R2DownloadDuration', duration)
put_metric('R2DownloadSuccess', 1)
```

### 9.2 Logging Enhancements

```python
l.info(f"R2 Config - Endpoint: {R2_ENDPOINT}, Bucket: {R2_BUCKET_NAME}")
l.info(f"Downloading from R2: bucket={R2_BUCKET_NAME}, key={object_key}")
l.info(f"Download complete: {len(image_bytes)} bytes, format={image_format}")
```

---

## Phase 10: Documentation Updates

### 10.1 Update README

Add section about R2 configuration:

```markdown
## Environment Variables

### Required
- `APPLICATION_INFERENCE_PROFILE_ARN`: Bedrock inference profile ARN
- `R2_ACCESS_KEY_ID`: Cloudflare R2 access key ID
- `R2_SECRET_ACCESS_KEY`: Cloudflare R2 secret access key
- `R2_ENDPOINT`: R2 endpoint URL
- `R2_BUCKET_NAME`: R2 bucket name

### Optional
- `APP_DEBUG`: Log level (default: WARNING)
- `R2_PUBLIC_URL`: Public URL base for constructing source URLs
```

### 10.2 API Documentation

Document the new event schema:

```json
{
  "object_key": "camera_snapshot/YYYYMMDD/HHMMSS_screenshot.jpg"
}
```

---

## Summary Checklist

### Development Phase
- [ ] Update deployment.go with R2 environment variables
- [ ] Add R2 configuration constants to agent.py
- [ ] Implement download_image_from_r2() function
- [ ] Update handler() to use object_key parameter
- [ ] Add comprehensive error handling
- [ ] Update test code in __main__ block

### Testing Phase
- [ ] Test locally with R2 credentials
- [ ] Test with valid object keys
- [ ] Test error cases (missing object, invalid credentials)
- [ ] Validate image format detection
- [ ] Verify source URL construction

### Deployment Phase
- [ ] Set R2 environment variables in deployment environment
- [ ] Build Lambda packages
- [ ] Deploy with CDK
- [ ] Test deployed Lambda with test events
- [ ] Monitor CloudWatch logs

### Documentation Phase
- [ ] Update README with R2 configuration
- [ ] Document new API schema
- [ ] Create migration guide for clients
- [ ] Update operational runbooks

---

## Rollback Plan

If issues occur after deployment:

1. **Quick Rollback**: 
   - Revert to previous Lambda version using AWS Console
   - Or redeploy previous CDK stack

2. **Environment Variable Fix**:
   - Update Lambda environment variables in AWS Console
   - No code deployment needed

3. **Data Recovery**:
   - Original images remain in R2
   - No data loss expected

---

## Timeline Estimate

- **Phase 1 (Environment Variables)**: 30 minutes
- **Phase 2 (Lambda Refactoring)**: 2-3 hours
- **Phase 3 (IAM - N/A for R2)**: 0 minutes
- **Phase 4 (Testing)**: 1-2 hours
- **Phase 5 (Deployment)**: 30 minutes
- **Phase 6 (Migration)**: Varies based on strategy
- **Phase 7 (Security Enhancements)**: 1-2 hours (optional)
- **Phase 8 (Error Handling)**: 1 hour
- **Phase 9 (Monitoring)**: 1 hour (optional)
- **Phase 10 (Documentation)**: 1 hour

**Total**: 8-12 hours for complete implementation and testing

---

## Next Steps

1. Review and approve this plan
2. Set up R2 credentials and test access
3. Begin Phase 1: Update deployment.go
4. Proceed with Phase 2: Lambda refactoring
5. Test thoroughly before production deployment
