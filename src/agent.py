import json
from typing import Any, Dict
from botocore.config import Config as BotocoreConfig
from strands import Agent
from strands.models import BedrockModel
from strands.types.agent import AgentInput
from models.analyze_response import AnalyzeResponse
import boto3
from PIL import Image
import io
import logging
import os


APPLICATION_INFERENCE_PROFILE_ARN = os.environ.get("APPLICATION_INFERENCE_PROFILE_ARN", "arn:aws:bedrock:ap-southeast-1:096778346036:application-inference-profile/m2yc3f0mbts3")
APP_DEBUG = os.environ.get("APP_DEBUG", "DEBUG")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")

# Configure the root strands logger
l = logging.getLogger("strands")
# Get log level from environment variable, default to DEBUG if not set
log_level_name = APP_DEBUG
log_level = getattr(logging, log_level_name, logging.DEBUG)
l.setLevel(log_level)

# Add a handler to see the logs
logging.basicConfig(
    format="%(levelname)s | %(name)s | %(message)s", 
    handlers=[logging.StreamHandler()]
)

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


def custom_callback_handler(**kwargs):
    l.info(f"Agent event: {kwargs}")
    # Process stream data
    if "data" in kwargs:
        l.info(f"Agent event: {kwargs['data']}")
    elif "current_tool_use" in kwargs and kwargs["current_tool_use"].get("name"):
        l.info(f"\nUSING TOOL: {kwargs['current_tool_use']['name']}")

def handler(event: Dict[str, Any], _context) -> Dict[str, Any]:
    l.info(f"Using application inference profile ARN: {APPLICATION_INFERENCE_PROFILE_ARN}")
    file_key = event.get("file_key")

    # Create S3 client for R2
    s3_client = boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )

    # Download image from R2
    response = s3_client.get_object(Bucket=R2_BUCKET_NAME, Key=file_key)
    image_bytes = response['Body'].read()

    # Load image and get format
    image = Image.open(io.BytesIO(image_bytes))
    image_format = image.format.lower() if image.format else 'jpeg'

    # Generate presigned URL with 300 seconds expiration
    presigned_url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': R2_BUCKET_NAME, 'Key': file_key},
        ExpiresIn=300
    )

    boto3_session = boto3.Session(
        region_name="ap-southeast-1",
    )

    bedrock_model = BedrockModel(
        model_id=APPLICATION_INFERENCE_PROFILE_ARN,
        boto_session=boto3_session,
        boto_client_config=BotocoreConfig(
            connect_timeout=10,
            read_timeout=60,
        ),
    )

    agent = Agent(
        model=bedrock_model,
        system_prompt=CAMERA_MOTION_ACTIVITIES_AGENT_SYSTEM_PROMPT,
        callback_handler=custom_callback_handler,
    )

    agent_input: AgentInput = [
        {
            "text": "Analyse following image",
            "image": {
                "format": image_format,
                "source": {
                    "bytes": image_bytes
                }
            }
        },
        {
            "text": f"The source url of the image is {presigned_url}"
        }
    ]
    
    
    try:
        l.info(f"Analysing image from file key: {file_key}")
        result = agent.structured_output(output_model=AnalyzeResponse, prompt=agent_input)
        return {
            "data": {
                "result": result.model_dump(),
            }
        }
    except Exception as e:
        l.error(f"Error analysing image: {e}")
        return {
            "errors": [
                {
                    "message": "Error analysing image",
                    "details": str(e)
                }
            ] 
        }
    


if __name__ == "__main__":
    result = handler({
        "file_key": "camera_snapshot/20251008/180629_screenshot.jpg"
    }, None)
    print(json.dumps(result, indent=4))
