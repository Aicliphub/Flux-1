import os
import time
import base64
import json
import boto3
import requests
from botocore.client import Config
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize R2 client at startup
@app.on_event("startup")
async def startup_event():
    global s3_client
    s3_client = boto3.client(
        's3',
        endpoint_url=os.environ['R2_ENDPOINT_URL'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        config=Config(signature_version='s3v4')
    )

def generate_image(prompt: str):
    headers = {
        'accept': 'application/json',
        'authorization': f'Bearer {os.environ["FLUX_API_KEY"]}',
    }

    files = {
        'prompt': (None, prompt),
        'model': (None, 'flux_1_schnell'),
        'size': (None, '16_9'),
        'lora': (None, ''),
        'style': (None, 'no_style'),
    }

    response = requests.post(
        'https://api.freeflux.ai/v1/images/generate',
        headers=headers,
        files=files
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail="Image generation failed"
        )

    try:
        response_json = response.json()
        image_data_url = response_json.get('result')
        
        if not image_data_url or not image_data_url.startswith("data:image/png;base64,"):
            raise HTTPException(
                status_code=500,
                detail="Invalid image data response"
            )

        return image_data_url.split(",")[1]
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Invalid API response format"
        )

def upload_to_r2(image_data: str) -> str:
    try:
        image_bytes = base64.b64decode(image_data)
        timestamp = int(time.time())
        object_name = f"generated_image_{timestamp}.png"
        
        s3_client.put_object(
            Bucket=os.environ['R2_BUCKET_NAME'],
            Key=object_name,
            Body=image_bytes,
            ContentType='image/png'
        )
        
        return f"https://{os.environ['R2_PUBLIC_DOMAIN']}/{object_name}"
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"R2 upload failed: {str(e)}"
        )

@app.post("/generate")
async def generate_endpoint(payload: dict):
    try:
        prompt = payload.get("prompt")
        if not prompt:
            raise HTTPException(
                status_code=400,
                detail="Prompt is required"
            )

        base64_image = generate_image(prompt)
        image_url = upload_to_r2(base64_image)
        
        return {"image_url": image_url}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )
