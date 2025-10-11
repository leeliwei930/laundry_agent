"""
Pydantic models for laundry monitoring agent structured output.

These models define the response schema for the laundry monitoring agent,
ensuring structured and validated JSON output with multi-language support.
"""

from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Literal


class LaundryAnalysisResponse(BaseModel):
    """
    Single language analysis response for laundry monitoring.
    
    This model defines all required fields for the analysis result,
    including laundry detection, weather risk assessment, and recommendations.
    Addresses Requirements 4.2-4.8 and 5.1-5.2.
    """
    
    laundry_detected: bool = Field(
        description=(
            "Whether laundry racks were detected in the image (Requirement 4.2). "
            "Set to true if any laundry racks or hanging laundry items are visible "
            "in open air areas. Set to false if no laundry is detected."
        )
    )
    
    laundry_description: str = Field(
        description=(
            "Description of detected laundry items and location (Requirement 4.3). "
            "Include specific location within the image (e.g., 'left side of porch', "
            "'center area', 'near gate', 'right side by the wall'). "
            "Describe item types (e.g., 'clothes', 'bedsheets', 'towels') and "
            "quantity (e.g., 'several items', 'full rack', 'a few pieces'). "
            "Note colors or distinctive features when visible. "
            "If no laundry detected, return 'No laundry detected' (Requirement 1.4)."
        )
    )
    
    weather_risk_level: Literal["low", "medium", "high"] = Field(
        description=(
            "Risk level based on weather conditions (Requirement 4.4). "
            "Use 'low' for clear conditions with no rain forecast and moderate wind. "
            "Use 'medium' for cloudy conditions, low precipitation probability (<30%), "
            "high wind (>20 km/h), or significant temperature drops. "
            "Use 'high' for rain forecast, high precipitation probability (≥30%), "
            "storms, or strong winds (>40 km/h)."
        )
    )
    
    weather_summary: str = Field(
        description=(
            "Brief summary of weather conditions and risks (max 50 words). "
            "Include current and upcoming conditions, temperature changes, "
            "precipitation probability, and wind speed. "
            "Explain how these factors affect laundry drying and safety."
        ),
        max_length=300
    )
    
    recommendation: Literal["bring_inside", "leave_outside", "no_action"] = Field(
        description=(
            "Action recommendation (Requirement 4.5). "
            "Use 'bring_inside' when laundry is detected and weather poses risk "
            "(rain forecast, strong winds, or adverse conditions). "
            "Use 'leave_outside' when laundry is detected and weather is safe "
            "(clear conditions, no rain, moderate wind). "
            "Use 'no_action' when no laundry is detected."
        )
    )
    
    recommendation_reason: str = Field(
        description=(
            "Explanation for the recommendation (max 100 words). "
            "Reference specific weather factors (rain, wind, temperature) and "
            "risk assessment. Explain why the action is necessary or safe. "
            "For 'bring_inside', emphasize urgency and specific risks. "
            "For 'leave_outside', confirm safe conditions. "
            "For 'no_action', state that no laundry was detected."
        ),
        max_length=600
    )
    
    confidence: float = Field(
        description=(
            "Confidence score for the analysis (0.0-1.0) (Requirements 3.6, 4.6). "
            "Use lower confidence (<0.5) for poor image quality, obstructed views, "
            "poor lighting (too dark or overexposed), low resolution, blurry images, "
            "or adverse weather in the image (fog, heavy rain). "
            "Use higher confidence (≥0.7) for clear, well-lit images with good visibility. "
            "Use medium confidence (0.5-0.7) for acceptable but not ideal conditions."
        ),
        ge=0.0,
        le=1.0
    )
    
    timestamp: str = Field(
        description=(
            "ISO 8601 timestamp of analysis (Requirement 4.7). "
            "Format: YYYY-MM-DDTHH:MM:SS.sssZ or YYYY-MM-DDTHH:MM:SS.sss+HH:MM. "
            "Example: 2025-11-10T14:30:00.000Z"
        )
    )
    
    image_url: str = Field(
        description=(
            "Presigned URL of the analyzed image (Requirement 4.8). "
            "This URL has a 7-day expiration and provides access to the source image. "
            "The URL should be a valid HTTPS URL pointing to the R2 storage."
        )
    )
    
    @field_validator('confidence')
    @classmethod
    def validate_confidence_range(cls, v: float) -> float:
        """
        Validate that confidence score is within 0.0-1.0 range.
        
        Args:
            v: Confidence score value
            
        Returns:
            Validated confidence score
            
        Raises:
            ValueError: If confidence is outside valid range
        """
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Confidence score must be between 0.0 and 1.0, got {v}")
        return v
    
    @field_validator('timestamp')
    @classmethod
    def validate_iso8601_timestamp(cls, v: str) -> str:
        """
        Validate that timestamp is in ISO 8601 format.
        
        Args:
            v: Timestamp string
            
        Returns:
            Validated timestamp string
            
        Raises:
            ValueError: If timestamp is not valid ISO 8601 format
        """
        # Check for required 'T' separator between date and time
        if 'T' not in v:
            raise ValueError(
                f"Timestamp must be in ISO 8601 format with 'T' separator "
                f"(e.g., '2025-11-10T14:30:00.000Z'), got '{v}'"
            )
        
        try:
            # Try parsing with timezone
            datetime.fromisoformat(v.replace('Z', '+00:00'))
        except (ValueError, AttributeError) as e:
            raise ValueError(
                f"Timestamp must be in ISO 8601 format "
                f"(e.g., '2025-11-10T14:30:00.000Z'), got '{v}': {str(e)}"
            )
        return v


class LocalizedLaundryAnalysisResponse(BaseModel):
    """
    Multi-language response wrapper for laundry monitoring analysis.
    
    This model provides the complete analysis in both English and Simplified Chinese,
    ensuring all household members can understand the recommendations.
    Addresses Requirement 5 (Multi-Language Support).
    """
    
    en: LaundryAnalysisResponse = Field(
        description=(
            "English localization of the analysis (Requirement 5.1). "
            "All fields should be in English with clear, natural language."
        )
    )
    
    zh_CN: LaundryAnalysisResponse = Field(
        description=(
            "Simplified Chinese localization of the analysis (Requirement 5.2). "
            "All text fields must be translated to Simplified Chinese while "
            "maintaining consistent meaning with the English version (Requirement 5.4). "
            "For technical terms that cannot be translated, use the original term "
            "with an explanation in Chinese (Requirement 5.5)."
        )
    )
    
    class Config:
        """Pydantic model configuration."""
        json_schema_extra = {
            "example": {
                "en": {
                    "laundry_detected": True,
                    "laundry_description": "Several clothes hanging on rack in center of porch",
                    "weather_risk_level": "high",
                    "weather_summary": "Rain forecast in next hour with 80% probability. Wind speed 25 km/h.",
                    "recommendation": "bring_inside",
                    "recommendation_reason": "High risk of laundry getting wet due to imminent rain. Bring inside immediately.",
                    "confidence": 0.85,
                    "timestamp": "2025-11-10T14:30:00.000Z",
                    "image_url": "https://example.r2.cloudflarestorage.com/..."
                },
                "zh_CN": {
                    "laundry_detected": True,
                    "laundry_description": "门廊中央的晾衣架上挂着几件衣服",
                    "weather_risk_level": "high",
                    "weather_summary": "下一小时有雨，降雨概率80%。风速25公里/小时。",
                    "recommendation": "bring_inside",
                    "recommendation_reason": "即将下雨，衣物被淋湿的风险很高。请立即收回室内。",
                    "confidence": 0.85,
                    "timestamp": "2025-11-10T14:30:00.000Z",
                    "image_url": "https://example.r2.cloudflarestorage.com/..."
                }
            }
        }
