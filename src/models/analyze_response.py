from pydantic import BaseModel, Field

class AnalyzeResponse(BaseModel):
    risk_score: int = Field(description="""
	The score rating for the activity, between 0 and 100.
	""")
    reason: str = Field( description="The reason for the score")
    confidence: float = Field(description="The confidence of the score")
    timestamp: str = Field(description="The timestamp of the activity")
    image_url: str = Field(description="The presigned URL (300s expiration) of the analyzed image from R2 storage")
    image_description: str = Field(description="The description of the image, if there is nothing to describe, return 'No description', describe within 25 words")

class LocalisedAnalyseResponse(BaseModel):
    en: AnalyzeResponse = Field(description="English localization of the analysis output")
    zh_CN: AnalyzeResponse = Field(description="Chinese (Simplified) localization of the analysis output")

