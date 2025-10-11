import json
import logging
import os
from typing import Any, Dict, Optional
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
from botocore.config import Config as BotocoreConfig
import re
from PIL import Image
import io

# Import strands for Bedrock agent
from strands import Agent
from strands.models import BedrockModel
from strands.types.agent import AgentInput

# Import Pydantic models
from models.laundry_analysis_response import LocalizedLaundryAnalysisResponse

# ============================================================================
# ENVIRONMENT VARIABLES CONFIGURATION (Task 11 - Requirement 6.5)
# ============================================================================
# 
# Required environment variables for Lambda function operation:
#
# 1. APPLICATION_INFERENCE_PROFILE_ARN (Required)
#    - AWS Bedrock application inference profile ARN
#    - Used for AI model invocation to analyze laundry images
#    - Format: arn:aws:bedrock:region:account:application-inference-profile/id
#    - Example: arn:aws:bedrock:ap-southeast-1:123456789012:application-inference-profile/abc123
#
# 2. R2_ACCESS_KEY_ID (Required)
#    - Cloudflare R2 storage access key ID
#    - Used for authenticating with R2 storage to retrieve images
#    - Obtain from Cloudflare R2 dashboard
#
# 3. R2_SECRET_ACCESS_KEY (Required)
#    - Cloudflare R2 storage secret access key
#    - Used for authenticating with R2 storage to retrieve images
#    - Keep this value secure and never log or expose it
#
# 4. R2_ENDPOINT_URL (Required)
#    - Cloudflare R2 storage endpoint URL
#    - Format: https://<account-id>.r2.cloudflarestorage.com
#    - Example: https://abc123.r2.cloudflarestorage.com
#
# 5. R2_BUCKET_NAME (Required)
#    - Name of the R2 bucket containing security camera images
#    - Example: security-camera-snapshots
#
# 6. APP_DEBUG (Optional)
#    - Logging level for the application
#    - Valid values: DEBUG, INFO, WARNING, ERROR, CRITICAL
#    - Default: WARNING
#    - Use DEBUG for development, WARNING or ERROR for production
#
# 7. BEDROCK_REGION (Optional)
#    - AWS region for Bedrock service
#    - Default: ap-southeast-1
#    - Should match the region in APPLICATION_INFERENCE_PROFILE_ARN
#
# ============================================================================

# Load environment variables
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")
APPLICATION_INFERENCE_PROFILE_ARN = os.environ.get("APPLICATION_INFERENCE_PROFILE_ARN")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-southeast-1")
APP_DEBUG = os.environ.get("APP_DEBUG", "WARNING")

# Configure logging
logger = logging.getLogger(__name__)
log_level = getattr(logging, APP_DEBUG.upper(), logging.WARNING)
logger.setLevel(log_level)

# Configure strands logger
strands_logger = logging.getLogger("strands")
strands_logger.setLevel(log_level)

logging.basicConfig(
    format="%(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()]
)


# ============================================================================
# ENVIRONMENT VARIABLE VALIDATION (Task 11 - Requirement 6.5)
# ============================================================================

def validate_environment_variables() -> Optional[Dict[str, Any]]:
    """
    Validate that all required environment variables are set on Lambda initialization.
    
    This function checks for the presence of all required environment variables
    and returns a structured error response if any are missing.
    
    Returns:
        Error response dict if validation fails, None if all variables are valid
    """
    missing_vars = []
    
    # Check required R2 configuration variables
    if not R2_ACCESS_KEY_ID:
        missing_vars.append("R2_ACCESS_KEY_ID")
    if not R2_SECRET_ACCESS_KEY:
        missing_vars.append("R2_SECRET_ACCESS_KEY")
    if not R2_ENDPOINT_URL:
        missing_vars.append("R2_ENDPOINT_URL")
    if not R2_BUCKET_NAME:
        missing_vars.append("R2_BUCKET_NAME")
    
    # Check required Bedrock configuration variable
    if not APPLICATION_INFERENCE_PROFILE_ARN:
        missing_vars.append("APPLICATION_INFERENCE_PROFILE_ARN")
    
    if missing_vars:
        error_message = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.error(error_message)
        return {
            "errors": [{
                "message": "Lambda configuration error",
                "details": error_message,
                "error_code": "CONFIGURATION_ERROR"
            }]
        }
    
    # Validate APP_DEBUG value if provided
    valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if APP_DEBUG.upper() not in valid_log_levels:
        logger.warning(
            f"Invalid APP_DEBUG value '{APP_DEBUG}'. "
            f"Valid values are: {', '.join(valid_log_levels)}. "
            f"Defaulting to WARNING."
        )
    
    # Validate R2_ENDPOINT_URL format
    if R2_ENDPOINT_URL and not R2_ENDPOINT_URL.startswith(("http://", "https://")):
        error_message = "R2_ENDPOINT_URL must start with http:// or https://"
        logger.error(error_message)
        return {
            "errors": [{
                "message": "Invalid R2 endpoint URL configuration",
                "details": error_message,
                "error_code": "CONFIGURATION_ERROR"
            }]
        }
    
    # Validate APPLICATION_INFERENCE_PROFILE_ARN format
    if APPLICATION_INFERENCE_PROFILE_ARN and not APPLICATION_INFERENCE_PROFILE_ARN.startswith("arn:aws:bedrock:"):
        error_message = "APPLICATION_INFERENCE_PROFILE_ARN must be a valid Bedrock ARN"
        logger.error(error_message)
        return {
            "errors": [{
                "message": "Invalid Bedrock ARN configuration",
                "details": error_message,
                "error_code": "CONFIGURATION_ERROR"
            }]
        }
    
    logger.info("Environment variable validation successful")
    return None


# Validate environment variables on module initialization
# This ensures the Lambda function fails fast if misconfigured
_env_validation_error = validate_environment_variables()
if _env_validation_error:
    logger.critical("Lambda function is misconfigured and cannot start")
    # Store the error to return it on any handler invocation
    _INITIALIZATION_ERROR = _env_validation_error
else:
    _INITIALIZATION_ERROR = None

# System prompt for Bedrock agent (Task 6)
LAUNDRY_MONITORING_SYSTEM_PROMPT = """You are a household assistant specializing in laundry monitoring for car porch areas. Your role is to analyze security camera images to detect laundry racks placed outside in open air areas and provide weather-aware recommendations to help homeowners protect their laundry from adverse weather conditions.

## Image Analysis Requirements

### 1. Laundry Rack Detection (Requirement 1.1)
- Carefully examine the image for laundry racks or drying structures in open air areas
- Look for physical structures typical of laundry racks: poles, horizontal bars, hanging mechanisms, clotheslines
- Detect clothes, bedsheets, towels, or other fabric items hanging outdoors
- Focus specifically on open air areas such as car porches, patios, balconies, or outdoor spaces
- Distinguish between indoor and outdoor areas - only report laundry in open air locations

### 2. Location Identification (Requirement 1.2)
When laundry is detected, describe its location within the image using:
- **Horizontal position**: "left side of porch", "center area", "right side"
- **Depth/distance**: "near gate", "back of porch", "foreground", "background"
- **Landmarks**: "near car", "by the wall", "under roof overhang", "next to pillar", "beside entrance"
- Be specific and descriptive to help the homeowner quickly locate the laundry

### 3. Item Description (Requirement 1.3)
Describe the laundry items you observe:
- **Item types**: clothes (shirts, pants, dresses), bedsheets, towels, blankets, undergarments
- **Quantity**: "several items", "full rack", "a few pieces", "many items", approximate count if visible
- **Colors**: mention distinctive colors when clearly visible (e.g., "white bedsheets", "colorful clothes")
- **Arrangement**: "hanging on rack", "spread on line", "draped over bars"

### 4. No Detection Handling (Requirement 1.4)
- If no laundry racks or items are detected in open air areas, clearly state: "No laundry detected"
- Distinguish between "no laundry present" and "unable to determine due to image quality"
- Do not report laundry that is clearly indoors or under complete shelter

### 5. Image Quality Assessment (Requirement 1.5)
Evaluate image quality and adjust confidence accordingly:
- **Poor lighting**: too dark, overexposed, shadows obscuring view
- **Obstructions**: objects blocking the view, partial visibility
- **Low resolution**: blurry, pixelated, insufficient detail
- **Adverse weather in image**: fog, heavy rain, glare affecting visibility
- Report confidence score < 0.5 for poor quality images
- Report confidence score 0.5-0.7 for moderate quality with some limitations
- Report confidence score > 0.7 for clear, well-lit images with good visibility

## Weather Risk Assessment

### Weather Data Analysis (Requirements 2.3, 2.4, 2.5)
You will receive weather forecast data for the current hour and next hour. Analyze:

1. **Rain and Precipitation (Requirement 2.5)**
   - Check for rain, storms, or precipitation in current or upcoming conditions
   - Evaluate precipitation_probability in next_hour forecast
   - Flag as HIGH RISK if rain is forecasted or precipitation_probability ≥ 30%
   - This is the PRIMARY risk factor for laundry

2. **Temperature Changes (Requirement 2.3)**
   - Compare current_hour and next_hour temperatures
   - Significant drops (>5°C) may affect drying efficiency during daytime
   - Very high temperatures (>35°C) with low humidity are ideal for drying
   - Consider temperature in context of time of day

3. **Wind Conditions (Requirement 2.4)**
   - Moderate wind (10-20 km/h): helps drying, generally safe
   - High wind (20-40 km/h): risk of laundry displacement, flag as MEDIUM RISK
   - Strong wind (>40 km/h): high risk of laundry falling or damage, flag as HIGH RISK

4. **Weather Conditions (Requirement 2.4)**
   - Clear/Sunny: ideal for drying, LOW RISK
   - Cloudy: slower drying but safe if no rain, LOW to MEDIUM RISK
   - Rainy/Stormy: immediate risk, HIGH RISK
   - Foggy: may affect drying, MEDIUM RISK

### Risk Level Classification
Assign one of three risk levels:
- **low**: Clear conditions, no rain forecast, moderate wind (<20 km/h), stable temperature
- **medium**: Cloudy, low precipitation probability (<30%), high wind (20-40 km/h), or significant temperature drops
- **high**: Rain forecast, precipitation probability ≥30%, storms, or strong winds (>40 km/h)

## Recommendation Logic

### Decision Rules (Requirements 3.1-3.5)

1. **High Risk + Laundry Detected (Requirement 3.1)**
   - Recommendation: "bring_inside"
   - Urgency: HIGH
   - Reason: Explain the specific weather threat (rain, storm, strong wind)

2. **Medium Risk + Laundry Detected**
   - Recommendation: "bring_inside" (cautious approach)
   - Urgency: MEDIUM
   - Reason: Explain the potential risk factors (approaching clouds, increasing wind, temperature drop)

3. **Low Risk + Laundry Detected (Requirement 3.2)**
   - Recommendation: "leave_outside"
   - Urgency: LOW
   - Reason: Confirm favorable conditions for continued drying

4. **No Laundry Detected (Requirement 3.5)**
   - Recommendation: "no_action"
   - Urgency: NONE
   - Reason: State that no laundry was found in open air areas

### Confidence Scoring (Requirement 3.6)
Provide a confidence score (0.0-1.0) based on:
- Image quality and visibility (primary factor)
- Clarity of laundry detection
- Certainty of weather risk assessment
- Any ambiguities or limitations

**Confidence Guidelines:**
- 0.9-1.0: Excellent image quality, clear laundry detection, definitive weather assessment
- 0.7-0.9: Good visibility, confident detection, clear weather risks
- 0.5-0.7: Moderate quality, some limitations but reasonable assessment
- 0.3-0.5: Poor image quality, uncertain detection, or ambiguous conditions
- 0.0-0.3: Very poor quality, highly uncertain, or unable to make reliable assessment

## Output Requirements

### Bilingual Response (Requirements 5.1, 5.2, 5.3, 5.4, 5.5)

You MUST provide complete analysis in BOTH languages:

1. **English (en)** - Requirement 5.1
   - All fields in clear, natural English
   - Use standard terminology
   - Professional but friendly tone

2. **Simplified Chinese (zh_CN)** - Requirement 5.2
   - All fields translated to Simplified Chinese (简体中文)
   - Maintain consistent meaning across languages (Requirement 5.4)
   - Use natural, conversational Chinese appropriate for household context
   - For technical weather terms, use standard Chinese meteorological terminology
   - If a term cannot be translated naturally, use the English term with Chinese explanation (Requirement 5.5)

### Response Structure (Requirement 4)

Return a JSON object with this exact structure:

```json
{
  "en": {
    "laundry_detected": boolean,
    "laundry_description": "string - detailed description of laundry location and items, or 'No laundry detected'",
    "weather_risk_level": "low|medium|high",
    "weather_summary": "string - brief summary of current and upcoming weather conditions (max 50 words)",
    "recommendation": "bring_inside|leave_outside|no_action",
    "recommendation_reason": "string - explanation for the recommendation referencing specific weather factors (max 100 words)",
    "confidence": float (0.0-1.0),
    "timestamp": "ISO 8601 timestamp of analysis",
    "image_url": "presigned URL of analyzed image"
  },
  "zh_CN": {
    "laundry_detected": boolean,
    "laundry_description": "string - 衣物位置和类型的详细描述，或'未检测到晾晒衣物'",
    "weather_risk_level": "low|medium|high",
    "weather_summary": "string - 当前和未来天气状况的简要总结（最多50字）",
    "recommendation": "bring_inside|leave_outside|no_action",
    "recommendation_reason": "string - 建议的解释，引用具体天气因素（最多100字）",
    "confidence": float (0.0-1.0),
    "timestamp": "ISO 8601 时间戳",
    "image_url": "已分析图像的预签名URL"
  }
}
```

### Field Requirements (Requirements 4.2-4.8)

- **laundry_detected** (Requirement 4.2): Boolean indicating presence of laundry in open air
- **laundry_description** (Requirement 4.3): Detailed description including location and items, or "No laundry detected"
- **weather_risk_level** (Requirement 4.4): One of "low", "medium", "high"
- **weather_summary**: Concise weather overview (max 50 words)
- **recommendation** (Requirement 4.5): One of "bring_inside", "leave_outside", "no_action"
- **recommendation_reason**: Clear explanation with specific weather factors (max 100 words)
- **confidence** (Requirement 4.6): Float between 0.0 and 1.0
- **timestamp** (Requirement 4.7): Current time in ISO 8601 format (will be added by system)
- **image_url** (Requirement 4.8): Presigned URL (will be added by system)

## Analysis Approach

1. **Examine the image carefully** for laundry racks and items in open air areas
2. **Describe what you see** with specific location and item details
3. **Analyze the weather data** provided for current and next hour
4. **Assess the risk level** based on precipitation, wind, temperature, and conditions
5. **Make a recommendation** following the decision rules above
6. **Assign confidence** based on image quality and certainty
7. **Provide complete bilingual output** in both English and Simplified Chinese
8. **Be specific and actionable** - homeowners need clear guidance

Remember: Your primary goal is to help homeowners protect their laundry from getting wet or damaged. When in doubt about weather risks, err on the side of caution and recommend bringing laundry inside."""


def validate_weather_condition(condition: Dict[str, Any], condition_name: str) -> Optional[Dict[str, str]]:
    """
    Validate a weather condition object (current_hour or next_hour).
    
    Args:
        condition: Weather condition dictionary to validate
        condition_name: Name of the condition for error messages (e.g., "current_hour")
    
    Returns:
        Error dict if validation fails, None if valid
    """
    if not isinstance(condition, dict):
        return {
            "message": f"Invalid weather data: {condition_name} must be an object",
            "details": f"{condition_name} is not a dictionary",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    required_fields = ["temperature", "condition", "humidity", "wind_speed"]
    missing_fields = [field for field in required_fields if field not in condition]
    
    if missing_fields:
        return {
            "message": f"Invalid weather data: {condition_name} missing required fields",
            "details": f"Missing fields in {condition_name}: {', '.join(missing_fields)}",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    # Validate field types
    if not isinstance(condition.get("temperature"), (int, float)):
        return {
            "message": f"Invalid weather data: {condition_name}.temperature must be a number",
            "details": f"{condition_name}.temperature is not a numeric value",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    if not isinstance(condition.get("condition"), str):
        return {
            "message": f"Invalid weather data: {condition_name}.condition must be a string",
            "details": f"{condition_name}.condition is not a string",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    if not isinstance(condition.get("humidity"), (int, float)):
        return {
            "message": f"Invalid weather data: {condition_name}.humidity must be a number",
            "details": f"{condition_name}.humidity is not a numeric value",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    if not isinstance(condition.get("wind_speed"), (int, float)):
        return {
            "message": f"Invalid weather data: {condition_name}.wind_speed must be a number",
            "details": f"{condition_name}.wind_speed is not a numeric value",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    return None


def validate_file_key(file_key: str) -> Optional[Dict[str, str]]:
    """
    Validate file_key format to prevent path traversal attacks.
    
    Args:
        file_key: The file key to validate
    
    Returns:
        Error dict if validation fails, None if valid
    """
    if not isinstance(file_key, str) or not file_key.strip():
        return {
            "message": "Invalid file_key",
            "details": "file_key must be a non-empty string",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    # Prevent path traversal attacks
    if ".." in file_key:
        return {
            "message": "Invalid file_key format",
            "details": "file_key contains path traversal sequence (..)",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    # Prevent absolute paths
    if file_key.startswith("/"):
        return {
            "message": "Invalid file_key format",
            "details": "file_key cannot start with /",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    # Prevent backslash (Windows-style paths)
    if "\\" in file_key:
        return {
            "message": "Invalid file_key format",
            "details": "file_key contains invalid characters (\\)",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    # Validate against common path traversal patterns
    dangerous_patterns = [
        r'\.\.',  # Double dots
        r'\./',   # Current directory reference
        r'/\.',   # Hidden files at root
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, file_key):
            return {
                "message": "Invalid file_key format",
                "details": f"file_key contains potentially dangerous pattern: {pattern}",
                "error_code": "INPUT_VALIDATION_ERROR"
            }
    
    return None


def validate_input(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate the Lambda event input.
    
    Args:
        event: Lambda event dictionary
    
    Returns:
        Error response dict if validation fails, None if valid
    """
    # Validate file_key
    if "file_key" not in event:
        return {
            "errors": [{
                "message": "Missing required field: file_key",
                "details": "The event must contain a 'file_key' field",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    file_key = event.get("file_key")
    file_key_error = validate_file_key(file_key)
    if file_key_error:
        return {"errors": [file_key_error]}
    
    # Validate weather_data
    if "weather_data" not in event:
        return {
            "errors": [{
                "message": "Missing required field: weather_data",
                "details": "The event must contain a 'weather_data' field",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    weather_data = event.get("weather_data")
    if not isinstance(weather_data, dict):
        return {
            "errors": [{
                "message": "Invalid weather_data",
                "details": "weather_data must be an object",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    # Validate current_hour
    if "current_hour" not in weather_data:
        return {
            "errors": [{
                "message": "Missing required field: weather_data.current_hour",
                "details": "weather_data must contain a 'current_hour' field",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    error = validate_weather_condition(weather_data["current_hour"], "current_hour")
    if error:
        return {"errors": [error]}
    
    # Validate next_hour
    if "next_hour" not in weather_data:
        return {
            "errors": [{
                "message": "Missing required field: weather_data.next_hour",
                "details": "weather_data must contain a 'next_hour' field",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    error = validate_weather_condition(weather_data["next_hour"], "next_hour")
    if error:
        return {"errors": [error]}
    
    # Validate precipitation_probability in next_hour (optional but should be numeric if present)
    next_hour = weather_data["next_hour"]
    if "precipitation_probability" in next_hour:
        if not isinstance(next_hour["precipitation_probability"], (int, float)):
            return {
                "errors": [{
                    "message": "Invalid weather data: next_hour.precipitation_probability must be a number",
                    "details": "next_hour.precipitation_probability is not a numeric value",
                    "error_code": "INPUT_VALIDATION_ERROR"
                }]
            }
    
    return None


def create_r2_client():
    """
    Create and configure boto3 S3 client for R2 storage.
    
    Environment variables are validated at Lambda initialization (Task 11),
    so this function assumes they are already set correctly.
    
    Returns:
        Configured boto3 S3 client
    """
    # Create S3 client configured for R2
    # Environment variables are validated at module initialization
    s3_client = boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",  # R2 uses "auto" region
    )
    
    return s3_client


def retrieve_image_from_r2(file_key: str) -> Dict[str, Any]:
    """
    Retrieve image from R2 storage.
    
    Args:
        file_key: The S3 object key for the image
    
    Returns:
        Dict containing image_bytes and any metadata, or error dict
    """
    try:
        # Create R2 client
        s3_client = create_r2_client()
        
        logger.info(f"Retrieving image from R2: bucket={R2_BUCKET_NAME}, key={file_key}")
        
        # Retrieve object from R2
        response = s3_client.get_object(Bucket=R2_BUCKET_NAME, Key=file_key)
        image_bytes = response['Body'].read()
        
        if not image_bytes:
            return {
                "error": {
                    "message": "Retrieved image is empty",
                    "details": f"Image at {file_key} has zero bytes",
                    "error_code": "STORAGE_ERROR"
                }
            }
        
        logger.info(f"Successfully retrieved image: {len(image_bytes)} bytes")
        
        return {
            "image_bytes": image_bytes,
            "content_type": response.get('ContentType', 'image/jpeg'),
            "last_modified": response.get('LastModified'),
        }
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        
        if error_code == 'NoSuchKey':
            logger.error(f"Image not found in R2: {file_key}")
            return {
                "error": {
                    "message": "Image not found",
                    "details": f"No image exists at key: {file_key}",
                    "error_code": "STORAGE_ERROR"
                }
            }
        elif error_code == 'NoSuchBucket':
            logger.error(f"Bucket not found: {R2_BUCKET_NAME}")
            return {
                "error": {
                    "message": "Storage bucket not found",
                    "details": "The configured storage bucket does not exist",
                    "error_code": "STORAGE_ERROR"
                }
            }
        elif error_code in ['InvalidAccessKeyId', 'SignatureDoesNotMatch']:
            logger.error(f"Invalid R2 credentials: {error_code}")
            return {
                "error": {
                    "message": "Invalid storage credentials",
                    "details": "R2 access credentials are invalid or expired",
                    "error_code": "STORAGE_ERROR"
                }
            }
        else:
            logger.error(f"R2 client error: {error_code} - {str(e)}")
            return {
                "error": {
                    "message": "Storage access error",
                    "details": f"Failed to retrieve image: {error_code}",
                    "error_code": "STORAGE_ERROR"
                }
            }
    
    except NoCredentialsError:
        logger.error("No R2 credentials found")
        return {
            "error": {
                "message": "Missing storage credentials",
                "details": "R2 credentials are not configured",
                "error_code": "STORAGE_ERROR"
            }
        }
    
    except EndpointConnectionError as e:
        logger.error(f"Connection timeout to R2: {str(e)}")
        return {
            "error": {
                "message": "Storage connection timeout",
                "details": "Failed to connect to storage endpoint",
                "error_code": "STORAGE_ERROR"
            }
        }
    
    except ValueError as e:
        logger.error(f"Configuration error: {str(e)}")
        return {
            "error": {
                "message": "Storage configuration error",
                "details": str(e),
                "error_code": "STORAGE_ERROR"
            }
        }
    
    except Exception as e:
        logger.error(f"Unexpected error retrieving image: {str(e)}", exc_info=True)
        return {
            "error": {
                "message": "Unexpected storage error",
                "details": f"An unexpected error occurred: {type(e).__name__}",
                "error_code": "STORAGE_ERROR"
            }
        }


def format_weather_data_for_prompt(weather_data: Dict[str, Any]) -> str:
    """
    Format weather data into natural language description for the agent prompt.
    
    Args:
        weather_data: Dictionary containing current_hour and next_hour weather data
    
    Returns:
        Natural language description of weather conditions
    """
    current = weather_data["current_hour"]
    next_hour = weather_data["next_hour"]
    
    # Build weather description
    description_parts = []
    
    # Current hour conditions
    description_parts.append(
        f"Current weather: {current['condition']}, "
        f"temperature {current['temperature']}°C, "
        f"humidity {current['humidity']}%, "
        f"wind speed {current['wind_speed']} km/h"
    )
    
    # Next hour conditions
    next_hour_desc = (
        f"Next hour forecast: {next_hour['condition']}, "
        f"temperature {next_hour['temperature']}°C, "
        f"humidity {next_hour['humidity']}%, "
        f"wind speed {next_hour['wind_speed']} km/h"
    )
    
    # Add precipitation probability if available
    if "precipitation_probability" in next_hour:
        next_hour_desc += f", precipitation probability {next_hour['precipitation_probability']}%"
    
    description_parts.append(next_hour_desc)
    
    # Temperature change analysis
    temp_change = next_hour['temperature'] - current['temperature']
    if abs(temp_change) > 0.5:
        if temp_change > 0:
            description_parts.append(f"Temperature rising by {temp_change:.1f}°C")
        else:
            description_parts.append(f"Temperature dropping by {abs(temp_change):.1f}°C")
    
    return ". ".join(description_parts) + "."


def generate_presigned_url(file_key: str, expiration: int = 604800) -> Dict[str, Any]:
    """
    Generate a presigned URL for accessing an image in R2 storage.
    
    Args:
        file_key: The S3 object key for the image
        expiration: URL expiration time in seconds (default: 604800 = 7 days)
    
    Returns:
        Dict containing presigned_url or error dict
    """
    try:
        # Create R2 client
        s3_client = create_r2_client()
        
        logger.info(f"Generating presigned URL for: bucket={R2_BUCKET_NAME}, key={file_key}, expiration={expiration}s")
        
        # Generate presigned URL
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': R2_BUCKET_NAME,
                'Key': file_key
            },
            ExpiresIn=expiration
        )
        
        logger.info(f"Successfully generated presigned URL (expires in {expiration}s)")
        
        return {
            "presigned_url": presigned_url
        }
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"Failed to generate presigned URL: {error_code} - {str(e)}")
        return {
            "error": {
                "message": "Failed to generate image URL",
                "details": f"Could not create presigned URL: {error_code}",
                "error_code": "STORAGE_ERROR"
            }
        }
    
    except ValueError as e:
        logger.error(f"Configuration error: {str(e)}")
        return {
            "error": {
                "message": "Storage configuration error",
                "details": str(e),
                "error_code": "STORAGE_ERROR"
            }
        }
    
    except Exception as e:
        logger.error(f"Unexpected error generating presigned URL: {str(e)}", exc_info=True)
        return {
            "error": {
                "message": "Unexpected error generating image URL",
                "details": f"An unexpected error occurred: {type(e).__name__}",
                "error_code": "STORAGE_ERROR"
            }
        }


def invoke_bedrock_agent(
    image_bytes: bytes,
    image_format: str,
    presigned_url: str,
    weather_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Invoke Bedrock agent to analyze laundry image with weather context.
    
    Args:
        image_bytes: Raw image bytes
        image_format: Image format (e.g., 'jpeg', 'png')
        presigned_url: Presigned URL for the image
        weather_data: Weather forecast data for current and next hour
    
    Returns:
        Dict containing analysis result or error information
    """
    try:
        logger.info(f"Initializing Bedrock agent with model: {APPLICATION_INFERENCE_PROFILE_ARN}")
        
        # Create boto3 session for Bedrock
        boto3_session = boto3.Session(region_name=BEDROCK_REGION)
        
        # Initialize Bedrock model with timeout and retry configuration
        bedrock_model = BedrockModel(
            model_id=APPLICATION_INFERENCE_PROFILE_ARN,
            boto_session=boto3_session,
            cache_prompt="default",
            boto_client_config=BotocoreConfig(
                connect_timeout=10,  # Connection timeout
                read_timeout=60,     # Read timeout for inference
                retries={
                    'max_attempts': 3,
                    'mode': 'adaptive'
                }
            ),
        )
        
        # Create agent with system prompt
        agent = Agent(
            model=bedrock_model,
            system_prompt=LAUNDRY_MONITORING_SYSTEM_PROMPT,
        )
        
        # Format weather data into natural language
        weather_description = format_weather_data_for_prompt(weather_data)
        logger.info(f"Weather context: {weather_description}")
        
        # Generate current timestamp in ISO 8601 format
        current_timestamp = datetime.now(timezone.utc).isoformat()
        
        # Prepare agent input with image and weather context
        agent_input: AgentInput = [
            {
                "text": "Analyze the following security camera image for laundry racks in open air areas.",
                "image": {
                    "format": image_format,
                    "source": {
                        "bytes": image_bytes
                    }
                }
            },
            {
                "text": f"Weather forecast data: {weather_description}"
            },
            {
                "text": f"Current timestamp: {current_timestamp}"
            },
            {
                "text": f"Image source URL: {presigned_url}"
            }
        ]
        
        logger.info("Invoking Bedrock model for laundry analysis...")
        
        # Invoke Bedrock with structured output
        result = agent.structured_output(
            output_model=LocalizedLaundryAnalysisResponse,
            prompt=agent_input
        )
        
        logger.info("Successfully received structured output from Bedrock")
        
        return {
            "result": result
        }
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        
        logger.error(f"Bedrock client error: {error_code} - {error_message}")
        
        # Handle specific error types
        if error_code == 'ThrottlingException':
            return {
                "error": {
                    "message": "Bedrock service rate limit exceeded",
                    "details": "Too many requests. Please try again later.",
                    "error_code": "BEDROCK_RATE_LIMIT"
                }
            }
        elif error_code == 'ModelTimeoutException':
            return {
                "error": {
                    "message": "Bedrock model timeout",
                    "details": "Model inference took too long to complete",
                    "error_code": "BEDROCK_TIMEOUT"
                }
            }
        elif error_code in ['AccessDeniedException', 'UnauthorizedException']:
            return {
                "error": {
                    "message": "Bedrock access denied",
                    "details": "Invalid permissions or credentials for Bedrock model",
                    "error_code": "BEDROCK_ACCESS_DENIED"
                }
            }
        elif error_code == 'ResourceNotFoundException':
            return {
                "error": {
                    "message": "Bedrock model not found",
                    "details": "The configured Bedrock model could not be found",
                    "error_code": "BEDROCK_MODEL_NOT_FOUND"
                }
            }
        else:
            return {
                "error": {
                    "message": "Bedrock invocation failed",
                    "details": f"Error: {error_code} - {error_message}",
                    "error_code": "BEDROCK_ERROR"
                }
            }
    
    except TimeoutError as e:
        logger.error(f"Bedrock timeout: {str(e)}")
        return {
            "error": {
                "message": "Bedrock request timeout",
                "details": "The request to Bedrock timed out after 60 seconds",
                "error_code": "BEDROCK_TIMEOUT"
            }
        }
    
    except ValueError as e:
        logger.error(f"Invalid model configuration: {str(e)}")
        return {
            "error": {
                "message": "Invalid Bedrock configuration",
                "details": str(e),
                "error_code": "BEDROCK_CONFIG_ERROR"
            }
        }
    
    except Exception as e:
        logger.error(f"Unexpected error during Bedrock invocation: {str(e)}", exc_info=True)
        return {
            "error": {
                "message": "Unexpected error during analysis",
                "details": f"An unexpected error occurred: {type(e).__name__}",
                "error_code": "BEDROCK_ERROR"
            }
        }


def validate_and_enrich_response(
    bedrock_response: LocalizedLaundryAnalysisResponse,
    presigned_url: str
) -> Dict[str, Any]:
    """
    Validate Bedrock response and enrich with presigned URL and timestamp.
    
    This function implements Task 8: Response validation and parsing.
    It validates the Bedrock response against Pydantic models, verifies
    timestamp format and confidence score range, and adds the presigned URL.
    
    Args:
        bedrock_response: Pydantic model instance from Bedrock structured output
        presigned_url: Presigned URL to add to the response
    
    Returns:
        Dict containing validated and enriched response or error information
    """
    try:
        logger.info("Validating and enriching Bedrock response...")
        
        # Generate current timestamp in ISO 8601 format
        current_timestamp = datetime.now(timezone.utc).isoformat()
        logger.debug(f"Generated timestamp: {current_timestamp}")
        
        # The bedrock_response is already a Pydantic model instance from structured_output,
        # so basic validation has already occurred. However, we need to:
        # 1. Verify the response structure is complete
        # 2. Add presigned URL to both language versions
        # 3. Update timestamp to current time
        # 4. Perform additional validation checks
        
        # Validate English response
        if not hasattr(bedrock_response, 'en') or bedrock_response.en is None:
            logger.error("Missing English localization in response")
            return {
                "error": {
                    "message": "Invalid Bedrock response",
                    "details": "Missing English (en) localization in response",
                    "error_code": "VALIDATION_ERROR"
                }
            }
        
        # Validate Chinese response
        if not hasattr(bedrock_response, 'zh_CN') or bedrock_response.zh_CN is None:
            logger.error("Missing Chinese localization in response")
            return {
                "error": {
                    "message": "Invalid Bedrock response",
                    "details": "Missing Simplified Chinese (zh_CN) localization in response",
                    "error_code": "VALIDATION_ERROR"
                }
            }
        
        # Validate and enrich English response
        en_response = bedrock_response.en
        
        # Verify required fields are present
        required_fields = [
            'laundry_detected', 'laundry_description', 'weather_risk_level',
            'weather_summary', 'recommendation', 'recommendation_reason', 'confidence'
        ]
        
        for field in required_fields:
            if not hasattr(en_response, field):
                logger.error(f"Missing required field in English response: {field}")
                return {
                    "error": {
                        "message": "Invalid Bedrock response",
                        "details": f"Missing required field in English response: {field}",
                        "error_code": "VALIDATION_ERROR"
                    }
                }
        
        # Verify confidence score is in valid range (0.0-1.0)
        if not isinstance(en_response.confidence, (int, float)):
            logger.error(f"Invalid confidence type: {type(en_response.confidence)}")
            return {
                "error": {
                    "message": "Invalid confidence score",
                    "details": f"Confidence must be a number, got {type(en_response.confidence).__name__}",
                    "error_code": "VALIDATION_ERROR"
                }
            }
        
        if not 0.0 <= en_response.confidence <= 1.0:
            logger.error(f"Confidence score out of range: {en_response.confidence}")
            return {
                "error": {
                    "message": "Invalid confidence score",
                    "details": f"Confidence must be between 0.0 and 1.0, got {en_response.confidence}",
                    "error_code": "VALIDATION_ERROR"
                }
            }
        
        logger.debug(f"English response confidence validated: {en_response.confidence}")
        
        # Verify timestamp format (ISO 8601)
        # The Pydantic validator already checks this, but we'll verify it's present
        if hasattr(en_response, 'timestamp') and en_response.timestamp:
            try:
                # Verify it can be parsed as ISO 8601
                datetime.fromisoformat(en_response.timestamp.replace('Z', '+00:00'))
                logger.debug(f"English response timestamp validated: {en_response.timestamp}")
            except (ValueError, AttributeError) as e:
                logger.error(f"Invalid timestamp format in English response: {en_response.timestamp}")
                return {
                    "error": {
                        "message": "Invalid timestamp format",
                        "details": f"Timestamp must be in ISO 8601 format, got '{en_response.timestamp}': {str(e)}",
                        "error_code": "VALIDATION_ERROR"
                    }
                }
        
        # Update English response with presigned URL and current timestamp
        en_response.image_url = presigned_url
        en_response.timestamp = current_timestamp
        logger.debug("Updated English response with presigned URL and timestamp")
        
        # Validate and enrich Chinese response
        zh_response = bedrock_response.zh_CN
        
        # Verify required fields are present in Chinese response
        for field in required_fields:
            if not hasattr(zh_response, field):
                logger.error(f"Missing required field in Chinese response: {field}")
                return {
                    "error": {
                        "message": "Invalid Bedrock response",
                        "details": f"Missing required field in Chinese response: {field}",
                        "error_code": "VALIDATION_ERROR"
                    }
                }
        
        # Verify confidence score in Chinese response
        if not isinstance(zh_response.confidence, (int, float)):
            logger.error(f"Invalid confidence type in Chinese response: {type(zh_response.confidence)}")
            return {
                "error": {
                    "message": "Invalid confidence score",
                    "details": f"Confidence in Chinese response must be a number, got {type(zh_response.confidence).__name__}",
                    "error_code": "VALIDATION_ERROR"
                }
            }
        
        if not 0.0 <= zh_response.confidence <= 1.0:
            logger.error(f"Confidence score out of range in Chinese response: {zh_response.confidence}")
            return {
                "error": {
                    "message": "Invalid confidence score",
                    "details": f"Confidence in Chinese response must be between 0.0 and 1.0, got {zh_response.confidence}",
                    "error_code": "VALIDATION_ERROR"
                }
            }
        
        logger.debug(f"Chinese response confidence validated: {zh_response.confidence}")
        
        # Verify timestamp format in Chinese response
        if hasattr(zh_response, 'timestamp') and zh_response.timestamp:
            try:
                datetime.fromisoformat(zh_response.timestamp.replace('Z', '+00:00'))
                logger.debug(f"Chinese response timestamp validated: {zh_response.timestamp}")
            except (ValueError, AttributeError) as e:
                logger.error(f"Invalid timestamp format in Chinese response: {zh_response.timestamp}")
                return {
                    "error": {
                        "message": "Invalid timestamp format",
                        "details": f"Timestamp in Chinese response must be in ISO 8601 format, got '{zh_response.timestamp}': {str(e)}",
                        "error_code": "VALIDATION_ERROR"
                    }
                }
        
        # Update Chinese response with presigned URL and current timestamp
        zh_response.image_url = presigned_url
        zh_response.timestamp = current_timestamp
        logger.debug("Updated Chinese response with presigned URL and timestamp")
        
        # Verify both responses have consistent boolean and enum values
        if en_response.laundry_detected != zh_response.laundry_detected:
            logger.warning("Laundry detection mismatch between English and Chinese responses")
        
        if en_response.weather_risk_level != zh_response.weather_risk_level:
            logger.warning("Weather risk level mismatch between English and Chinese responses")
        
        if en_response.recommendation != zh_response.recommendation:
            logger.warning("Recommendation mismatch between English and Chinese responses")
        
        logger.info("Response validation and enrichment completed successfully")
        
        # Return the validated and enriched response
        return {
            "validated_response": bedrock_response
        }
        
    except AttributeError as e:
        logger.error(f"Missing attribute in Bedrock response: {str(e)}", exc_info=True)
        return {
            "error": {
                "message": "Invalid Bedrock response structure",
                "details": f"Response is missing required attributes: {str(e)}",
                "error_code": "VALIDATION_ERROR"
            }
        }
    
    except TypeError as e:
        logger.error(f"Type error in Bedrock response: {str(e)}", exc_info=True)
        return {
            "error": {
                "message": "Invalid data types in Bedrock response",
                "details": f"Response contains invalid data types: {str(e)}",
                "error_code": "VALIDATION_ERROR"
            }
        }
    
    except ValueError as e:
        logger.error(f"Value error in Bedrock response: {str(e)}", exc_info=True)
        return {
            "error": {
                "message": "Invalid values in Bedrock response",
                "details": f"Response contains invalid values: {str(e)}",
                "error_code": "VALIDATION_ERROR"
            }
        }
    
    except Exception as e:
        logger.error(f"Unexpected error during response validation: {str(e)}", exc_info=True)
        return {
            "error": {
                "message": "Unexpected validation error",
                "details": f"An unexpected error occurred during validation: {type(e).__name__}",
                "error_code": "VALIDATION_ERROR"
            }
        }


def handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    AWS Lambda handler for laundry monitoring agent.
    
    Analyzes security camera images to detect laundry racks and provides
    weather-aware recommendations.
    
    This function implements Task 10: Comprehensive error handling.
    All major operations are wrapped in try-except blocks with structured
    error responses, appropriate error codes, and proper logging.
    
    Args:
        event: Lambda event containing file_key and weather_data
        context: Lambda context object
    
    Returns:
        Dict containing analysis results or error information
    """
    try:
        # Task 11: Check for environment variable initialization errors
        # If the Lambda was misconfigured, fail immediately with clear error
        if _INITIALIZATION_ERROR:
            logger.error("Handler invoked but Lambda initialization failed")
            return _INITIALIZATION_ERROR
        
        # Log event (sanitize to avoid exposing sensitive data)
        sanitized_event = {
            "file_key": event.get("file_key", ""),
            "weather_data": "present" if "weather_data" in event else "missing"
        }
        logger.info(f"Received event: {json.dumps(sanitized_event)}")
        
        # Task 10: Input validation with comprehensive error handling
        try:
            validation_error = validate_input(event)
            if validation_error:
                logger.warning(f"Input validation failed")
                return validation_error
        except Exception as e:
            logger.error(f"Unexpected error during input validation: {str(e)}", exc_info=True)
            return {
                "errors": [{
                    "message": "Input validation error",
                    "details": f"Failed to validate input: {type(e).__name__}",
                    "error_code": "INPUT_VALIDATION_ERROR"
                }]
            }
        
        file_key = event["file_key"]
        weather_data = event["weather_data"]
        
        logger.info(f"Processing laundry analysis for file_key: {file_key}")
        logger.debug(f"Weather data structure validated")
        
        # Task 10: R2 retrieval with comprehensive error handling
        try:
            # Task 4: Retrieve image from R2 storage
            image_result = retrieve_image_from_r2(file_key)
            
            # Check for retrieval errors
            if "error" in image_result:
                logger.error(f"Failed to retrieve image from R2")
                return {"errors": [image_result["error"]]}
            
            image_bytes = image_result["image_bytes"]
            logger.info(f"Successfully retrieved image: {len(image_bytes)} bytes")
        except Exception as e:
            logger.error(f"Unexpected error during R2 retrieval: {str(e)}", exc_info=True)
            return {
                "errors": [{
                    "message": "Storage retrieval error",
                    "details": f"Unexpected error retrieving image: {type(e).__name__}",
                    "error_code": "STORAGE_ERROR"
                }]
            }
        
        # Task 10: Presigned URL generation with comprehensive error handling
        try:
            # Task 5: Generate presigned URL with 7-day expiration
            presigned_result = generate_presigned_url(file_key, expiration=604800)  # 7 days = 604800 seconds
            
            # Check for presigned URL generation errors
            if "error" in presigned_result:
                logger.error(f"Failed to generate presigned URL")
                return {"errors": [presigned_result["error"]]}
            
            presigned_url = presigned_result["presigned_url"]
            logger.info(f"Successfully generated presigned URL for image")
        except Exception as e:
            logger.error(f"Unexpected error generating presigned URL: {str(e)}", exc_info=True)
            return {
                "errors": [{
                    "message": "URL generation error",
                    "details": f"Unexpected error generating presigned URL: {type(e).__name__}",
                    "error_code": "STORAGE_ERROR"
                }]
            }
        
        # Task 10: Image processing with comprehensive error handling
        try:
            # Task 7: Invoke Bedrock agent for laundry analysis
            # Load image to get format
            image = Image.open(io.BytesIO(image_bytes))
            image_format = image.format.lower() if image.format else 'jpeg'
            logger.info(f"Image format detected: {image_format}")
        except Exception as e:
            logger.error(f"Failed to load image: {str(e)}")
            return {
                "errors": [{
                    "message": "Invalid image file",
                    "details": f"Could not load image: {type(e).__name__}",
                    "error_code": "IMAGE_PROCESSING_ERROR"
                }]
            }
        
        # Task 10: Bedrock invocation with comprehensive error handling
        try:
            # Invoke Bedrock agent with image and weather data
            bedrock_result = invoke_bedrock_agent(
                image_bytes=image_bytes,
                image_format=image_format,
                presigned_url=presigned_url,
                weather_data=weather_data
            )
            
            # Check for Bedrock invocation errors
            if "error" in bedrock_result:
                logger.error(f"Bedrock invocation failed")
                return {"errors": [bedrock_result["error"]]}
            
            # Extract the structured result
            analysis_result = bedrock_result["result"]
            logger.info("Successfully received analysis result from Bedrock")
        except Exception as e:
            logger.error(f"Unexpected error during Bedrock invocation: {str(e)}", exc_info=True)
            return {
                "errors": [{
                    "message": "AI analysis error",
                    "details": f"Unexpected error during analysis: {type(e).__name__}",
                    "error_code": "BEDROCK_ERROR"
                }]
            }
        
        # Task 10: Response validation with comprehensive error handling
        try:
            # Task 8: Validate and enrich response
            validation_result = validate_and_enrich_response(
                bedrock_response=analysis_result,
                presigned_url=presigned_url
            )
            
            # Check for validation errors
            if "error" in validation_result:
                logger.error(f"Response validation failed")
                return {"errors": [validation_result["error"]]}
            
            validated_response = validation_result["validated_response"]
            logger.info("Successfully validated and enriched response")
        except Exception as e:
            logger.error(f"Unexpected error during response validation: {str(e)}", exc_info=True)
            return {
                "errors": [{
                    "message": "Response validation error",
                    "details": f"Unexpected error validating response: {type(e).__name__}",
                    "error_code": "VALIDATION_ERROR"
                }]
            }
        
        # Task 10: Response formatting with comprehensive error handling
        try:
            # Task 9: Format success response with data.result structure
            # This implements the success response formatting as specified in the design document.
            # 
            # Requirements addressed:
            # - Requirement 5.1: English localization included in response
            # - Requirement 5.2: Simplified Chinese localization included in response
            # - Requirement 6.3: Return HTTP 200 status with structured JSON
            #
            # Response structure:
            # {
            #     "data": {
            #         "result": {
            #             "en": { ... },      # English localization
            #             "zh_CN": { ... }    # Simplified Chinese localization
            #         }
            #     }
            # }
            #
            # Both language versions are always included in every response, ensuring
            # all household members can understand the recommendations regardless of
            # their preferred language.
            
            # Convert Pydantic models to dictionaries for JSON serialization
            success_response = {
                "data": {
                    "result": {
                        "en": validated_response.en.model_dump(),
                        "zh_CN": validated_response.zh_CN.model_dump()
                    }
                }
            }
            
            logger.info("Successfully formatted response with bilingual localizations")
            logger.debug(f"Response structure: data.result with 'en' and 'zh_CN' keys")
            
            # Return HTTP 200 status with structured JSON (Requirement 6.3)
            return success_response
            
        except Exception as e:
            logger.error(f"Failed to format success response: {str(e)}", exc_info=True)
            return {
                "errors": [{
                    "message": "Response formatting error",
                    "details": f"Failed to format success response: {type(e).__name__}",
                    "error_code": "RESPONSE_FORMATTING_ERROR"
                }]
            }
    
    except Exception as e:
        # Task 10: Top-level exception handler for any unexpected errors
        # This catches any errors that weren't caught by the specific handlers above
        logger.critical(f"Unhandled exception in Lambda handler: {str(e)}", exc_info=True)
        return {
            "errors": [{
                "message": "Internal server error",
                "details": f"An unexpected error occurred: {type(e).__name__}",
                "error_code": "INTERNAL_ERROR"
            }]
        }


if __name__ == "__main__":
    # Test with valid input
    test_event = {
        "file_key": "camera_snapshot/20251110/120000_porch.jpg",
        "weather_data": {
            "current_hour": {
                "temperature": 28.5,
                "condition": "clear",
                "humidity": 65.0,
                "wind_speed": 12.5
            },
            "next_hour": {
                "temperature": 29.0,
                "condition": "cloudy",
                "humidity": 70.0,
                "wind_speed": 15.0,
                "precipitation_probability": 20.0
            }
        }
    }
    
    result = handler(test_event, None)
    print("Valid input test:")
    print(json.dumps(result, indent=2))
    
    # Test with missing file_key
    invalid_event_1 = {
        "weather_data": {
            "current_hour": {
                "temperature": 28.5,
                "condition": "clear",
                "humidity": 65.0,
                "wind_speed": 12.5
            },
            "next_hour": {
                "temperature": 29.0,
                "condition": "cloudy",
                "humidity": 70.0,
                "wind_speed": 15.0
            }
        }
    }
    
    result = handler(invalid_event_1, None)
    print("\nMissing file_key test:")
    print(json.dumps(result, indent=2))
    
    # Test with missing weather_data
    invalid_event_2 = {
        "file_key": "camera_snapshot/20251110/120000_porch.jpg"
    }
    
    result = handler(invalid_event_2, None)
    print("\nMissing weather_data test:")
    print(json.dumps(result, indent=2))
    
    # Test with invalid weather structure
    invalid_event_3 = {
        "file_key": "camera_snapshot/20251110/120000_porch.jpg",
        "weather_data": {
            "current_hour": {
                "temperature": 28.5,
                "condition": "clear"
                # Missing humidity and wind_speed
            },
            "next_hour": {
                "temperature": 29.0,
                "condition": "cloudy",
                "humidity": 70.0,
                "wind_speed": 15.0
            }
        }
    }
    
    result = handler(invalid_event_3, None)
    print("\nInvalid weather structure test:")
    print(json.dumps(result, indent=2))
    
    # Test with path traversal attempt
    invalid_event_4 = {
        "file_key": "../../../etc/passwd",
        "weather_data": {
            "current_hour": {
                "temperature": 28.5,
                "condition": "clear",
                "humidity": 65.0,
                "wind_speed": 12.5
            },
            "next_hour": {
                "temperature": 29.0,
                "condition": "cloudy",
                "humidity": 70.0,
                "wind_speed": 15.0
            }
        }
    }
    
    result = handler(invalid_event_4, None)
    print("\nPath traversal attack test:")
    print(json.dumps(result, indent=2))
    
    # Test with absolute path
    invalid_event_5 = {
        "file_key": "/etc/passwd",
        "weather_data": {
            "current_hour": {
                "temperature": 28.5,
                "condition": "clear",
                "humidity": 65.0,
                "wind_speed": 12.5
            },
            "next_hour": {
                "temperature": 29.0,
                "condition": "cloudy",
                "humidity": 70.0,
                "wind_speed": 15.0
            }
        }
    }
    
    result = handler(invalid_event_5, None)
    print("\nAbsolute path test:")
    print(json.dumps(result, indent=2))
