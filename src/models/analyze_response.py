from pydantic import BaseModel, Field


class AnalyzeResponse(BaseModel):
    risk_score: int = Field(description="""
	The score rating for the activity, between 0 and 100.
	""")
    reason: str = Field( description="The reason for the score")
    confidence: float = Field(description="The confidence of the score")
    timestamp: str = Field(description="The timestamp of the activity")
    image_url: str = Field(description="The source url of the image that you analyse, return the url from the input")
    image_description: str = Field(description="The description of the image, if there is nothing to describe, return 'No description', describe within 25 words")
