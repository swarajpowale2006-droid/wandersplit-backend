import os
import json
import re
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

def parse_receipt_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing from your .env file.")

    client = genai.Client(api_key=api_key)

    prompt = """
    Analyze this expense receipt image.
    Extract the following information accurately into a JSON object:
    - vendor_name (string): Name of the restaurant, hotel, or merchant
    - location (string): Address or city if visible
    - category (string): Choose from "Food & Dining", "Hotels & Stays", "Travel & Local Transport", "Activities & Experiences"
    - date (string): Extracted date
    - sub_total (float): Total before tax
    - tax_and_service_charge (float): Taxes/service charge
    - grand_total (float): Final payable amount
    - currency (string): "INR"
    - items (list): Array of objects with "name", "quantity", "rate", and "amount"

    Return ONLY raw valid JSON without markdown formatting or backticks.
    """

    # Exact models active on your project
    models_to_try = [
        "gemini-3-flash-preview",
        "gemini-2.5-flash-lite",
        "gemini-3.7-flash"
    ]
    
    last_error = None

    for model_name in models_to_try:
        try:
            print(f"--> Attempting OCR with model: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=mime_type,
                    ),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            
            raw_text = response.text.strip()
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return json.loads(raw_text)

        except Exception as e:
            print(f"Model {model_name} failed with error: {e}")
            last_error = e
            continue

    raise RuntimeError(f"OCR failed across models: {last_error}")