from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import time
import requests
import base64
import json
import boto3
from botocore.client import Config

app = FastAPI()

class ImageRequest(BaseModel):
    prompt: str

def get_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing environment variable: {name}")
    return value

@app.post("/generate-image")
async def generate_image(request: ImageRequest):
    try:
        # Get environment variables
        flux_api_key = get_env_var("FLUX_API_KEY")
        r2_access_key_id = get_env_var("R2_ACCESS_KEY_ID")
        r2_secret_access_key = get_env_var("R2_SECRET_ACCESS_KEY")
        r2_endpoint_url = get_env_var("R2_ENDPOINT_URL")
        r2_bucket_name = get_env_var("R2_BUCKET_NAME")
        r2_public_domain = get_env_var("R2_PUBLIC_DOMAIN")

        # Configure headers for Flux API
        headers = {
            'accept': 'application/json',
            'authorization': f'Bearer {flux_api_key}',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        }

        # Prepare multipart form data with dynamic prompt
        files = {
            'prompt': (None, request.prompt),
            'model': (None, 'flux_1_schnell'),
            'size': (None, '16_9'),
            'lora': (None, ''),
            'style': (None, 'no_style'),
            'color': (None, ''),
            'lighting': (None, ''),
            'composition': (None, ''),
        }

        # Call Flux API
        response = requests.post(
            'https://api.freeflux.ai/v1/images/generate',
            headers=headers,
            files=files
        )
        response.raise_for_status()

        # Process image response
        result = response.json().get('result')
        if not result or not result.startswith("data:image/png;base64,"):
            raise HTTPException(status_code=500, detail="Invalid image response from Flux API")

        # Decode and upload to R2
        base64_data = result.split(",")[1]
        image_bytes = base64.b64decode(base64_data)
        
        s3 = boto3.client(
            's3',
            endpoint_url=r2_endpoint_url,
            aws_access_key_id=r2_access_key_id,
            aws_secret_access_key=r2_secret_access_key,
            config=Config(signature_version='s3v4')
        )

        filename = f"generated_{int(time.time())}.png"
        s3.put_object(
            Bucket=r2_bucket_name,
            Key=filename,
            Body=image_bytes,
            ContentType='image/png'
        )

        return {"image_url": f"https://{r2_public_domain}/{filename}"}

    except requests.exceptions.HTTPError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Flux API error: {str(e)}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid JSON response from Flux API")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")
