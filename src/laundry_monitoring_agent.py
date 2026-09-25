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
from strands.models.openai import OpenAIModel
from strands.types.agent import AgentInput

# Import Pydantic models
from models.laundry_analysis_response import LocalizedLaundryAnalysisResponse

# ============================================================================
# ENVIRONMENT VARIABLES CONFIGURATION (Task 11 - Requirement 6.5)
# ============================================================================
# 
# Required environment variables for Lambda function operation:
#
# 1. MODEL_PROVIDER (Optional)
#    - AI model provider to use: "bedrock" or "openrouter"
#    - Default: "bedrock" if not specified
#    - Determines which AI service to use for image analysis
#
# 2. APPLICATION_INFERENCE_PROFILE_ARN (Required if MODEL_PROVIDER=bedrock)
#    - AWS Bedrock application inference profile ARN
#    - Used for AI model invocation to analyze laundry images
#    - Format: arn:aws:bedrock:region:account:application-inference-profile/id
#    - Example: arn:aws:bedrock:ap-southeast-1:123456789012:application-inference-profile/abc123
#
# 3. OPENROUTER_AI_URL (Required if MODEL_PROVIDER=openrouter)
#    - OpenRouter API base URL
#    - Example: https://openrouter.ai/api/v1
#
# 4. OPENROUTER_AI_MODEL_ID (Required if MODEL_PROVIDER=openrouter)
#    - OpenRouter model identifier
#    - Example: anthropic/claude-3.5-sonnet
#
# 5. OPENROUTER_AI_API_KEY (Required if MODEL_PROVIDER=openrouter)
#    - OpenRouter API key for authentication
#    - Keep this value secure and never log or expose it
#
# 6. R2_ACCESS_KEY_ID (Required)
#    - Cloudflare R2 storage access key ID
#    - Used for authenticating with R2 storage to retrieve images
#    - Obtain from Cloudflare R2 dashboard
#
# 7. R2_SECRET_ACCESS_KEY (Required)
#    - Cloudflare R2 storage secret access key
#    - Used for authenticating with R2 storage to retrieve images
#    - Keep this value secure and never log or expose it
#
# 8. R2_ENDPOINT_URL (Required)
#    - Cloudflare R2 storage endpoint URL
#    - Format: https://<account-id>.r2.cloudflarestorage.com
#    - Example: https://abc123.r2.cloudflarestorage.com
#
# 9. R2_BUCKET_NAME (Required)
#    - Name of the R2 bucket containing security camera images
#    - Example: security-camera-snapshots
#
# 10. APP_DEBUG (Optional)
#     - Logging level for the application
#     - Valid values: DEBUG, INFO, WARNING, ERROR, CRITICAL
#     - Default: WARNING
#     - Use DEBUG for development, WARNING or ERROR for production
#
# 11. BEDROCK_REGION (Optional)
#     - AWS region for Bedrock service
#     - Default: ap-southeast-1
#     - Should match the region in APPLICATION_INFERENCE_PROFILE_ARN
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

MODEL_PROVIDER = os.environ.get("MODEL_PROVIDER")
OPENROUTER_AI_URL = os.environ.get("OPENROUTER_AI_URL")
OPENROUTER_AI_MODEL_ID = os.environ.get("OPENROUTER_AI_MODEL_ID")
OPENROUTER_AI_API_KEY = os.environ.get("OPENROUTER_AI_API_KEY")

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
    
    # Check model provider configuration
    if MODEL_PROVIDER == "bedrock":
        if not APPLICATION_INFERENCE_PROFILE_ARN:
            missing_vars.append("APPLICATION_INFERENCE_PROFILE_ARN")
    elif MODEL_PROVIDER == "openrouter":
        if not OPENROUTER_AI_URL:
            missing_vars.append("OPENROUTER_AI_URL")
        if not OPENROUTER_AI_MODEL_ID:
            missing_vars.append("OPENROUTER_AI_MODEL_ID")
        if not OPENROUTER_AI_API_KEY:
            missing_vars.append("OPENROUTER_AI_API_KEY")
    else:
        # Default to bedrock if not specified
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
    
    # Validate Bedrock configuration if using bedrock provider
    if MODEL_PROVIDER == "bedrock" or not MODEL_PROVIDER:
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
    
    # Validate OpenRouter configuration if using openrouter provider
    if MODEL_PROVIDER == "openrouter":
        if OPENROUTER_AI_URL and not OPENROUTER_AI_URL.startswith(("http://", "https://")):
            error_message = "OPENROUTER_AI_URL must start with http:// or https://"
            logger.error(error_message)
            return {
                "errors": [{
                    "message": "Invalid OpenRouter URL configuration",
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
LAUNDRY_MONITORING_SYSTEM_PROMPT = """You are a household laundry monitoring assistant. You analyze security camera images to detect laundry drying in open air areas (car porch, patio, balcony) and recommend actions based on the weather forecast data provided.

## Image Analysis
- Look for laundry racks, clotheslines, poles, or clothes/bedsheets/towels hanging outdoors.
- Report only laundry in OPEN AIR areas. Do not report laundry clearly indoors or fully sheltered.
- Note the laundry's location in the image (e.g., "left side of porch", "near gate") and use it in notification_message.
- Judge image quality (lighting, obstructions, resolution, glare) and reflect it in confidence:
  - 0.7-1.0: clear, well-lit image, confident detection
  - 0.5-0.7: moderate quality with limitations
  - 0.0-0.5: poor quality or uncertain detection
- If no laundry is visible in open air areas, set laundry_detected=false and recommendation="no_action".

## Weather Risk Assessment
You receive current and next hour forecasts (temperature, condition, humidity, wind speed, precipitation probability). Classify:
- high: rain or storms forecast, precipitation probability >= 30%, or wind > 40 km/h
- medium: cloudy, precipitation probability < 30%, wind 20-40 km/h, or temperature dropping more than 5 degrees
- low: clear conditions, no rain, wind < 20 km/h, stable temperature

## Recommendations
- Laundry detected + high risk -> "bring_inside" (urgent)
- Laundry detected + medium risk -> "bring_inside" (cautious)
- Laundry detected + low risk -> "leave_outside"
- No laundry detected -> "no_action"

When weather risk is uncertain, err on the side of caution and recommend bringing laundry inside.

## Output
Return a JSON object with "en" and "zh_CN" keys holding the same structure: "en" fully in natural English, "zh_CN" fully in natural Simplified Chinese. laundry_detected, weather_risk_level, recommendation, and confidence must be identical in both languages.

Each language object contains:
{
  "laundry_detected": true/false,
  "weather_risk_level": "low" | "medium" | "high",
  "weather_summary": "current and next hour conditions, max 50 words",
  "recommendation": "bring_inside" | "leave_outside" | "no_action",
  "recommendation_reason": "explanation citing specific weather factors, max 100 words",
  "notification_title": "actionable title, max 60 characters, with an emoji: warning sign for bring_inside, check mark for leave_outside, info for no_action",
  "notification_message": "weather threat with probability, laundry location, and urgency, max 200 characters",
  "confidence": 0.0-1.0
}"""


def validate_forecast_item(forecast_item: Dict[str, Any], item_name: str) -> Optional[Dict[str, str]]:
    """
    Validate a single forecast item from the weather forecast array.
    
    This function validates that a forecast item from the Home Assistant weather_forecast
    contains all required fields (condition, datetime, temperature, humidity, wind_speed)
    and that each field has the correct data type and format.
    
    Args:
        forecast_item: Forecast item dictionary to validate from weather_forecast
        item_name: Name of the item for error messages (e.g., "forecast[0]")
    
    Returns:
        Error dict with message, details, and error_code if validation fails, None if valid
    
    Example:
        >>> forecast_item = {
        ...     "condition": "cloudy",
        ...     "datetime": "2025-10-12T02:00:00+00:00",
        ...     "temperature": 27.4,
        ...     "humidity": 79,
        ...     "wind_speed": 11.2
        ... }
        >>> validate_forecast_item(forecast_item, "forecast[0]")
        None  # Returns None if validation passes
    """
    if not isinstance(forecast_item, dict):
        return {
            "message": f"Invalid forecast item: {item_name} must be an object",
            "details": f"{item_name} is not a dictionary",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    # Validate required fields
    required_fields = ["condition", "datetime", "temperature", "humidity", "wind_speed"]
    missing_fields = [field for field in required_fields if field not in forecast_item]
    
    if missing_fields:
        return {
            "message": f"Invalid forecast item: {item_name} missing required fields",
            "details": f"Missing fields in {item_name}: {', '.join(missing_fields)}",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    # Validate field types
    if not isinstance(forecast_item.get("condition"), str):
        return {
            "message": f"Invalid forecast item: {item_name}.condition must be a string",
            "details": f"{item_name}.condition is not a string",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    if not isinstance(forecast_item.get("temperature"), (int, float)):
        return {
            "message": f"Invalid forecast item: {item_name}.temperature must be a number",
            "details": f"{item_name}.temperature is not a numeric value",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    if not isinstance(forecast_item.get("humidity"), (int, float)):
        return {
            "message": f"Invalid forecast item: {item_name}.humidity must be a number",
            "details": f"{item_name}.humidity is not a numeric value",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    if not isinstance(forecast_item.get("wind_speed"), (int, float)):
        return {
            "message": f"Invalid forecast item: {item_name}.wind_speed must be a number",
            "details": f"{item_name}.wind_speed is not a numeric value",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    # Validate datetime format
    try:
        datetime.fromisoformat(forecast_item["datetime"].replace('Z', '+00:00'))
    except (ValueError, AttributeError, TypeError):
        return {
            "message": f"Invalid forecast item: {item_name}.datetime must be a valid ISO 8601 timestamp",
            "details": f"{item_name}.datetime is not in valid ISO 8601 format",
            "error_code": "INPUT_VALIDATION_ERROR"
        }
    
    return None


def extract_weather_data(weather_forecast: Dict[str, Any], current_time: str) -> Dict[str, Any]:
    """
    Extract and transform weather forecast data from Home Assistant format
    to internal processing format, using current_time to identify relevant forecast entries.
    
    This function transforms the Home Assistant weather forecast structure (with entity IDs
    and forecast arrays) into the internal format expected by downstream processing functions.
    It intelligently matches forecast entries to the current and next hour based on the
    provided current_time parameter.
    
    The function:
    - Sorts forecast entries chronologically by datetime
    - Finds the forecast entry closest to current_time for current_hour
    - Selects the next chronological entry for next_hour
    - Converts precipitation from 0-1 range to percentage (multiply by 100)
    - Handles edge cases: missing next_hour, empty forecast array, invalid datetimes
    
    Example:
        >>> weather_forecast = {
        ...     "weather.forecast_home": {
        ...         "forecast": [
        ...             {
        ...                 "condition": "cloudy",
        ...                 "datetime": "2025-10-12T02:00:00+00:00",
        ...                 "temperature": 27.4,
        ...                 "wind_speed": 11.2,
        ...                 "precipitation": 0,
        ...                 "humidity": 79
        ...             },
        ...             {
        ...                 "condition": "rainy",
        ...                 "datetime": "2025-10-12T03:00:00+00:00",
        ...                 "temperature": 28.7,
        ...                 "wind_speed": 9.7,
        ...                 "precipitation": 0.65,
        ...                 "humidity": 75
        ...             }
        ...         ]
        ...     }
        ... }
        >>> current_time = "2025-10-12T02:00:00+00:00"
        >>> result = extract_weather_data(weather_forecast, current_time)
        >>> result["current_hour"]["condition"]
        'cloudy'
        >>> result["next_hour"]["precipitation_probability"]
        65.0  # Converted from 0.65 to percentage
    
    Args:
        weather_forecast: Weather forecast dict with entity structure (e.g., {"weather.forecast_home": {...}})
        current_time: ISO 8601 timestamp representing current time
    
    Returns:
        Dict with current_hour and next_hour weather data in internal format:
        {
            "current_hour": {
                "temperature": float,
                "condition": str,
                "humidity": float,
                "wind_speed": float
            },
            "next_hour": {
                "temperature": float,
                "condition": str,
                "humidity": float,
                "wind_speed": float,
                "precipitation_probability": float  # Percentage (0-100)
            }
        }
    
    Raises:
        ValueError: If forecast array is empty or current_time is invalid
    """
    from datetime import timedelta
    
    # Parse current time
    try:
        current_dt = datetime.fromisoformat(current_time.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid current_time format: {current_time}")
    
    # Get first weather entity
    if not weather_forecast:
        raise ValueError("weather_forecast is empty")
    
    entity_key = list(weather_forecast.keys())[0]
    entity_data = weather_forecast[entity_key]
    
    if "forecast" not in entity_data:
        raise ValueError(f"Weather entity {entity_key} missing 'forecast' array")
    
    forecast_array = entity_data["forecast"]
    
    if not forecast_array or len(forecast_array) == 0:
        raise ValueError("Forecast array is empty")
    
    # Sort forecast by datetime to ensure chronological order
    try:
        sorted_forecast = sorted(
            forecast_array,
            key=lambda x: datetime.fromisoformat(x["datetime"].replace('Z', '+00:00'))
        )
    except (KeyError, ValueError, AttributeError) as e:
        raise ValueError(f"Invalid datetime in forecast array: {str(e)}")
    
    # Find the forecast entry closest to current time (current hour)
    current_forecast = None
    next_forecast = None
    
    for i, forecast_item in enumerate(sorted_forecast):
        try:
            forecast_dt = datetime.fromisoformat(forecast_item["datetime"].replace('Z', '+00:00'))
        except (ValueError, AttributeError, KeyError):
            # Skip invalid datetime entries
            continue
        
        # If this forecast is for current hour or just passed
        # Check if current_time falls within this forecast's hour window
        if forecast_dt <= current_dt < forecast_dt + timedelta(hours=1):
            current_forecast = forecast_item
            # Next forecast is the following entry
            if i + 1 < len(sorted_forecast):
                next_forecast = sorted_forecast[i + 1]
            break
        
        # If we haven't found current yet and this forecast is in the future
        # Use the first future forecast as current
        if forecast_dt > current_dt and current_forecast is None:
            current_forecast = forecast_item
            if i + 1 < len(sorted_forecast):
                next_forecast = sorted_forecast[i + 1]
            break
    
    # Fallback: use first two entries if no match found
    if current_forecast is None:
        logger.warning(f"No forecast entry matched current_time {current_time}, using first entry")
        current_forecast = sorted_forecast[0]
        next_forecast = sorted_forecast[1] if len(sorted_forecast) > 1 else None
    
    # Handle missing next_hour edge case
    if next_forecast is None:
        logger.warning("No next_hour forecast available, using current_hour data")
        next_forecast = current_forecast
    
    # Extract and transform data to internal format
    # Convert precipitation from 0-1 range to percentage
    precipitation_value = next_forecast.get("precipitation", 0)
    if isinstance(precipitation_value, (int, float)):
        precipitation_probability = precipitation_value * 100
    else:
        precipitation_probability = 0
    
    return {
        "current_hour": {
            "temperature": current_forecast["temperature"],
            "condition": current_forecast["condition"],
            "humidity": current_forecast["humidity"],
            "wind_speed": current_forecast["wind_speed"]
        },
        "next_hour": {
            "temperature": next_forecast["temperature"],
            "condition": next_forecast["condition"],
            "humidity": next_forecast["humidity"],
            "wind_speed": next_forecast["wind_speed"],
            "precipitation_probability": precipitation_probability
        }
    }


def validate_weather_condition(condition: Dict[str, Any], condition_name: str) -> Optional[Dict[str, str]]:
    """
    Validate a weather condition object (current_hour or next_hour) in internal format.
    
    This function validates weather data in the internal format (current_hour/next_hour structure),
    not the Home Assistant weather_forecast format. It is used to validate weather data after
    it has been extracted and transformed by extract_weather_data().
    
    Args:
        condition: Weather condition dictionary to validate (internal format)
        condition_name: Name of the condition for error messages (e.g., "current_hour", "next_hour")
    
    Returns:
        Error dict with message, details, and error_code if validation fails, None if valid
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
    
    This function validates the event structure for the laundry monitoring Lambda,
    ensuring all required fields are present and properly formatted. It checks for
    the presence of file_key, current_time, and weather_forecast fields, and validates
    the nested weather forecast structure from Home Assistant.
    
    Expected event structure:
    {
        "file_key": str,
        "current_time": str (ISO 8601 format),
        "weather_forecast": {
            "<entity_id>": {
                "forecast": [
                    {
                        "condition": str,
                        "datetime": str (ISO 8601 format),
                        "temperature": float,
                        "humidity": float,
                        "wind_speed": float,
                        "precipitation": float (optional, 0-1 range)
                    },
                    ...
                ]
            }
        }
    }
    
    Example:
        >>> event = {
        ...     "file_key": "camera_snapshot/20251110/120000_porch.jpg",
        ...     "current_time": "2025-10-12T02:00:00+00:00",
        ...     "weather_forecast": {
        ...         "weather.forecast_home": {
        ...             "forecast": [
        ...                 {
        ...                     "condition": "cloudy",
        ...                     "datetime": "2025-10-12T02:00:00+00:00",
        ...                     "temperature": 27.4,
        ...                     "wind_speed": 11.2,
        ...                     "precipitation": 0,
        ...                     "humidity": 79
        ...                 },
        ...                 {
        ...                     "condition": "rainy",
        ...                     "datetime": "2025-10-12T03:00:00+00:00",
        ...                     "temperature": 28.7,
        ...                     "wind_speed": 9.7,
        ...                     "precipitation": 0.65,
        ...                     "humidity": 75
        ...                 }
        ...             ]
        ...         }
        ...     }
        ... }
        >>> validate_input(event)
        None  # Returns None if validation passes
    
    Args:
        event: Lambda event dictionary containing file_key, current_time, and weather_forecast
    
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
    
    # Validate current_time
    if "current_time" not in event:
        return {
            "errors": [{
                "message": "Missing required field: current_time",
                "details": "The event must contain a 'current_time' field",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    current_time = event.get("current_time")
    if not isinstance(current_time, str):
        return {
            "errors": [{
                "message": "Invalid current_time",
                "details": "current_time must be a string in ISO 8601 format",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    # Parse and validate current_time using datetime.fromisoformat()
    try:
        datetime.fromisoformat(current_time.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return {
            "errors": [{
                "message": "Invalid current_time format",
                "details": "current_time must be a valid ISO 8601 timestamp",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    # Validate weather_forecast
    if "weather_forecast" not in event:
        return {
            "errors": [{
                "message": "Missing required field: weather_forecast",
                "details": "The event must contain a 'weather_forecast' field",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    weather_forecast = event.get("weather_forecast")
    if not isinstance(weather_forecast, dict):
        return {
            "errors": [{
                "message": "Invalid weather_forecast",
                "details": "weather_forecast must be an object",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    # Extract weather entity key (use first entity if multiple exist)
    weather_entities = list(weather_forecast.keys())
    if len(weather_entities) == 0:
        return {
            "errors": [{
                "message": "Invalid weather_forecast structure",
                "details": "weather_forecast must contain at least one weather entity",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    # Use the first weather entity
    entity_key = weather_entities[0]
    entity_data = weather_forecast[entity_key]
    
    if not isinstance(entity_data, dict):
        return {
            "errors": [{
                "message": "Invalid weather entity structure",
                "details": f"Weather entity '{entity_key}' must be an object",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    # Validate weather entity contains forecast array
    if "forecast" not in entity_data:
        return {
            "errors": [{
                "message": "Invalid weather entity structure",
                "details": f"Weather entity '{entity_key}' must contain 'forecast' array",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    forecast_array = entity_data["forecast"]
    if not isinstance(forecast_array, list):
        return {
            "errors": [{
                "message": "Invalid forecast structure",
                "details": "forecast must be an array",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    # Validate forecast array has at least 2 entries
    if len(forecast_array) < 2:
        return {
            "errors": [{
                "message": "Insufficient forecast data",
                "details": "forecast array must contain at least 2 hourly entries for current and next hour analysis",
                "error_code": "INPUT_VALIDATION_ERROR"
            }]
        }
    
    # Validate each forecast item has datetime field in ISO 8601 format
    # and call validate_forecast_item() for each forecast entry
    for i, forecast_item in enumerate(forecast_array):
        # Check for datetime field
        if not isinstance(forecast_item, dict):
            return {
                "errors": [{
                    "message": f"Invalid forecast item at index {i}",
                    "details": f"Forecast item at index {i} must be an object",
                    "error_code": "INPUT_VALIDATION_ERROR"
                }]
            }
        
        if "datetime" not in forecast_item:
            return {
                "errors": [{
                    "message": f"Invalid forecast item at index {i}",
                    "details": f"Forecast item at index {i} missing 'datetime' field",
                    "error_code": "INPUT_VALIDATION_ERROR"
                }]
            }
        
        # Validate datetime format
        try:
            datetime.fromisoformat(forecast_item["datetime"].replace('Z', '+00:00'))
        except (ValueError, AttributeError, TypeError):
            return {
                "errors": [{
                    "message": f"Invalid forecast item at index {i}",
                    "details": f"Forecast item at index {i} has invalid datetime format",
                    "error_code": "INPUT_VALIDATION_ERROR"
                }]
            }
        
        # Validate forecast item using validate_forecast_item()
        error = validate_forecast_item(forecast_item, f"forecast[{i}]")
        if error:
            return {"errors": [error]}
    
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
    
    This function converts the internal weather data structure (current_hour/next_hour)
    into a human-readable natural language description that is included in the Bedrock
    agent prompt. It analyzes temperature changes and formats all weather parameters
    into clear, descriptive sentences.
    
    Note: This function receives weather_data in internal format (current_hour/next_hour),
    not the raw Home Assistant weather_forecast format.
    
    Args:
        weather_data: Dictionary containing current_hour and next_hour weather data:
            {
                "current_hour": {
                    "temperature": float,
                    "condition": str,
                    "humidity": float,
                    "wind_speed": float
                },
                "next_hour": {
                    "temperature": float,
                    "condition": str,
                    "humidity": float,
                    "wind_speed": float,
                    "precipitation_probability": float (optional)
                }
            }
    
    Returns:
        Natural language description of weather conditions, e.g.:
        "Current weather: cloudy, temperature 27.4°C, humidity 79%, wind speed 11.2 km/h. 
        Next hour forecast: rainy, temperature 28.7°C, humidity 75%, wind speed 9.7 km/h, 
        precipitation probability 65%. Temperature rising by 1.3°C."
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
    weather_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Invoke AI agent to analyze laundry image with weather context.
    
    This function sends the camera image and weather data to the configured AI model
    (Bedrock or OpenRouter) for analysis. The agent detects laundry racks in open air
    areas, assesses weather risks, and provides bilingual recommendations.
    
    Note: The weather_data parameter receives the internal format (current_hour/next_hour
    structure), not the raw Home Assistant weather_forecast format. The weather_forecast
    is transformed to weather_data by extract_weather_data() before being passed here.
    
    Args:
        image_bytes: Raw image bytes from R2 storage
        image_format: Image format (e.g., 'jpeg', 'png')
        weather_data: Weather data in internal format with current_hour and next_hour:
            {
                "current_hour": {
                    "temperature": float,
                    "condition": str,
                    "humidity": float,
                    "wind_speed": float
                },
                "next_hour": {
                    "temperature": float,
                    "condition": str,
                    "humidity": float,
                    "wind_speed": float,
                    "precipitation_probability": float
                }
            }
    
    Returns:
        Dict containing analysis result or error information:
        {
            "result": LocalizedLaundryAnalysisResponse  # Pydantic model with en and zh_CN
        }
        or
        {
            "error": {
                "message": str,
                "details": str,
                "error_code": str
            }
        }
    """
    try:
        # Initialize model based on MODEL_PROVIDER
        if MODEL_PROVIDER == "bedrock":
            logger.info(f"Initializing Bedrock agent with model: {APPLICATION_INFERENCE_PROFILE_ARN}")
            
            # Create boto3 session for Bedrock
            boto3_session = boto3.Session(region_name=BEDROCK_REGION)
            
            # Initialize Bedrock model with timeout and retry configuration
            model = BedrockModel(
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
        else:
            logger.info(f"Initializing OpenRouter agent with model: {OPENROUTER_AI_MODEL_ID}")
            
            # Initialize OpenRouter model
            model = OpenAIModel(
                client_args={
                    "base_url": OPENROUTER_AI_URL,
                    "api_key": OPENROUTER_AI_API_KEY,
                },
                model_id=OPENROUTER_AI_MODEL_ID,
                params={
                    "reasoning": {
                        "enabled": True
                    }
                }
            )
        
        # Create agent with system prompt
        agent = Agent(
            model=model,
            system_prompt=LAUNDRY_MONITORING_SYSTEM_PROMPT,
        )
        
        # Format weather data into natural language
        weather_description = format_weather_data_for_prompt(weather_data)
        logger.info(f"Weather context: {weather_description}")
        
        # Prepare agent input with image and weather context
        # (timestamp and image URL are injected post-analysis by the handler,
        # not generated by the model, to reduce output tokens)
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
            }
        ]
        
        logger.info(f"Invoking {MODEL_PROVIDER or 'bedrock'} model for laundry analysis...")
        
        # Invoke model with structured output
        result = agent.structured_output(
            output_model=LocalizedLaundryAnalysisResponse,
            prompt=agent_input
        )
        
        logger.info(f"Successfully received structured output from {MODEL_PROVIDER or 'bedrock'}")
        
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


def validate_response(
    bedrock_response: LocalizedLaundryAnalysisResponse
) -> Dict[str, Any]:
    """
    Validate the agent's structured response.

    The Pydantic model already enforces field presence, types, enum values,
    and the confidence range via structured output. This function checks
    cross-language consistency between the English and Simplified Chinese
    localizations.

    Args:
        bedrock_response: Pydantic model instance from structured output

    Returns:
        Dict containing the validated response, or error information
    """
    try:
        logger.info("Validating agent response...")

        en_response = bedrock_response.en
        zh_response = bedrock_response.zh_CN

        # Verify both localizations agree on language-independent values
        if en_response.laundry_detected != zh_response.laundry_detected:
            logger.warning("Laundry detection mismatch between English and Chinese responses")

        if en_response.weather_risk_level != zh_response.weather_risk_level:
            logger.warning("Weather risk level mismatch between English and Chinese responses")

        if en_response.recommendation != zh_response.recommendation:
            logger.warning("Recommendation mismatch between English and Chinese responses")

        logger.info("Response validation completed successfully")

        return {
            "validated_response": bedrock_response
        }

    except AttributeError as e:
        logger.error(f"Missing attribute in agent response: {str(e)}", exc_info=True)
        return {
            "error": {
                "message": "Invalid agent response structure",
                "details": f"Response is missing required attributes: {str(e)}",
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
    
    Analyzes security camera images to detect laundry racks in open air areas and provides
    weather-aware recommendations to help homeowners protect their laundry from adverse
    weather conditions.
    
    This function orchestrates the complete laundry monitoring workflow:
    1. Validates input event structure (file_key, current_time, weather_forecast)
    2. Extracts and transforms weather forecast data from Home Assistant format
    3. Retrieves the camera image from R2 storage
    4. Generates a presigned URL for the image
    5. Invokes Bedrock AI agent for laundry detection and risk assessment
    6. Validates the response and injects timestamp and image URL
    7. Returns structured JSON with recommendations in English and Simplified Chinese
    
    This function implements comprehensive error handling with structured error responses,
    appropriate error codes, and proper logging at each step.
    
    Args:
        event: Lambda event dictionary containing:
            - file_key (str): R2 object key for the camera snapshot image
            - current_time (str): ISO 8601 timestamp for current time context
            - weather_forecast (dict): Home Assistant weather forecast structure with entity data
        context: Lambda context object (provided by AWS Lambda runtime)
    
    Returns:
        Dict containing analysis results or error information:
        
        Success response:
        {
            "data": {
                "result": {
                    "en": {
                        "laundry_detected": bool,
                        "weather_risk_level": "low|medium|high",
                        "weather_summary": str,
                        "recommendation": "bring_inside|leave_outside|no_action",
                        "recommendation_reason": str,
                        "confidence": float,
                        "timestamp": str,
                        "image_url": str
                    },
                    "zh_CN": { ... }  # Same structure in Simplified Chinese
                }
            }
        }
        
        Error response:
        {
            "errors": [{
                "message": str,
                "details": str,
                "error_code": str
            }]
        }
    
    Expected event structure:
        {
            "file_key": "camera_snapshot/20251110/120000_porch.jpg",
            "current_time": "2025-10-12T02:00:00+00:00",
            "weather_forecast": {
                "weather.forecast_home": {
                    "forecast": [
                        {
                            "condition": "cloudy",
                            "datetime": "2025-10-12T02:00:00+00:00",
                            "temperature": 27.4,
                            "wind_speed": 11.2,
                            "precipitation": 0,
                            "humidity": 79
                        },
                        {
                            "condition": "rainy",
                            "datetime": "2025-10-12T03:00:00+00:00",
                            "temperature": 28.7,
                            "wind_speed": 9.7,
                            "precipitation": 0.65,
                            "humidity": 75
                        }
                    ]
                }
            }
        }
    
    Example usage:
        >>> event = {
        ...     "file_key": "camera_snapshot/20251110/120000_porch.jpg",
        ...     "current_time": "2025-10-12T02:00:00+00:00",
        ...     "weather_forecast": {
        ...         "weather.forecast_home": {
        ...             "forecast": [
        ...                 {
        ...                     "condition": "cloudy",
        ...                     "datetime": "2025-10-12T02:00:00+00:00",
        ...                     "temperature": 27.4,
        ...                     "wind_speed": 11.2,
        ...                     "precipitation": 0,
        ...                     "humidity": 79
        ...                 },
        ...                 {
        ...                     "condition": "rainy",
        ...                     "datetime": "2025-10-12T03:00:00+00:00",
        ...                     "temperature": 28.7,
        ...                     "wind_speed": 9.7,
        ...                     "precipitation": 0.65,
        ...                     "humidity": 75
        ...                 }
        ...             ]
        ...         }
        ...     }
        ... }
        >>> result = handler(event, None)
        >>> result["data"]["result"]["en"]["recommendation"]
        'bring_inside'  # Example output
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
            "current_time": event.get("current_time", ""),
            "weather_forecast": "present" if "weather_forecast" in event else "missing"
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
        current_time = event["current_time"]
        weather_forecast = event["weather_forecast"]
        
        # Extract and transform weather data from Home Assistant format to internal format
        try:
            weather_data = extract_weather_data(weather_forecast, current_time)
            logger.debug(f"Successfully extracted weather data from forecast")
        except Exception as e:
            logger.error(f"Failed to extract weather data: {str(e)}", exc_info=True)
            return {
                "errors": [{
                    "message": "Weather data extraction error",
                    "details": f"Failed to extract weather data from forecast: {str(e)}",
                    "error_code": "INPUT_VALIDATION_ERROR"
                }]
            }
        
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
            # Task 8: Validate the response
            validation_result = validate_response(
                bedrock_response=analysis_result
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
            # Task 9: Format success response with data.result structure.
            # Both language versions are always included in every response
            # (Requirements 5.1, 5.2), returned as structured JSON (Requirement 6.3).

            # timestamp and image_url are identical across languages and were
            # not generated by the model (saves output tokens) — inject them here.
            current_timestamp = datetime.now(timezone.utc).isoformat()

            en_result = validated_response.en.model_dump()
            en_result["timestamp"] = current_timestamp
            en_result["image_url"] = presigned_url

            zh_result = validated_response.zh_CN.model_dump()
            zh_result["timestamp"] = current_timestamp
            zh_result["image_url"] = presigned_url

            success_response = {
                "data": {
                    "result": {
                        "en": en_result,
                        "zh_CN": zh_result
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
    # Test with valid input using weather_forecast and current_time
    test_event = {
        "file_key": "camera_snapshot/20251110/120000_porch.jpg",
        "current_time": "2025-10-12T02:00:00+00:00",
        "weather_forecast": {
            "weather.forecast_home": {
                "forecast": [
                    {
                        "condition": "clear",
                        "datetime": "2025-10-12T02:00:00+00:00",
                        "temperature": 28.5,
                        "wind_speed": 12.5,
                        "precipitation": 0,
                        "humidity": 65.0,
                        "wind_bearing": 180.0,
                        "cloud_coverage": 10.0,
                        "uv_index": 5.0
                    },
                    {
                        "condition": "cloudy",
                        "datetime": "2025-10-12T03:00:00+00:00",
                        "temperature": 29.0,
                        "wind_speed": 15.0,
                        "precipitation": 0.20,
                        "humidity": 70.0,
                        "wind_bearing": 190.0,
                        "cloud_coverage": 60.0,
                        "uv_index": 4.5
                    },
                    {
                        "condition": "rainy",
                        "datetime": "2025-10-12T04:00:00+00:00",
                        "temperature": 27.0,
                        "wind_speed": 18.0,
                        "precipitation": 0.75,
                        "humidity": 85.0
                    }
                ]
            }
        }
    }
    
    result = handler(test_event, None)
    print("Valid input test with weather_forecast and current_time:")
    print(json.dumps(result, indent=2))
    
    # Test with missing file_key
    invalid_event_1 = {
        "current_time": "2025-10-12T02:00:00+00:00",
        "weather_forecast": {
            "weather.forecast_home": {
                "forecast": [
                    {
                        "condition": "clear",
                        "datetime": "2025-10-12T02:00:00+00:00",
                        "temperature": 28.5,
                        "wind_speed": 12.5,
                        "precipitation": 0,
                        "humidity": 65.0
                    },
                    {
                        "condition": "cloudy",
                        "datetime": "2025-10-12T03:00:00+00:00",
                        "temperature": 29.0,
                        "wind_speed": 15.0,
                        "precipitation": 0.20,
                        "humidity": 70.0
                    }
                ]
            }
        }
    }
    
    result = handler(invalid_event_1, None)
    print("\nMissing file_key test:")
    print(json.dumps(result, indent=2))
    
    # Test with missing weather_forecast
    invalid_event_2 = {
        "file_key": "camera_snapshot/20251110/120000_porch.jpg",
        "current_time": "2025-10-12T02:00:00+00:00"
    }
    
    result = handler(invalid_event_2, None)
    print("\nMissing weather_forecast test:")
    print(json.dumps(result, indent=2))
    
    # Test with missing current_time
    invalid_event_3 = {
        "file_key": "camera_snapshot/20251110/120000_porch.jpg",
        "weather_forecast": {
            "weather.forecast_home": {
                "forecast": [
                    {
                        "condition": "clear",
                        "datetime": "2025-10-12T02:00:00+00:00",
                        "temperature": 28.5,
                        "wind_speed": 12.5,
                        "precipitation": 0,
                        "humidity": 65.0
                    },
                    {
                        "condition": "cloudy",
                        "datetime": "2025-10-12T03:00:00+00:00",
                        "temperature": 29.0,
                        "wind_speed": 15.0,
                        "precipitation": 0.20,
                        "humidity": 70.0
                    }
                ]
            }
        }
    }
    
    result = handler(invalid_event_3, None)
    print("\nMissing current_time test:")
    print(json.dumps(result, indent=2))
    
    # Test with invalid current_time format
    invalid_event_4 = {
        "file_key": "camera_snapshot/20251110/120000_porch.jpg",
        "current_time": "not-a-valid-timestamp",
        "weather_forecast": {
            "weather.forecast_home": {
                "forecast": [
                    {
                        "condition": "clear",
                        "datetime": "2025-10-12T02:00:00+00:00",
                        "temperature": 28.5,
                        "wind_speed": 12.5,
                        "precipitation": 0,
                        "humidity": 65.0
                    },
                    {
                        "condition": "cloudy",
                        "datetime": "2025-10-12T03:00:00+00:00",
                        "temperature": 29.0,
                        "wind_speed": 15.0,
                        "precipitation": 0.20,
                        "humidity": 70.0
                    }
                ]
            }
        }
    }
    
    result = handler(invalid_event_4, None)
    print("\nInvalid current_time format test:")
    print(json.dumps(result, indent=2))
    
    # Test with insufficient forecast entries (less than 2)
    invalid_event_5 = {
        "file_key": "camera_snapshot/20251110/120000_porch.jpg",
        "current_time": "2025-10-12T02:00:00+00:00",
        "weather_forecast": {
            "weather.forecast_home": {
                "forecast": [
                    {
                        "condition": "clear",
                        "datetime": "2025-10-12T02:00:00+00:00",
                        "temperature": 28.5,
                        "wind_speed": 12.5,
                        "precipitation": 0,
                        "humidity": 65.0
                    }
                ]
            }
        }
    }
    
    result = handler(invalid_event_5, None)
    print("\nInsufficient forecast entries test:")
    print(json.dumps(result, indent=2))
    
    # Test with path traversal attempt using weather_forecast
    invalid_event_6 = {
        "file_key": "../../../etc/passwd",
        "current_time": "2025-10-12T02:00:00+00:00",
        "weather_forecast": {
            "weather.forecast_home": {
                "forecast": [
                    {
                        "condition": "clear",
                        "datetime": "2025-10-12T02:00:00+00:00",
                        "temperature": 28.5,
                        "wind_speed": 12.5,
                        "precipitation": 0,
                        "humidity": 65.0
                    },
                    {
                        "condition": "cloudy",
                        "datetime": "2025-10-12T03:00:00+00:00",
                        "temperature": 29.0,
                        "wind_speed": 15.0,
                        "precipitation": 0.20,
                        "humidity": 70.0
                    }
                ]
            }
        }
    }
    
    result = handler(invalid_event_6, None)
    print("\nPath traversal attack test with weather_forecast:")
    print(json.dumps(result, indent=2))
    
    # Test with absolute path using weather_forecast
    invalid_event_7 = {
        "file_key": "/etc/passwd",
        "current_time": "2025-10-12T02:00:00+00:00",
        "weather_forecast": {
            "weather.forecast_home": {
                "forecast": [
                    {
                        "condition": "clear",
                        "datetime": "2025-10-12T02:00:00+00:00",
                        "temperature": 28.5,
                        "wind_speed": 12.5,
                        "precipitation": 0,
                        "humidity": 65.0
                    },
                    {
                        "condition": "cloudy",
                        "datetime": "2025-10-12T03:00:00+00:00",
                        "temperature": 29.0,
                        "wind_speed": 15.0,
                        "precipitation": 0.20,
                        "humidity": 70.0
                    }
                ]
            }
        }
    }
    
    result = handler(invalid_event_7, None)
    print("\nAbsolute path test with weather_forecast:")
    print(json.dumps(result, indent=2))
