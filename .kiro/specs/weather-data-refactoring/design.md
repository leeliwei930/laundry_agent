# Design Document

## Overview

This design document outlines the refactoring approach for changing the weather data input key from `weather_data` to `weather_forecast` in the laundry monitoring Lambda function. The refactoring is a focused change that updates the input interface while maintaining all existing functionality and internal data structures.

The design follows a systematic approach: update the input validation layer, modify the handler's data extraction, update function signatures and documentation, and ensure all test cases reflect the new structure. This approach minimizes risk by keeping changes isolated to the input layer while preserving all downstream processing logic.

## Architecture

### Current Architecture

The Lambda function currently expects this ere:

```json
{
  "file_key": "camera_snapshot/20251110/120000_porch.jpg",
  "weather_data": {
    "current_hour": {
      "temperature": 28.5,
      "condition": "cloudy",
      "humidity": 75,
      "wind_speed": 12.5
    },
    "next_hour": {
      "temperature": 27.8,
      "condition": "rainy",
      "humidity": 82,
      "wind_speed": 15.0,
      "precipitation_probability": 65
    }
  }
}
```

### Target Architecture

The refactored function will expect this event structure:

```json
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
          "humidity": 79,
          "wind_bearing": 264.8,
          "cloud_coverage": 95.3,
          "uv_index": 6.1
        },
        {
          "condition": "rainy",
          "datetime": "2025-10-12T03:00:00+00:00",
          "temperature": 28.7,
          "wind_speed": 9.7,
          "precipitation": 0.1,
          "humidity": 75
        }
      ]
    }
  }
}
```

**Design Rationale**: The new structure aligns with Home Assistant's weather entity format, which provides weather forecast data with entity IDs (e.g., `weather.forecast_home`). The `current_time` parameter allows the system to intelligently match forecast entries to current and next hour, making the integration more robust and time-aware. This eliminates assumptions about forecast array ordering and enables accurate temporal analysis.

### Data Flow Changes

```
┌─────────────────────────────────────────────────────────────┐
│ Lambda Event Input                                          │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ OLD: event["weather_data"]                              │ │
│ │ NEW: event["weather_forecast"]                          │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Input Validation (validate_input)                          │
│ - Check for "weather_forecast" key                         │
│ - Validate nested structure                                │
│ - Extract weather entity data                              │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Weather Data Extraction                                     │
│ - Extract forecast array from weather entity               │
│ - Map forecast items to current_hour/next_hour structure   │
│ - Maintain existing internal format                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Weather Processing (format_weather_data_for_prompt)        │
│ - NO CHANGES - receives same data structure                │
│ - Formats weather description for Bedrock agent            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Bedrock Agent Analysis                                      │
│ - NO CHANGES - receives same weather context               │
└─────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### 1. Input Validation Layer

**Component**: `validate_input(event: Dict[str, Any]) -> Optional[Dict[str, Any]]`

**Changes Required**:
- Update key check from `"weather_data"` to `"weather_forecast"`
- Update error messages to reference `weather_forecast`
- Add validation for weather entity structure (e.g., `weather.forecast_home`)
- Extract forecast array from nested entity structure
- Validate forecast array contains required hourly data

**New Validation Logic**:
```python
def validate_input(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # Check for current_time key
    if "current_time" not in event:
        return error_response("Missing required field: current_time")
    
    current_time = event.get("current_time")
    if not isinstance(current_time, str):
        return error_response("current_time must be a string in ISO 8601 format")
    
    # Validate ISO 8601 format
    try:
        datetime.fromisoformat(current_time.replace('Z', '+00:00'))
    except ValueError:
        return error_response("current_time must be a valid ISO 8601 timestamp")
    
    # Check for weather_forecast key
    if "weather_forecast" not in event:
        return error_response("Missing required field: weather_forecast")
    
    weather_forecast = event.get("weather_forecast")
    if not isinstance(weather_forecast, dict):
        return error_response("weather_forecast must be an object")
    
    # Extract weather entity (e.g., weather.forecast_home)
    # Expect a single weather entity key
    weather_entities = list(weather_forecast.keys())
    if len(weather_entities) == 0:
        return error_response("weather_forecast must contain at least one weather entity")
    
    # Use the first weather entity
    entity_key = weather_entities[0]
    entity_data = weather_forecast[entity_key]
    
    # Validate forecast array exists
    if "forecast" not in entity_data:
        return error_response(f"Weather entity {entity_key} must contain 'forecast' array")
    
    forecast_array = entity_data["forecast"]
    if not isinstance(forecast_array, list) or len(forecast_array) < 2:
        return error_response("forecast array must contain at least 2 hourly entries")
    
    # Validate that forecast items have datetime field
    for i, forecast_item in enumerate(forecast_array):
        if "datetime" not in forecast_item:
            return error_response(f"Forecast item at index {i} missing 'datetime' field")
        
        # Validate datetime format
        try:
            datetime.fromisoformat(forecast_item["datetime"].replace('Z', '+00:00'))
        except ValueError:
            return error_response(f"Forecast item at index {i} has invalid datetime format")
        
        # Validate required weather fields
        error = validate_forecast_item(forecast_item, f"forecast[{i}]")
        if error:
            return error
    
    return None
```

**Design Rationale**: The validation layer now handles the nested weather entity structure while maintaining the same validation requirements for the actual weather data fields. This allows the upstream system to send data in Home Assistant's native format.

### 2. Weather Data Extraction

**Component**: New helper function `extract_weather_data(weather_forecast: Dict[str, Any]) -> Dict[str, Any]`

**Purpose**: Transform the Home Assistant weather forecast structure into the internal format expected by downstream functions.

**Implementation**:
```python
def extract_weather_data(weather_forecast: Dict[str, Any], current_time: str) -> Dict[str, Any]:
    """
    Extract and transform weather forecast data from Home Assistant format
    to internal processing format, using current_time to identify relevant forecast entries.
    
    Args:
        weather_forecast: Weather forecast dict with entity structure
        current_time: ISO 8601 timestamp representing current time
    
    Returns:
        Dict with current_hour and next_hour weather data
    """
    from datetime import datetime, timedelta
    
    # Parse current time
    current_dt = datetime.fromisoformat(current_time.replace('Z', '+00:00'))
    
    # Get first weather entity
    entity_key = list(weather_forecast.keys())[0]
    entity_data = weather_forecast[entity_key]
    forecast_array = entity_data["forecast"]
    
    # Find forecast entries for current hour and next hour
    # Sort forecast by datetime to ensure chronological order
    sorted_forecast = sorted(
        forecast_array,
        key=lambda x: datetime.fromisoformat(x["datetime"].replace('Z', '+00:00'))
    )
    
    # Find the forecast entry closest to current time (current hour)
    current_forecast = None
    next_forecast = None
    
    for i, forecast_item in enumerate(sorted_forecast):
        forecast_dt = datetime.fromisoformat(forecast_item["datetime"].replace('Z', '+00:00'))
        
        # If this forecast is for current hour or just passed
        if forecast_dt <= current_dt < forecast_dt + timedelta(hours=1):
            current_forecast = forecast_item
            # Next forecast is the following entry
            if i + 1 < len(sorted_forecast):
                next_forecast = sorted_forecast[i + 1]
            break
        
        # If we haven't found current yet and this forecast is in the future
        if forecast_dt > current_dt and current_forecast is None:
            current_forecast = forecast_item
            if i + 1 < len(sorted_forecast):
                next_forecast = sorted_forecast[i + 1]
            break
    
    # Fallback: use first two entries if no match found
    if current_forecast is None:
        current_forecast = sorted_forecast[0]
        next_forecast = sorted_forecast[1] if len(sorted_forecast) > 1 else sorted_forecast[0]
    
    if next_forecast is None:
        next_forecast = current_forecast
    
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
            "precipitation_probability": next_forecast.get("precipitation", 0) * 100  # Convert to percentage
        }
    }
```

**Design Rationale**: This extraction layer uses the `current_time` parameter to intelligently identify which forecast entries correspond to the current and next hour. This makes the system robust to forecast arrays that may not start at the current time, and handles cases where forecasts are provided at different intervals. The function sorts forecasts chronologically and finds the most relevant entries based on temporal proximity to `current_time`.

### 3. Handler Function Updates

**Component**: `handler(event, context)`

**Changes Required**:
- Update event extraction: `weather_forecast = event["weather_forecast"]`
- Call new extraction function: `weather_data = extract_weather_data(weather_forecast)`
- Update logging to reference `weather_forecast`
- Pass extracted `weather_data` to existing functions (no changes to downstream calls)

**Updated Handler Logic**:
```python
def handler(event, context):
    # ... existing validation ...
    
    file_key = event["file_key"]
    current_time = event["current_time"]  # NEW
    weather_forecast = event["weather_forecast"]  # Changed from weather_data
    
    # Extract and transform weather data using current_time
    weather_data = extract_weather_data(weather_forecast, current_time)
    
    # Log sanitized event
    sanitized_event = {
        "file_key": event.get("file_key", ""),
        "current_time": event.get("current_time", ""),  # NEW
        "weather_forecast": "present" if "weather_forecast" in event else "missing"  # Updated
    }
    logger.info(f"Received event: {json.dumps(sanitized_event)}")
    
    # ... rest of handler unchanged, uses weather_data internally ...
```

**Design Rationale**: The handler acts as an adapter, accepting the new input format but immediately transforming it to the internal format. This minimizes changes to downstream functions.

### 4. Function Signature Updates

**Component**: `analyze_laundry_with_bedrock()`

**Current Signature**:
```python
def analyze_laundry_with_bedrock(
    image_bytes: bytes,
    image_format: str,
    presigned_url: str,
    weather_data: Dict[str, Any]
) -> Dict[str, Any]:
```

**Design Decision**: Keep the parameter name as `weather_data` since this function receives the internal format (current_hour/next_hour structure), not the raw event input. The parameter name accurately reflects what the function receives.

**Alternative Considered**: Rename to `weather_forecast` for consistency with input. **Rejected** because this would be misleading - the function doesn't receive the forecast array structure, it receives the extracted current_hour/next_hour data.

### 5. Documentation Updates

**Components to Update**:
- Function docstrings referencing weather input
- Inline comments about event structure
- Lambda handler docstring
- Design document event schema examples
- Task descriptions in tasks.md

**Documentation Pattern**:
- Use `weather_forecast` when referring to the Lambda event input
- Use `weather_data` when referring to the internal current_hour/next_hour structure
- Clearly distinguish between "input format" and "internal format" in documentation

## Data Models

### Input Event Schema

```python
{
    "file_key": str,  # R2 object key
    "current_time": str,  # NEW: ISO 8601 timestamp for current time context
    "weather_forecast": {  # NEW: Changed from weather_data
        "<entity_id>": {  # e.g., "weather.forecast_home"
            "forecast": [  # Array of hourly forecasts
                {
                    "condition": str,
                    "datetime": str,  # ISO 8601 timestamp
                    "temperature": float,
                    "wind_speed": float,
                    "precipitation": float,  # 0-1 range (will be converted to percentage)
                    "humidity": float,
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

### Internal Weather Data Schema (Unchanged)

```python
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
        "precipitation_probability": float  # Percentage
    }
}
```

**Design Rationale**: Maintaining the internal schema unchanged ensures that all weather analysis logic, prompt formatting, and Bedrock agent processing continue to work without modification.

## Error Handling

### New Error Messages

All error messages referencing the weather input will be updated:

**Before**:
- "Missing required field: weather_data"
- "Invalid weather_data"
- "weather_data must be an object"
- "Missing required field: weather_data.current_hour"

**After**:
- "Missing required field: weather_forecast"
- "Invalid weather_forecast"
- "weather_forecast must be an object"
- "weather_forecast must contain at least one weather entity"
- "Weather entity {entity_id} must contain 'forecast' array"
- "forecast array must contain at least 2 hourly entries"
- "Invalid forecast item at index {i}: missing required field {field}"

### Error Handling for New Structure

**Scenario 1**: Missing weather_forecast key
```python
{
    "errors": [{
        "message": "Missing required field: weather_forecast",
        "details": "The event must contain a 'weather_forecast' field",
        "error_code": "INPUT_VALIDATION_ERROR"
    }]
}
```

**Scenario 2**: Empty weather entity
```python
{
    "errors": [{
        "message": "Invalid weather_forecast structure",
        "details": "weather_forecast must contain at least one weather entity",
        "error_code": "INPUT_VALIDATION_ERROR"
    }]
}
```

**Scenario 3**: Missing forecast array
```python
{
    "errors": [{
        "message": "Invalid weather entity structure",
        "details": "Weather entity 'weather.forecast_home' must contain 'forecast' array",
        "error_code": "INPUT_VALIDATION_ERROR"
    }]
}
```

**Scenario 4**: Insufficient forecast data
```python
{
    "errors": [{
        "message": "Insufficient forecast data",
        "details": "forecast array must contain at least 2 hourly entries for current and next hour analysis",
        "error_code": "INPUT_VALIDATION_ERROR"
    }]
}
```

## Testing Strategy

### Unit Tests

1. **Input Validation Tests**
   - Test with valid weather_forecast structure
   - Test with missing weather_forecast key
   - Test with invalid weather_forecast type (not dict)
   - Test with empty weather entity
   - Test with missing forecast array
   - Test with insufficient forecast entries (< 2)
   - Test with missing required fields in forecast items

2. **Weather Data Extraction Tests**
   - Test extraction of current_hour and next_hour from forecast array
   - Test precipitation conversion (0-1 range to percentage)
   - Test handling of optional fields (wind_bearing, cloud_coverage, uv_index)
   - Test with multiple weather entities (should use first one)

3. **Handler Integration Tests**
   - Test end-to-end with new weather_forecast structure
   - Test that extracted weather_data is correctly passed to downstream functions
   - Test logging shows correct field names

### Test Data

**Valid Test Event**:
```python
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
```

### Regression Testing

Ensure all existing functionality continues to work:
- Image retrieval from R2
- Presigned URL generation
- Bedrock agent analysis
- Response formatting (bilingual output)
- Error handling for non-weather errors

## Migration Considerations

### Breaking Change

This is a **breaking change** for any systems calling the Lambda function. Callers must update their event structure from `weather_data` to `weather_forecast`.

### Migration Path

1. **Update Lambda function code** with new input structure
2. **Update calling systems** (Home Assistant automation, API Gateway, etc.) to send `weather_forecast` instead of `weather_data`
3. **Update documentation** to reflect new event structure
4. **Test integration** end-to-end before deploying to production

### Backward Compatibility Option (Not Recommended)

If backward compatibility is required temporarily, the handler could accept both keys:

```python
# Check for new key first, fall back to old key
if "weather_forecast" in event:
    weather_forecast = event["weather_forecast"]
    weather_data = extract_weather_data(weather_forecast)
elif "weather_data" in event:
    # Legacy format - use directly
    weather_data = event["weather_data"]
    logger.warning("Using deprecated 'weather_data' key. Please update to 'weather_forecast'")
else:
    return validation_error("Missing weather data")
```

**Recommendation**: Implement a clean break rather than maintaining backward compatibility, as this is an internal system with controlled callers.

## Implementation Notes

### Order of Changes

1. Create `extract_weather_data()` helper function
2. Create `validate_forecast_item()` helper function
3. Update `validate_input()` function
4. Update `handler()` function
5. Update all error messages
6. Update docstrings and comments
7. Update test cases
8. Update documentation files (design.md, tasks.md)

### Code Review Checklist

- [ ] All references to `weather_data` in event handling updated to `weather_forecast`
- [ ] New validation logic handles weather entity structure
- [ ] Extraction function correctly maps forecast array to internal format
- [ ] Precipitation conversion from 0-1 to percentage is correct
- [ ] All error messages reference correct field names
- [ ] Docstrings updated for affected functions
- [ ] Test cases updated with new event structure
- [ ] Logging statements reference correct field names
- [ ] Documentation files updated (design.md, tasks.md)
- [ ] No changes to downstream weather processing logic

