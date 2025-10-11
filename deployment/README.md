# Laundry Monitoring Agent Deployment

This CDK project deploys the Household Laundry Monitoring Agent as an AWS Lambda function. The agent analyzes security camera images to detect laundry racks in open air areas and provides weather-aware recommendations.

## Architecture Overview

The deployment includes:
- **Lambda Function**: `laundryMonitoringAgentFunction` - Processes images and provides laundry monitoring analysis
- **Runtime**: Python 3.13 on ARM64 architecture
- **Dependencies Layer**: Shared layer containing boto3, pydantic, and other required packages
- **IAM Permissions**: Bedrock model invocation access
- **External Integrations**: Cloudflare R2 storage for image retrieval

## Prerequisites

Before deploying, ensure you have:

1. **AWS CLI** configured with appropriate credentials
2. **AWS CDK** installed (`npm install -g aws-cdk`)
3. **Go** 1.21 or later
4. **Python** 3.13 or later
5. **Cloudflare R2** bucket with security camera images
6. **Amazon Bedrock** access with a vision-language model

## Environment Variables Configuration

The Lambda function requires the following environment variables. Configure these in your `.env` file or directly in the CDK stack:

### Required Variables

```bash
# Bedrock Configuration
APPLICATION_INFERENCE_PROFILE_ARN=arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/your-profile-id
# The ARN of your Bedrock application inference profile with vision-language model access

# R2 Storage Configuration
R2_ACCESS_KEY_ID=your_r2_access_key_id
# Cloudflare R2 access key ID for image retrieval

R2_SECRET_ACCESS_KEY=your_r2_secret_access_key
# Cloudflare R2 secret access key

R2_ENDPOINT_URL=https://your-account-id.r2.cloudflarestorage.com
# Your Cloudflare R2 endpoint URL

R2_BUCKET_NAME=your-bucket-name
# The R2 bucket containing security camera images

# Logging Configuration
APP_DEBUG=WARNING
# Log level: DEBUG, INFO, WARNING, ERROR
```

### Setting Up Environment Variables

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and fill in your actual values:
   ```bash
   nano .env
   ```

3. The CDK stack will automatically load these variables during deployment

## Deployment Steps

### 1. Install Dependencies

```bash
# Install Go dependencies
go mod download

# Build the Lambda package (from project root)
cd ..
./build.sh
cd deployment
```

### 2. Bootstrap CDK (First Time Only)

If this is your first CDK deployment in this AWS account/region:

```bash
cdk bootstrap
```

### 3. Review Changes

Preview the changes that will be deployed:

```bash
cdk diff
```

### 4. Deploy the Stack

Deploy the Lambda function and all resources:

```bash
cdk deploy
```

Confirm the deployment when prompted.

### 5. Verify Deployment

After successful deployment, note the Lambda function ARN from the output:

```
Outputs:
LaundryMonitoringAgentDeploymentStack.LaundryMonitoringFunctionArn = arn:aws:lambda:us-east-1:123456789012:function:laundryMonitoringAgentFunction
```

## Testing the Lambda Function

### Example Event Payload

Use this example payload to test the Lambda function:

```json
{
  "file_key": "camera_snapshot/20251110/120000_porch.jpg",
  "weather_data": {
    "current_hour": {
      "temperature": 28.5,
      "condition": "cloudy",
      "humidity": 65.0,
      "wind_speed": 15.0
    },
    "next_hour": {
      "temperature": 27.0,
      "condition": "rainy",
      "humidity": 80.0,
      "wind_speed": 20.0,
      "precipitation_probability": 75.0
    }
  }
}
```

### Testing via AWS Console

1. Navigate to AWS Lambda console
2. Select `laundryMonitoringAgentFunction`
3. Go to the "Test" tab
4. Create a new test event with the example payload above
5. Click "Test" to invoke the function

### Testing via AWS CLI

```bash
aws lambda invoke \
  --function-name laundryMonitoringAgentFunction \
  --payload file://test_event.json \
  response.json

# View the response
cat response.json | jq
```

### Expected Response Format

#### Success Response (HTTP 200)

```json
{
  "data": {
    "result": {
      "en": {
        "laundry_detected": true,
        "laundry_description": "Laundry rack detected on the left side of the porch with several clothing items including shirts and pants hanging.",
        "weather_risk_level": "high",
        "weather_summary": "Current conditions are cloudy with 28.5°C. Rain is forecasted for the next hour with 75% precipitation probability and increasing wind speeds.",
        "recommendation": "bring_inside",
        "recommendation_reason": "High risk of rain within the next hour with 75% precipitation probability. Strong winds (20 km/h) may also cause laundry displacement. Recommend bringing laundry inside immediately to prevent it from getting wet.",
        "confidence": 0.85,
        "timestamp": "2025-11-10T12:00:00Z",
        "image_url": "https://your-account.r2.cloudflarestorage.com/your-bucket/camera_snapshot/20251110/120000_porch.jpg?X-Amz-Algorithm=..."
      },
      "zh_CN": {
        "laundry_detected": true,
        "laundry_description": "在门廊左侧检测到晾衣架，上面挂着几件衣物，包括衬衫和裤子。",
        "weather_risk_level": "high",
        "weather_summary": "当前天气多云，温度28.5°C。预计下一小时有雨，降水概率75%，风速增强。",
        "recommendation": "bring_inside",
        "recommendation_reason": "下一小时内有高降雨风险，降水概率为75%。强风（20公里/小时）也可能导致衣物移位。建议立即将衣物收进室内以防淋湿。",
        "confidence": 0.85,
        "timestamp": "2025-11-10T12:00:00Z",
        "image_url": "https://your-account.r2.cloudflarestorage.com/your-bucket/camera_snapshot/20251110/120000_porch.jpg?X-Amz-Algorithm=..."
      }
    }
  }
}
```

#### Error Response

```json
{
  "errors": [
    {
      "message": "Failed to retrieve image from R2 storage",
      "details": "The specified key does not exist: camera_snapshot/20251110/120000_porch.jpg",
      "error_code": "STORAGE_ERROR"
    }
  ]
}
```

### Response Field Descriptions

| Field                   | Type    | Description                                                            |
| ----------------------- | ------- | ---------------------------------------------------------------------- |
| `laundry_detected`      | boolean | Whether laundry racks were detected in the image                       |
| `laundry_description`   | string  | Description of detected laundry items and their location               |
| `weather_risk_level`    | string  | Risk level: "low", "medium", or "high"                                 |
| `weather_summary`       | string  | Brief summary of weather conditions and risks                          |
| `recommendation`        | string  | Action recommendation: "bring_inside", "leave_outside", or "no_action" |
| `recommendation_reason` | string  | Explanation for the recommendation                                     |
| `confidence`            | float   | Confidence score (0.0-1.0) for the analysis                            |
| `timestamp`             | string  | ISO 8601 timestamp of when the analysis was performed                  |
| `image_url`             | string  | Presigned URL (7-day expiration) of the analyzed image                 |

### Error Codes

| Error Code         | Description                                             |
| ------------------ | ------------------------------------------------------- |
| `INPUT_VALIDATION` | Invalid or missing required fields in the event payload |
| `STORAGE_ERROR`    | Failed to retrieve image from R2 storage                |
| `BEDROCK_ERROR`    | Error invoking Bedrock model or processing response     |
| `VALIDATION_ERROR` | Response validation failed against expected schema      |

## Event Payload Specification

### Required Fields

- **file_key** (string): The R2 object key for the security camera image
  - Example: `"camera_snapshot/20251110/120000_porch.jpg"`
  - Must be a valid path within the configured R2 bucket

- **weather_data** (object): Weather forecast data for analysis
  - **current_hour** (object): Current hour weather conditions
    - **temperature** (float): Temperature in Celsius
    - **condition** (string): Weather condition (e.g., "clear", "cloudy", "rainy")
    - **humidity** (float): Humidity percentage (0-100)
    - **wind_speed** (float): Wind speed in km/h
  - **next_hour** (object): Next hour weather forecast
    - **temperature** (float): Temperature in Celsius
    - **condition** (string): Weather condition
    - **humidity** (float): Humidity percentage (0-100)
    - **wind_speed** (float): Wind speed in km/h
    - **precipitation_probability** (float): Precipitation probability percentage (0-100)

## Monitoring and Troubleshooting

### CloudWatch Logs

View Lambda execution logs:

```bash
aws logs tail /aws/lambda/laundryMonitoringAgentFunction --follow
```

### Common Issues

1. **"Failed to retrieve image from R2 storage"**
   - Verify R2 credentials are correct in environment variables
   - Check that the file_key exists in the R2 bucket
   - Ensure R2_ENDPOINT_URL is correctly formatted

2. **"Bedrock invocation failed"**
   - Verify APPLICATION_INFERENCE_PROFILE_ARN is correct
   - Check IAM permissions include `bedrock:InvokeModel`
   - Ensure the Bedrock model supports vision inputs

3. **"Input validation error"**
   - Verify event payload matches the required schema
   - Check that all required fields are present
   - Ensure weather_data contains both current_hour and next_hour

4. **Timeout errors**
   - Lambda timeout is set to 30 seconds
   - Large images may take longer to process
   - Check CloudWatch logs for performance bottlenecks

### Performance Metrics

Monitor these CloudWatch metrics:
- **Invocations**: Total number of function invocations
- **Duration**: Execution time (target: <10 seconds)
- **Errors**: Failed invocations
- **Throttles**: Rate-limited requests

## Updating the Deployment

### Update Lambda Code

1. Make changes to the Python code in `src/`
2. Rebuild the Lambda package:
   ```bash
   cd ..
   ./build.sh
   cd deployment
   ```
3. Deploy the update:
   ```bash
   cdk deploy
   ```

### Update Environment Variables

1. Edit `.env` file with new values
2. Redeploy the stack:
   ```bash
   cdk deploy
   ```

### Update Dependencies

1. Modify `requirements.txt` in the project root
2. Rebuild and redeploy:
   ```bash
   cd ..
   ./build.sh
   cd deployment
   cdk deploy
   ```

## Cleanup

To remove all deployed resources:

```bash
cdk destroy
```

Confirm the deletion when prompted.

## CDK Commands Reference

 * `cdk deploy`      Deploy this stack to your default AWS account/region
 * `cdk diff`        Compare deployed stack with current state
 * `cdk synth`       Emit the synthesized CloudFormation template
 * `cdk destroy`     Remove all deployed resources
 * `go test`         Run unit tests for the CDK stack

## Additional Resources

- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [AWS Lambda Documentation](https://docs.aws.amazon.com/lambda/)
- [Amazon Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- [Cloudflare R2 Documentation](https://developers.cloudflare.com/r2/)

## Support

For issues or questions:
1. Check CloudWatch logs for detailed error messages
2. Review the requirements and design documents in `.kiro/specs/laundry-monitoring-agent/`
3. Verify all environment variables are correctly configured
