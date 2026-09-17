import os
import json
from typing import List
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel
from google import genai
from google.genai import types

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

# Pydantic schemas for the structured AI recommendation response
class PlaceOption(BaseModel):
    name: str
    type: str  # e.g. Resort, Cafe, Scooter Rental, Water Sports
    area: str  # e.g. Anjuna, Calangute, Panjim
    approx_price_inr: float
    rating: str  # e.g. "4.4/5"
    booking_platform: str  # e.g. Booking.com, MakeMyTrip, Zomato, Direct
    why_recommended: str

class CategoryBudgetBreakdown(BaseModel):
    category: str
    allocated_budget_inr: float
    recommendations: List[PlaceOption]

class TravelPlanResponse(BaseModel):
    destination_insights: str
    budget_health: str
    total_budget_inr: float
    remaining_budget_inr: float
    budget_breakdown: List[CategoryBudgetBreakdown]
    money_saving_tips: List[str]

def generate_booking_recommendations(
    destination: str, 
    total_budget: float, 
    spent_so_far: float, 
    member_count: int, 
    booked_categories: list
) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing from your .env file.")

    client = genai.Client(api_key=api_key)
    remaining_budget = max(0.0, float(total_budget) - float(spent_so_far))
    
    prompt = f"""
    You are an expert travel concierge and booking optimizer for trips in India.
    
    Trip Details:
    - Destination: {destination}
    - Total Budget: INR {total_budget}
    - Spent so far: INR {spent_so_far}
    - Remaining Budget to allocate: INR {remaining_budget}
    - Number of Travelers: {member_count}
    - Already Booked Categories: {', '.join(booked_categories) if booked_categories else 'None'}
    
    Task:
    1. Distribute the remaining INR {remaining_budget} across four categories:
       - "Hotels & Stays"
       - "Dining & Food"
       - "Activities & Sightseeing"
       - "Travel & Local Transport"
    2. For each category, provide 2 to 3 real, top-rated places/options in {destination} that fit within that category's allocated budget.
    3. Include accurate estimated price in INR, real rating, specific neighborhood/beach/area, and the primary booking platform (e.g. Booking.com, Zomato, GoaMiles, Direct).
    4. Provide actionable money-saving advice for {destination}.
    """

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TravelPlanResponse,
            temperature=0.2
        )
    )

    return json.loads(response.text)