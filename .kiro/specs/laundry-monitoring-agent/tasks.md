# Implementation Plan

- [x] 1. Create Pydantic response models for structured output
  - Create `src/models/laundry_analysis_response.py` with `LaundryAnalysisResponse` and `LocalizedLaundryAnalysisResponse` models
  - Define all required fields: laundry_detected, laundry_description, weather_risk_level, weather_summary, recommendation, recommendation_reason, confidence, timestamp, image_url
  - Add field validators for confidence score (0.0-1.0 range) and timestamp (ISO 8601 format)
  - Include comprehensive field descriptions to guide AI model output
  - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 5.2_


- [x] 3. Implement Lambda handler function
  - Create `src/laundry_monitoring_agent.py` with `handler(event, context)` function
  - Parse and validate input event for required fields (file_key, weather_data)
  - Validate weather_data structure (current_hour and next_hour with all required fields)
  - Implement error handling for missing or malformed input
  - Return structured error response for validation failures
  - _Requirements: 6.1, 6.4_

- [x] 4. Implement R2 storage integration
  - Configure boto3 S3 client with R2 endpoint from environment variables
  - Implement image retrieval using file_key from event
  - Add error handling for missing images, connection timeouts, and invalid credentials
  - Validate file_key format to prevent path traversal attacks
  - _Requirements: 6.2, 6.5_

- [x] 5. Implement presigned URL generation
  - Create function to generate presigned URLs with 7-day expiration
  - Use boto3 `generate_presigned_url` method with appropriate parameters
  - Include presigned URL in response image_url field
  - _Requirements: 6.6, 4.8_

- [x] 6. Create system prompt for Bedrock agent
  - Write comprehensive system prompt covering all analysis requirements
  - Include instructions for laundry rack detection in open air areas
  - Add guidance for location identification (left/right/center, near landmarks)
  - Specify item description requirements (type, quantity, colors)
  - Define weather risk assessment criteria (rain, temperature, wind)
  - Include recommendation logic (bring_inside, leave_outside, no_action)
  - Add bilingual output requirements (English and Simplified Chinese)
  - Specify confidence scoring guidelines for image quality issues
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 7. Implement Bedrock agent invocation
  - Initialize Bedrock client using boto3
  - Load JSON schema for structured output
  - Prepare agent input with image URL and weather data
  - Format weather data into natural language description for the prompt
  - Invoke Bedrock model with system prompt, image, and weather context
  - Configure timeout and retry logic
  - Add error handling for model invocation failures, timeouts, and rate limiting
  - _Requirements: 2.1, 2.2, 6.5_

- [x] 8. Implement response validation and parsing
  - Parse Bedrock response JSON
  - Validate response against Pydantic models
  - Handle validation errors (missing fields, invalid types, constraint violations)
  - Verify timestamp is in ISO 8601 format
  - Verify confidence score is in 0.0-1.0 range
  - Add presigned URL to validated response
  - Generate current timestamp for analysis
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

- [x] 9. Implement success response formatting
  - Create response structure with data.result containing en and zh_CN localizations
  - Ensure both language versions are included in every response
  - Return HTTP 200 status with structured JSON
  - _Requirements: 5.1, 5.2, 6.3_

- [x] 10. Implement comprehensive error handling
  - Add try-except blocks around major operations (input validation, R2 retrieval, Bedrock invocation, response validation)
  - Create structured error response format with message, details, and error_code
  - Map error categories to appropriate error codes (INPUT_VALIDATION, STORAGE_ERROR, BEDROCK_ERROR, VALIDATION_ERROR)
  - Log errors with appropriate severity levels
  - Avoid exposing sensitive information in error messages
  - _Requirements: 4.9, 6.4_

- [x] 11. Configure environment variables
  - Document required environment variables in code comments
  - Add environment variable validation on Lambda initialization
  - Required variables: APPLICATION_INFERENCE_PROFILE_ARN, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL, R2_BUCKET_NAME, APP_DEBUG
  - _Requirements: 6.5_

- [x] 12. Update CDK deployment stack
  - Open `deployment/deployment.go`
  - Add new Lambda function resource for laundry monitoring agent
  - Configure function properties: handler=laundry_monitoring_agent.handler, runtime=Python 3.13, memory=256MB, timeout=30s, architecture=ARM64
  - Add environment variables for R2 configuration and Bedrock ARN
  - Attach dependencies layer (reuse existing layer from security cam analyzer)
  - Add IAM permissions for bedrock:InvokeModel and bedrock:InvokeModelWithResponseStream
  - _Requirements: 6.1, 6.5_

- [x] 13. Update build script
  - Modify `build.sh` to include laundry_monitoring_agent.py in Lambda package
  - Ensure models/laundry_analysis_response.py and schema JSON are included
  - Verify dependencies (boto3, pydantic) are in requirements.txt
  - _Requirements: 6.1_

- [x] 14. Create deployment documentation
  - Document deployment steps in deployment/README.md
  - Include environment variable configuration instructions
  - Add example event payload for testing
  - Document expected response format
  - _Requirements: 6.1, 6.5_
