# Design Document

## Overview

The Household Laundry Monitoring Agent is an AWS Lambda-based intelligent system that analyzes security camera images to detect laundry racks in open air areas (specifically car porch areas) and provides weather-aware recommendations. The agent leverages Amazon Bedrock's vision-language models to perform image analysis and combines this with weather forecast data to deliver actionable insights in multiple languages.

The system follows the same architectural pattern as the existing security camera analyzer agent, utilizing R2 storage for image retrieval, Bedrock for AI inference, and structured Pydantic models for response validation.

### Requirements Coverage

This design addresses all six requirements from the requirements document:

1. **Requirement 1 (Image Analysis)**: Bedrock vision-language model analyzes images to detect laundry racks, identify locations, describe items, and report confidence levels
2. **Requirement 2 (Weather Integration)**: Event schema accepts current and upcoming hour weather data; system prompt instructs analysis of temperature, conditions, and precipitation
3. **Requirement 3 (Risk Assessment)**: Risk assessment logic evaluates weather factors and generates recommendations with confidence scores
4. **Requirement 4 (Structured JSON)**: Pydantic models define and validate all required JSON fields (detection status, description, risk, recommendation, confidence, timestamp, image URL)
5. **Requirement 5 (Multi-Language)**: LocalizedLaundryAnalysisResponse provides both English and Simplified Chinese translations with consistent meaning
6. **Requirement 6 (Lambda Integration)**: Lambda handler accepts event with file_key and weather_data, retrieves from R2, uses environment variables, generates presigned URLs, and returns structured responses

## Architecture

### High-Level Architecture

```
┌─────────────────┐
│   API Gateway   │
│   or Trigger    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│           AWS Lambda Function                            │
│  (laundry_monitoring_agent.handler)                     │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │  1. Parse Event (image key + weather data)       │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     ▼                                    │
│  ┌──────────────────────────────────────────────────┐  │
│  │  2. Retrieve Image from R2 Storage               │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     ▼                                    │
│  ┌──────────────────────────────────────────────────┐  │
│  │  3. Generate Presigned URL                       │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     ▼                                    │
│  ┌──────────────────────────────────────────────────┐  │
│  │  4. Prepare Agent Input (image + weather)        │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     ▼                                    │
│  ┌──────────────────────────────────────────────────┐  │
│  │  5. Invoke Bedrock Agent with Structured Output  │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     ▼                                    │
│  ┌──────────────────────────────────────────────────┐  │
│  │  6. Return Localized JSON Response               │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│  JSON Response  │
│  (en + zh_CN)   │
└─────────────────┘

External Dependencies:
- R2 Storage (Cloudflare)
- Amazon Bedrock (Vision-Language Model)
```

### Component Interaction Flow

1. **Event Reception**: Lambda receives event with `file_key`, `current_time`, and `weather_forecast`
2. **Weather Extraction**: Transforms Home Assistant forecast format to internal format using `current_time`
3. **Image Retrieval**: Downloads image from R2 using boto3 S3 client
4. **URL Generation**: Creates presigned URL for image reference (7-day expiration)
5. **Agent Initialization**: Sets up Bedrock agent with custom system prompt
6. **Analysis Execution**: Sends image and weather data to Bedrock for analysis
7. **Response Validation**: Validates output against Pydantic schema
8. **Result Return**: Returns structured JSON with bilingual analysis

## Image Analysis Strategy

### Detection Approach (Requirement 1)

The Bedrock vision-language model will analyze images using the following strategy:

1. **Laundry Rack Detection** (Requirement 1.1)
   - Identify physical structures typical of laundry racks (poles, horizontal bars, hanging mechanisms)
   - Detect clothes, bedsheets, towels, or other fabric items hanging in open air
   - Distinguish between indoor and outdoor areas (focus on open air/car porch areas)

2. **Location Identification** (Requirement 1.2)
   - Describe position within the frame using relative terms:
     - Horizontal: "left side", "center", "right side"
     - Depth: "near gate", "back of porch", "foreground"
     - Specific landmarks: "near car", "by the wall", "under roof overhang"

3. **Item Description** (Requirement 1.3)
   - Identify item types: clothes (shirts, pants), bedsheets, towels, blankets
   - Estimate quantity: "several items", "full rack", "a few pieces"
   - Note colors or distinctive features when visible

4. **No Detection Handling** (Requirement 1.4)
   - Return explicit "No laundry detected" message when no racks or items found
   - Distinguish between "no laundry" and "unable to determine"

5. **Quality Assessment** (Requirement 1.5)
   - Evaluate image clarity, lighting, obstructions
   - Report low confidence (<0.5) for:
     - Poor lighting (too dark, overexposed)
     - Obstructions (objects blocking view)
     - Low resolution or blurry images
     - Adverse weather in image (fog, heavy rain)

**Design Rationale**: The vision-language model's natural language understanding allows for flexible, context-aware analysis. By providing detailed instructions in the system prompt, we guide the model to focus on relevant features while maintaining the ability to handle varied scenarios (different rack types, lighting conditions, camera angles).

## Components and Interfaces

### 1. Lambda Handler Function

**File**: `src/laundry_monitoring_agent.py`

**Signature**:
```python
def handler(event: Dict[str, Any], context) -> Dict[str, Any]
```

**Input Event Schema** (per Requirement 6.1):
```python
{
    "file_key": str,  # R2 object key (e.g., "camera_snapshot/20251110/120000_porch.jpg")
    "current_time": str,  # ISO 8601 timestamp for current time context (e.g., "2025-10-12T02:00:00+00:00")
    "weather_forecast": {  # Home Assistant weather entity structure
        "<entity_id>": {  # e.g., "weather.forecast_home"
            "forecast": [  # Array of hourly forecasts
                {
                    "condition": str,  # e.g., "clear", "cloudy", "rainy" - for adverse condition detection (Req 2.4)
                    "datetime": str,  # ISO 8601 timestamp
                    "temperature": float,  # Celsius - for temperature analysis (Req 2.3)
                    "wind_speed": float,  # km/h - for wind risk assessment (Req 3.4)
                    "precipitation": float,  # 0-1 range (converted to percentage) - for rain risk flagging (Req 2.5)
                    "humidity": float,  # Percentage
                    "wind_bearing": float,  # Optional
                    "cloud_coverage": float,  # Optional
                    "uv_index": float  # Optional
                },
                # ... more hourly forecasts
            ]
        }
    }
}
```

**Design Rationale**: The event schema uses Home Assistant's native weather forecast format with entity IDs, providing a forecast array with datetime stamps. The `current_time` parameter enables intelligent matching of forecast entries to current and next hour, making the system robust to varying forecast intervals and start times. The Lambda function extracts relevant forecast entries and transforms them into the internal format (current_hour/next_hour) for analysis, addressing Requirements 2.1, 2.2, 2.3, and 2.5.

**Output Schema** (per Requirements 4 & 5):
```python
{
    "data": {
        "result": {
            "en": LaundryAnalysisResponse,    # Requirement 5.1: English localization
            "zh_CN": LaundryAnalysisResponse  # Requirement 5.2: Simplified Chinese localization
        }
    }
}
# OR on error (Requirement 4.9):
{
    "errors": [
        {
            "message": str,     # Human-readable error message
            "details": str,     # Technical error details
            "error_code": str   # Error category code
        }
    ]
}
```

**Design Rationale**: The dual-language structure at the top level ensures both localizations are always provided together, maintaining consistency. The error format provides both user-friendly messages and technical details for debugging, satisfying Requirement 4.9.

**Responsibilities**:
- Parse and validate input event containing file_key, current_time, and weather_forecast (Requirement 6.1)
- Extract and transform weather forecast data using current_time to identify relevant forecast entries
- Retrieve image from R2 storage using provided file key (Requirement 6.2)
- Generate presigned URL for image with 7-day expiration (Requirement 6.6)
- Initialize Bedrock agent with specialized system prompt
- Orchestrate analysis workflow combining image and weather data
- Return HTTP 200 with analysis results on success (Requirement 6.3)
- Handle errors and return structured error responses (Requirement 6.4)
- Use environment variables for R2 credentials and Bedrock model ARN (Requirement 6.5)

**Design Rationale**: The handler acts as the orchestration layer, delegating specific tasks to specialized components while maintaining overall control flow. This separation of concerns makes the code maintainable and testable.

### 2. Pydantic Response Models

**File**: `src/models/laundry_analysis_response.py`

**Models**:

```python
class LaundryAnalysisResponse(BaseModel):
    """Single language analysis response - addresses Requirements 4 & 5"""
    
    laundry_detected: bool = Field(
        description="Whether laundry racks were detected in the image (Requirement 4.2)"
    )
    
    laundry_description: str = Field(
        description="Description of detected laundry items and location (Requirement 4.3). "
                    "Include location (e.g., 'left side of porch') and item types "
                    "(e.g., 'clothes', 'bedsheets', 'towels'). "
                    "If no laundry detected, return 'No laundry detected' (Requirement 1.4)"
    )
    
    weather_risk_level: str = Field(
        description="Risk level based on weather: 'low', 'medium', 'high' (Requirement 4.4)"
    )
    
    weather_summary: str = Field(
        description="Brief summary of weather conditions and risks (max 50 words). "
                    "Include current and upcoming conditions, temperature changes, "
                    "precipitation probability, and wind speed."
    )
    
    recommendation: str = Field(
        description="Action recommendation (Requirement 4.5): 'bring_inside', 'leave_outside', 'no_action'"
    )
    
    recommendation_reason: str = Field(
        description="Explanation for the recommendation (max 100 words). "
                    "Reference specific weather factors and risk assessment."
    )
    
    notification_title: str = Field(
        description="Concise, actionable notification title for push notifications (Requirement 4.9). "
                    "Max 60 characters. Should clearly indicate the action needed or status. "
                    "Examples: 'Bring Laundry Inside!', 'Rain Coming Soon', 'Laundry Safe Outside' (Requirement 5.6)"
    )
    
    notification_message: str = Field(
        description="Clear, informative notification message for mobile notifications (Requirement 4.10). "
                    "Max 200 characters. Should provide key details about weather risk and recommendation. "
                    "Examples: 'Rain forecasted in 1 hour. Laundry detected on left side of porch.' (Requirement 5.7)"
    )
    
    confidence: float = Field(
        description="Confidence score for the analysis (0.0-1.0) (Requirements 3.6, 4.6). "
                    "Lower confidence for poor image quality or obstructed views.",
        ge=0.0,
        le=1.0
    )
    
    timestamp: str = Field(
        description="ISO 8601 timestamp of analysis (Requirement 4.7)"
    )
    
    image_url: str = Field(
        description="Presigned URL (7 days expiration) of the analyzed image (Requirement 4.8)"
    )


class LocalizedLaundryAnalysisResponse(BaseModel):
    """Multi-language response wrapper - addresses Requirement 5"""
    
    en: LaundryAnalysisResponse = Field(
        description="English localization of the analysis (Requirement 5.1). "
                    "Includes notification_title and notification_message fields (Requirements 5.6, 5.7)"
    )
    
    zh_CN: LaundryAnalysisResponse = Field(
        description="Simplified Chinese localization of the analysis (Requirement 5.2). "
                    "All text fields including notification_title and notification_message "
                    "translated while maintaining consistent meaning (Requirements 5.3, 5.4)"
    )
```

**Design Rationale**: The Pydantic models serve dual purposes: they validate the AI model's output structure and provide field descriptions that guide the AI in generating appropriate responses. Each field maps directly to requirements, ensuring complete coverage. The confidence score field specifically addresses image quality concerns from Requirement 1.5.

**Responsibilities**:
- Define structured output schema matching Requirement 4 (JSON format with all required fields)
- Validate response data types and constraints (e.g., confidence 0.0-1.0, ISO 8601 timestamps)
- Provide field descriptions for AI model guidance to ensure requirement compliance
- Support multi-language responses per Requirement 5 (English and Simplified Chinese)
- Ensure all required fields from Requirements 4.2-4.8 are present and validated

**Design Rationale**: Using Pydantic for schema definition provides automatic validation, clear documentation, and type safety. The field descriptions double as instructions for the AI model, reducing the chance of missing or incorrectly formatted data.

### 3. Bedrock Agent Configuration

**System Prompt**:

The agent will use a specialized system prompt that instructs the model to:
- Analyze images for laundry racks and items in open air areas (Requirement 1)
- Identify location within the image (e.g., "left side of porch", "center area") (Requirement 1.2)
- Describe type and quantity of laundry items (e.g., "clothes", "bedsheets", "towels") (Requirement 1.3)
- Consider weather data in risk assessment (Requirement 2)
- Evaluate temperature changes, rain forecasts, and wind conditions (Requirements 2.3, 2.4, 2.5)
- Provide location-specific descriptions
- Generate actionable recommendations with confidence scores (Requirement 3)
- Return bilingual responses in English and Simplified Chinese (Requirement 5)

**Key Prompt Elements**:
1. **Role definition**: Household assistant specializing in laundry monitoring for car porch areas
2. **Analysis criteria**: 
   - Detect laundry racks in open air areas
   - Identify location within frame (left/right/center of porch, near gate, etc.)
   - Describe visible items (clothes, bedsheets, towels, quantity)
   - Report "no laundry detected" when none found (Requirement 1.4)
   - Assess image quality and report low confidence if poor/obstructed (Requirement 1.5)
3. **Weather interpretation**: 
   - Analyze current hour and next hour forecasts
   - Identify rain, storms, or adverse conditions as risk factors
   - Consider temperature changes for drying efficiency
   - Evaluate wind speed for displacement risk
4. **Recommendation logic**: 
   - High urgency for rain forecasts (Requirement 3.1)
   - Safe to leave outside in clear weather (Requirement 3.2)
   - Consider temperature drops for drying efficiency (Requirement 3.3)
   - Warn about strong winds (Requirement 3.4)
   - No action when no laundry detected (Requirement 3.5)
   - Include confidence score 0.0-1.0 (Requirement 3.6)
5. **Output format**: Structured JSON matching Pydantic schema (Requirement 4)
6. **Language requirements**: 
   - Provide complete analysis in English (en) (Requirement 5.1)
   - Provide complete analysis in Simplified Chinese (zh_CN) (Requirement 5.2)
   - Translate all text fields including notification_title and notification_message (Requirement 5.3)
   - Maintain consistent meaning across languages (Requirement 5.4)
   - Use original terms with explanation for untranslatable technical terms (Requirement 5.5)
   - Create concise notification titles (max 60 characters) (Requirement 5.6)
   - Create clear notification messages (max 200 characters) (Requirement 5.7)

**Design Rationale**: The system prompt is structured to directly address each requirement, ensuring the AI model receives clear instructions for all analysis aspects. The prompt emphasizes location-specific descriptions and multi-factor weather assessment to provide actionable insights.

### 4. R2 Storage Integration

**Configuration** (per Requirement 6.5):
- Endpoint URL: From environment variable `R2_ENDPOINT_URL`
- Access credentials: `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
- Bucket: `R2_BUCKET_NAME`
- Region: "auto" (Cloudflare R2)

**Operations**:
- `get_object`: Retrieve image bytes using file_key from event (Requirement 6.2)
- `generate_presigned_url`: Create 7-day access URL (Requirement 6.6)

**Design Rationale**: R2 storage provides cost-effective image storage with S3-compatible API. The 7-day presigned URL expiration balances security (limited access window) with usability (sufficient time for viewing historical analyses). Using environment variables for credentials follows security best practices and enables easy configuration across environments.

### 5. AWS CDK Deployment Stack

**File**: `deployment/deployment.go`

**New Lambda Function**:
```go
laundryMonitoringFunc := awslambda.NewFunction(
    stack, 
    jsii.String("laundryMonitoringAgentFunction"),
    &awslambda.FunctionProps{
        Code:         awslambda.AssetCode_FromAsset(...),
        Handler:      jsii.String("laundry_monitoring_agent.handler"),
        Runtime:      awslambda.Runtime_PYTHON_3_13(),
        MemorySize:   jsii.Number(256),
        Timeout:      awscdk.Duration_Seconds(jsii.Number(30)),
        Layers:       &[]awslambda.ILayerVersion{dependenciesLayer},
        Architecture: awslambda.Architecture_ARM_64(),
        Environment:  &map[string]*string{...},
    },
)
```

**IAM Permissions**:
- `bedrock:InvokeModel`
- `bedrock:InvokeModelWithResponseStream`

## Data Models

### Weather Data Structure

```python
class WeatherCondition(BaseModel):
    temperature: float
    condition: str  # Enum: clear, cloudy, rainy, stormy, etc.
    humidity: float
    wind_speed: float
    precipitation_probability: Optional[float] = None

class WeatherData(BaseModel):
    current_hour: WeatherCondition
    next_hour: WeatherCondition
```

### Risk Assessment Logic

**Weather Risk Levels**:
- **Low**: Clear conditions, no rain forecast, moderate wind (<20 km/h), stable temperature
- **Medium**: Cloudy, low precipitation probability (<30%), high wind (>20 km/h), or significant temperature drops
- **High**: Rain forecast, high precipitation probability (≥30%), storms, or strong winds (>40 km/h)

**Design Rationale**: The three-tier risk system provides clear categorization for decision-making. Medium risk is treated cautiously to prevent laundry damage, aligning with Requirement 3 which emphasizes protecting laundry from adverse conditions.

**Recommendation Logic**:
```
IF laundry_detected AND weather_risk_level == "high":
    recommendation = "bring_inside"
    urgency = "high"
ELIF laundry_detected AND weather_risk_level == "medium":
    recommendation = "bring_inside" (cautious approach)
    urgency = "medium"
ELIF laundry_detected AND weather_risk_level == "low":
    recommendation = "leave_outside"
    urgency = "low"
ELSE:
    recommendation = "no_action"
    urgency = "none"
```

**Weather Factors Considered** (per Requirement 2):
1. **Rain/Precipitation**: Primary risk factor for wet laundry
2. **Temperature Changes**: Affects drying efficiency during daytime
3. **Wind Speed**: Risk of laundry displacement or damage
4. **Weather Conditions**: Storms, clouds, or clear skies

**Design Rationale**: The recommendation logic prioritizes laundry protection over convenience. When in doubt (medium risk), the system recommends bringing laundry inside to prevent potential damage. This conservative approach aligns with homeowner expectations in Requirement 3.

## Error Handling

### Error Categories

1. **Input Validation Errors** (Requirement 6.4)
   - Missing required fields (`file_key`, `current_time`, `weather_forecast`)
   - Invalid current_time format (not ISO 8601)
   - Invalid weather_forecast structure (missing entity, missing forecast array, insufficient entries)
   - Invalid forecast item fields (missing required fields, invalid datetime format)
   - Malformed event structure
   - Invalid file_key format (path traversal attempts)

2. **Storage Errors** (Requirement 6.4)
   - Image not found in R2 (invalid file_key)
   - R2 connection timeout
   - Invalid credentials (misconfigured environment variables)
   - Network connectivity issues

3. **Image Processing Errors**
   - Corrupted image file
   - Unsupported image format (only JPEG/PNG supported)
   - Image too large (exceeds Lambda memory limits)
   - Empty or zero-byte image file

4. **Bedrock Errors** (Requirement 6.4)
   - Model invocation failure (invalid ARN or permissions)
   - Timeout during inference (>30 seconds)
   - Invalid model response (doesn't match expected format)
   - Rate limiting or throttling

5. **Validation Errors** (Requirement 4.9)
   - Response doesn't match Pydantic schema
   - Missing required fields in AI output (e.g., confidence score)
   - Invalid data types (e.g., confidence not in 0.0-1.0 range)
   - Timestamp not in ISO 8601 format

### Error Response Format (Requirement 4.9)

```python
{
    "errors": [
        {
            "message": "Human-readable error message",
            "details": "Technical details and stack trace",
            "error_code": "ERROR_CATEGORY_CODE"
        }
    ]
}
```

**Design Rationale**: The structured error format provides both user-facing messages and technical details for debugging. Error codes enable programmatic error handling by client applications. This format satisfies Requirement 4.9 for structured error responses with error details.

### Error Handling Strategy

- Use try-except blocks around each major operation (image retrieval, Bedrock invocation, validation)
- Log errors with appropriate severity levels (ERROR for failures, WARNING for retryable issues)
- Return structured error responses per Requirement 4.9
- Include context for debugging (file_key, operation stage, timestamp)
- Avoid exposing sensitive information (credentials, internal paths)
- Return appropriate HTTP status codes (400 for validation errors, 500 for internal errors)

**Design Rationale**: Comprehensive error handling ensures the Lambda function fails gracefully and provides actionable information for troubleshooting. Structured errors enable monitoring and alerting on specific failure patterns.



## Configuration and Environment Variables

### Required Environment Variables

```bash
# Bedrock Configuration
APPLICATION_INFERENCE_PROFILE_ARN=arn:aws:bedrock:region:account:application-inference-profile/id

# Logging
APP_DEBUG=WARNING  # DEBUG, INFO, WARNING, ERROR

# R2 Storage Configuration
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_ENDPOINT_URL=https://your-account.r2.cloudflarestorage.com
R2_BUCKET_NAME=your_bucket_name
```

### CDK Deployment Configuration

- Stack name: `LaundryMonitoringAgentDeploymentStack`
- Function name: `laundryMonitoringAgentFunction`
- Memory: 256 MB
- Timeout: 30 seconds
- Runtime: Python 3.13
- Architecture: ARM64

## Performance Considerations

### Optimization Strategies

1. **Image Processing**
   - Stream image bytes directly to Bedrock
   - Avoid unnecessary image transformations
   - Support common formats (JPEG, PNG)

2. **Lambda Cold Start**
   - Use ARM64 architecture for better performance
   - Keep dependencies minimal
   - Reuse boto3 clients across invocations

3. **Response Time**
   - Target: < 10 seconds for typical analysis
   - Bedrock inference: ~5-8 seconds
   - R2 retrieval: ~1-2 seconds

4. **Memory Usage**
   - 256 MB should be sufficient
   - Monitor actual usage and adjust if needed

### Monitoring

- CloudWatch Logs for debugging
- CloudWatch Metrics for performance
- Track invocation count, duration, errors
- Set up alarms for high error rates

## Security Considerations

1. **Credentials Management**
   - Store R2 credentials in environment variables
   - Use IAM roles for Bedrock access
   - Never log sensitive credentials

2. **Image Access**
   - Use presigned URLs with expiration
   - Validate file keys before retrieval
   - Prevent path traversal attacks

3. **Input Validation**
   - Validate all input parameters
   - Sanitize file keys
   - Check weather data ranges

4. **Output Sanitization**
   - Avoid exposing internal errors
   - Sanitize error messages
   - Don't include stack traces in production

## Future Enhancements

1. **Advanced Weather Integration**
   - Support hourly forecasts for next 24 hours
   - Include UV index for fabric protection
   - Add pollen count for allergy considerations

2. **Smart Notifications**
   - Send alerts when action needed
   - Integration with home automation systems
   - SMS/email notification support

3. **Historical Analysis**
   - Track laundry patterns over time
   - Learn optimal drying times
   - Predict best times to hang laundry

4. **Multi-Camera Support**
   - Analyze multiple camera angles
   - Combine views for better detection
   - Support different outdoor areas

5. **Enhanced Detection**
   - Identify specific clothing items
   - Detect if laundry is dry
   - Estimate drying time remaining
