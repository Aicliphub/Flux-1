import os
import time
import requests
import base64
import json
import boto3
from botocore.client import Config
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration from environment
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_PUBLIC_DOMAIN = os.getenv("R2_PUBLIC_DOMAIN")
FLUX_API_KEY = os.getenv("FLUX_API_KEY")

def get_s3_client():
    """Initialize S3 client with runtime environment validation"""
    required_vars = [
        R2_ACCESS_KEY_ID, 
        R2_SECRET_ACCESS_KEY,
        R2_ENDPOINT_URL,
        R2_BUCKET_NAME,
        R2_PUBLIC_DOMAIN
    ]
    
    if any(var is None for var in required_vars):
        raise HTTPException(
            status_code=500,
            detail="Missing Cloudflare R2 configuration in environment variables"
        )
    
    return boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version='s3v4')
    )

class ImageRequest(BaseModel):
    prompt: str

@app.post("/generate-image")
async def generate_image(request: ImageRequest):
    start_time = time.time()
    
    try:
        # Call Flux API
        files = {
            'prompt': (None, request.prompt),
            'model': (None, 'flux_1_schnell'),
            'size': (None, '16_9'),
            'lora': (None, ''),
            'style': (None, 'no_style'),
        }

        headers = {
            'accept': 'application/json',
            'authorization': f'Bearer {FLUX_API_KEY}',
        }

        response = requests.post(
            'https://api.freeflux.ai/v1/images/generate',
            headers=headers,
            files=files
        )

        response.raise_for_status()

        # Process image response
        response_json = response.json()
        image_data_url = response_json.get('result')

        if not image_data_url or not image_data_url.startswith("data:image/png;base64,"):
            raise HTTPException(status_code=500, detail="Invalid image data from API")

        base64_image_data = image_data_url.split(",", 1)[1]
        image_bytes = base64.b64decode(base64_image_data)
        
        # Upload to R2
        timestamp = int(time.time())
        object_name = f"generated_image_{timestamp}.png"
        
        client = get_s3_client()
        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=object_name,
            Body=image_bytes,
            ContentType='image/png'
        )
        
        # Generate public URL
        image_url = f"https://{R2_PUBLIC_DOMAIN}/{object_name}"
        
        return {"image_url": image_url}

    except requests.HTTPError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        print(f"Request processed in {time.time() - start_time:.2f} seconds")
