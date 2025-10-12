# Implementation Plan

- [x] 1. Create helper functions for weather data extraction
  - Create `extract_weather_data(weather_forecast, current_time)` function that transforms Home Assistant forecast format to internal current_hour/next_hour structure
  - Implement datetime parsing and comparison logic to match forecast entries to current_time
  - Sort forecast array chronologically by datetime field
  - Find forecast entry closest to current_time for current_hour
  - Select next chronological entry for next_hour
  - Convert precipitation from 0-1 range to percentage (multiply by 100)
  - Handle edge cases: missing next_hour, empty forecast array, invalid datetimes
  - _Requirements: 1.2, 1.3, 3.1, 3.2, 3.3, 3.4, 3.5, 7.1, 7.2_

- [x] 2. Create validation helper for forecast items
  - Create `validate_forecast_item(forecast_item, item_name)` function
  - Validate required fields: condition, datetime, temperature, humidity, wind_speed
  - Validate field types (temperature/humidity/wind_speed are numeric, condition is string)
  - Validate datetime is valid ISO 8601 format
  - Return structured error dict with message, details, and error_code
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 3. Update input validation function
  - Update `validate_input()` to check for `current_time` field first
  - Validate `current_time` is a string in ISO 8601 format
  - Parse and validate `current_time` using datetime.fromisoformat()
  - Update check from `weather_data` to `weather_forecast`
  - Validate `weather_forecast` is a dictionary
  - Extract weather entity key (use first entity if multiple exist)
  - Validate weather entity contains `forecast` array
  - Validate forecast array has at least 2 entries
  - Validate each forecast item has `datetime` field in ISO 8601 format
  - Call `validate_forecast_item()` for each forecast entry
  - Update all error messages to reference `weather_forecast` instead of `weather_data`
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4_

- [x] 4. Update Lambda handler function
  - Extract `current_time` from event: `current_time = event["current_time"]`
  - Update weather data extraction: `weather_forecast = event["weather_forecast"]`
  - Call new extraction function: `weather_data = extract_weather_data(weather_forecast, current_time)`
  - Update sanitized event logging to include `current_time` field
  - Update sanitized event logging to reference `weather_forecast` instead of `weather_data`
  - Pass extracted `weather_data` to `analyze_laundry_with_bedrock()` (no changes to this call)
  - Update handler docstring to document new event structure with `current_time` and `weather_forecast`
  - _Requirements: 1.1, 1.2, 1.5, 3.1, 3.8, 4.1, 4.2, 4.3_

- [x] 5. Update function docstrings and comments
  - Update `validate_input()` docstring to reference `weather_forecast` and `current_time`
  - Update inline comments in validation logic that reference weather input
  - Update handler function docstring to show new event structure
  - Add docstring examples showing `weather_forecast` and `current_time` usage
  - Review and update any comments that reference `weather_data` to use `weather_forecast`
  - Keep `analyze_laundry_with_bedrock()` parameter name as `weather_data` (it receives internal format)
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 6. Update test cases in main block
  - Update valid test event to use `weather_forecast` key with Home Assistant structure
  - Add `current_time` field to valid test event matching first forecast datetime
  - Update test event to include weather entity (e.g., `weather.forecast_home`)
  - Update test event to include forecast array with at least 2 hourly entries
  - Include datetime field in each forecast entry
  - Update missing field test to check for missing `weather_forecast` instead of `weather_data`
  - Add new test case for missing `current_time` field
  - Add new test case for invalid `current_time` format
  - Update test case for missing next_hour to test insufficient forecast entries
  - Update path traversal test cases to include `current_time` and `weather_forecast`
  - Update test output descriptions to reference `weather_forecast` and `current_time`
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 7. Update related documentation files
  - Update `.kiro/specs/laundry-monitoring-agent/design.md` event schema to show `weather_forecast` and `current_time`
  - Update `.kiro/specs/laundry-monitoring-agent/tasks.md` to reference `weather_forecast` validation
  - Update any inline documentation or README files that show example event structures
  - Update deployment documentation if it includes Lambda event examples
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 8. Verify internal data structure compatibility
  - Verify `format_weather_data_for_prompt()` still receives correct structure
  - Verify weather validation functions work with extracted data
  - Verify Bedrock agent receives properly formatted weather description
  - Run end-to-end test to confirm weather analysis logic unchanged
  - _Requirements: 7.1, 7.2, 7.3, 7.4_
