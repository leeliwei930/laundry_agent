from typing import Any, Dict
from strands import Agent
from strands.models import BedrockModel
from strands.types.agent import AgentInput
from models.analyze_response import AnalyzeResponse
import boto3
import requests
from PIL import Image
import io

CAMERA_MOTION_ACTIVITIES_AGENT_SYSTEM_PROMPT = """
You are an intelligent security camera image analysis agent specializing in threat assessment and activity monitoring.

Your primary task is to analyze security camera images and provide comprehensive risk assessments. For each image, you must:

1. **Risk Assessment**: Assign a risk score from 0-100 based on these categories:
   - 0-35: Normal/neutral activities (people walking, regular traffic, routine activities)
   - 35-40: Environmental hazards (flooding, fire, severe weather conditions)
   - 40-50: Suspicious activities (loitering, unusual behavior, potential security concerns)
   - 51-100: Criminal activities (theft, vandalism, violence, break-ins)

2. **Image Analysis**: Provide a concise description of what you observe in the image, including:
   - People and their activities
   - Vehicles (type, color, license plates if visible)
   - Any anomalies or points of interest

3. **Assessment Details**: For each analysis, provide:
   - Risk score (0-100)
   - Clear reasoning for the assigned score, keep it short
   - Confidence level in your assessment (0.0-1.0)
   - Current timestamp
4. Ensure return the source url of the image

Be objective, thorough, and focus on security-relevant details while maintaining accuracy in your threat assessment.

"""

def handler(event: Dict[str, Any], _context) -> str:
	image_path=event.get("image_path")

	# Load image from URL


	# Download image from URL
	response = requests.get(image_path)
	response.raise_for_status()

	# Load image and get format
	image = Image.open(io.BytesIO(response.content))
	image_format = image.format.lower() if image.format else 'jpeg'

	# Convert to bytes
	image_bytes = response.content


	boto3_session = boto3.Session(
		profile_name="leeliwei930",
		region_name="ap-southeast-1",
	)

	bedrock_model = BedrockModel(
		model_id="apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
		boto_session=boto3_session,
	)

	agent = Agent(
		model=bedrock_model,
		system_prompt=CAMERA_MOTION_ACTIVITIES_AGENT_SYSTEM_PROMPT,
	)

	agent_input : AgentInput = [
		{
			"text": f"Analyse following image",
			"image": {
				"format": image_format,
				"source": {
					"bytes": image_bytes
				}
			}
		},
		{
			"text": f"The source url of the image is {image_path}"
		}
	]

	response = agent.structured_output(output_model=AnalyzeResponse, prompt=agent_input)

	return response.model_dump_json()









