# Requirements Document

## Introduction

This specification defines the refactoring of the weather data input structure for the laundry monitoring Lambda function. Currently, the Lambda function expects weather forecast data under the key `weather_data` in the event object. This refactoring will change the input key from `weather_data` to `weather_forecast` to better align with the actual data structure being passed from the Home Assistant integration, which provides weather forecast data with entity IDs like `weather.forecast_home`.

The refactoring maintains backward compatibility considerations while updating all validation, processing, and documentation to use the new key name. This change improves code clarity and consistency with the upstream data source.

## Requirements

### Requirement 1: Update Lambda Event Input Structure

**User Story:** As a system integrator, I want the Lambda function to accept weather forecast data under the key `weather_forecast` and a `current_time` parameter, so that the input structure matches the Home Assistant weather entity naming convention and enables time-aware forecast analysis.

#### Acceptance Criteria

1. WHEN the Lambda handler receives an event THEN it SHALL expect weather forecast data under the key `weather_forecast`
2. WHEN the Lambda handler receives an event THEN it SHALL expect a `current_time` parameter in ISO 8601 format
3. WHEN the event contains `weather_forecast` key THEN the system SHALL extract and process the nested weather entity data (e.g., `weather.forecast_home`)
4. WHEN the event is missing the `weather_forecast` key THEN the system SHALL return a validation error with error code `INPUT_VALIDATION_ERROR`
5. WHEN the event is missing the `current_time` key THEN the system SHALL return a validation error with error code `INPUT_VALIDATION_ERROR`
6. WHEN the `weather_forecast` value is not a dictionary THEN the system SHALL return a validation error indicating the field must be an object
7. WHEN the `current_time` value is not a valid ISO 8601 timestamp THEN the system SHALL return a validation error

### Requirement 2: Update Input Validation Logic

**User Story:** As a developer, I want all input validation functions to check for `weather_forecast` instead of `weather_data`, so that validation errors accurately reflect the expected input structure.

#### Acceptance Criteria

1. WHEN the `validate_input()` function runs THEN it SHALL check for the presence of `weather_forecast` key instead of `weather_data`
2. WHEN validation fails for missing weather forecast THEN the error message SHALL reference `weather_forecast` not `weather_data`
3. WHEN the weather forecast structure is validated THEN it SHALL still expect `current_hour` and `next_hour` nested within the forecast entity data
4. WHEN validation error messages are generated THEN they SHALL use the terminology `weather_forecast` consistently

### Requirement 3: Update Weather Data Processing

**User Story:** As a developer, I want the weather data extraction and formatting functions to work with the new `weather_forecast` structure and use `current_time` to identify relevant forecast entries, so that weather analysis is accurate and time-aware.

#### Acceptance Criteria

1. WHEN the handler extracts weather data from the event THEN it SHALL access `event["weather_forecast"]` and `event["current_time"]`
2. WHEN the extraction function processes forecast data THEN it SHALL use `current_time` to identify which forecast entries correspond to current hour and next hour
3. WHEN forecast entries are matched to current/next hour THEN the system SHALL sort forecasts chronologically by datetime
4. WHEN the current hour forecast is identified THEN it SHALL be the entry whose datetime is closest to or contains the `current_time`
5. WHEN the next hour forecast is identified THEN it SHALL be the chronologically next entry after the current hour
6. WHEN the `format_weather_data_for_prompt()` function is called THEN it SHALL continue to receive the same weather data structure (current_hour and next_hour)
7. WHEN weather data is passed to the Bedrock agent THEN the internal format SHALL remain unchanged (only the input extraction logic changes)
8. WHEN the system logs weather data presence THEN log messages SHALL reference `weather_forecast` and `current_time`

### Requirement 4: Update Function Signatures and Documentation

**User Story:** As a developer, I want function signatures, docstrings, and comments to accurately reflect the new `weather_forecast` parameter name, so that the codebase is self-documenting and maintainable.

#### Acceptance Criteria

1. WHEN the `analyze_laundry_with_bedrock()` function signature is reviewed THEN the parameter SHALL be named `weather_forecast` instead of `weather_data`
2. WHEN function docstrings reference weather data input THEN they SHALL use the term `weather_forecast`
3. WHEN inline comments reference the weather input THEN they SHALL use consistent terminology with `weather_forecast`
4. WHEN the Lambda handler docstring describes the event structure THEN it SHALL document `weather_forecast` as the expected key

### Requirement 5: Update Test Cases and Examples

**User Story:** As a developer, I want all test cases and example events to use the new `weather_forecast` and `current_time` keys, so that testing accurately reflects production usage.

#### Acceptance Criteria

1. WHEN test events are defined in the code THEN they SHALL use `weather_forecast` as the key for weather data and include `current_time`
2. WHEN the `if __name__ == "__main__"` test block runs THEN all test events SHALL use `weather_forecast` and `current_time`
3. WHEN validation error tests are executed THEN they SHALL test for missing or invalid `weather_forecast` and `current_time` data
4. WHEN test output is logged THEN it SHALL reference `weather_forecast` and `current_time` in test descriptions
5. WHEN time-based extraction is tested THEN test cases SHALL verify correct matching of forecast entries to current/next hour based on `current_time`

### Requirement 6: Update Related Documentation

**User Story:** As a system administrator, I want deployment documentation and specifications to reflect the new input structure, so that I can correctly configure the Lambda function integration.

#### Acceptance Criteria

1. WHEN the design document is reviewed THEN it SHALL show `weather_forecast` in the event structure examples
2. WHEN the tasks document is reviewed THEN task descriptions SHALL reference `weather_forecast` validation
3. WHEN API documentation exists THEN it SHALL be updated to show the new event structure
4. WHEN integration examples are provided THEN they SHALL use `weather_forecast` as the input key

### Requirement 7: Maintain Data Structure Compatibility

**User Story:** As a developer, I want the internal weather data structure to remain unchanged, so that existing weather analysis logic continues to work without modification.

#### Acceptance Criteria

1. WHEN weather data is extracted from `weather_forecast` THEN it SHALL maintain the same nested structure with `current_hour` and `next_hour`
2. WHEN the `format_weather_data_for_prompt()` function processes data THEN it SHALL work with the same data format as before
3. WHEN weather validation functions are called THEN they SHALL validate the same fields (temperature, condition, humidity, wind_speed, precipitation_probability)
4. WHEN the Bedrock agent receives weather context THEN the formatted weather description SHALL remain unchanged in structure and content
