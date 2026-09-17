import random
import string
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from db import supabase
from settlement import compute_settlements
from recommendations import generate_booking_recommendations
from fastapi import FastAPI, HTTPException, UploadFile, File
from ocr_service import parse_receipt_image

app = FastAPI(title="WanderSplit API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. TRIP ONBOARDING
class CreateTripRequest(BaseModel):
    title: str
    destination: str
    budget: float
    organizer_name: str
    organizer_upi: str

@app.post("/api/trips")
def create_trip(payload: CreateTripRequest):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    trip_res = supabase.table("trips").insert({
        "title": payload.title,
        "destination": payload.destination,
        "budget": payload.budget,
        "invite_code": code
    }).execute()

    if not trip_res.data:
        raise HTTPException(status_code=500, detail="Failed to initialize trip.")

    trip_id = trip_res.data[0]["id"]
    member_res = supabase.table("trip_members").insert({
        "trip_id": trip_id,
        "name": payload.organizer_name,
        "upi_id": payload.organizer_upi,
        "role": "organizer"
    }).execute()

    return {
        "trip_id": trip_id,
        "invite_code": code,
        "organizer_member_id": member_res.data[0]["id"]
    }

class JoinTripRequest(BaseModel):
    invite_code: str
    name: str
    upi_id: str

@app.post("/api/trips/join")
def join_trip(payload: JoinTripRequest):
    trip = supabase.table("trips").select("id").eq("invite_code", payload.invite_code.strip().upper()).execute()
    if not trip.data:
        raise HTTPException(status_code=404, detail="Invalid invite code.")

    trip_id = trip.data[0]["id"]
    member_res = supabase.table("trip_members").insert({
        "trip_id": trip_id,
        "name": payload.name,
        "upi_id": payload.upi_id,
        "role": "member"
    }).execute()

    return {"status": "joined", "trip_id": trip_id, "member_id": member_res.data[0]["id"]}

@app.get("/api/trips/{trip_id}/members")
def get_trip_members(trip_id: str):
    members = supabase.table("trip_members").select("id, name, upi_id, role").eq("trip_id", trip_id).execute().data or []
    return {"members": members}

# 2. MANUAL EXPENSE ENTRY
class SplitAllocation(BaseModel):
    member_id: str
    amount: Optional[float] = None

class AddManualExpenseRequest(BaseModel):
    trip_id: str
    title: str
    category: str
    sub_category: Optional[str] = None
    booking_reference: Optional[str] = None
    day_number: Optional[int] = 1
    total_amount: float
    paid_by_member_id: str
    split_type: str
    participating_members: List[SplitAllocation]

@app.post("/api/expenses/manual")
def add_manual_expense(payload: AddManualExpenseRequest):
    if payload.total_amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
    if not payload.participating_members:
        raise HTTPException(status_code=400, detail="At least one participant required.")

    item_res = supabase.table("itinerary_items").insert({
        "trip_id": payload.trip_id,
        "title": payload.title,
        "category": payload.category,
        "sub_category": payload.sub_category,
        "booking_reference": payload.booking_reference,
        "day_number": payload.day_number,
        "total_cost": payload.total_amount,
        "paid_by_member_id": payload.paid_by_member_id,
        "split_type": payload.split_type
    }).execute()

    if not item_res.data:
        raise HTTPException(status_code=500, detail="Failed to save expense.")

    item_id = item_res.data[0]["id"]
    split_rows = []

    if payload.split_type == "equal":
        share = round(payload.total_amount / len(payload.participating_members), 2)
        for p in payload.participating_members:
            split_rows.append({"item_id": item_id, "member_id": p.member_id, "owed_amount": share})
    elif payload.split_type == "exact":
        total_check = sum([p.amount or 0.0 for p in payload.participating_members])
        if round(total_check, 2) != round(payload.total_amount, 2):
            raise HTTPException(status_code=400, detail="Splits sum does not match total amount.")
        for p in payload.participating_members:
            split_rows.append({"item_id": item_id, "member_id": p.member_id, "owed_amount": p.amount})

    supabase.table("item_splits").insert(split_rows).execute()
    return {"status": "SUCCESS", "item_id": item_id}

# 3. SETTLEMENT CALCULATION
@app.get("/api/trips/{trip_id}/settlement")
def get_trip_settlement(trip_id: str):
    members = supabase.table("trip_members").select("id, name, upi_id").eq("trip_id", trip_id).execute().data or []
    items = supabase.table("itinerary_items").select("id, paid_by_member_id").eq("trip_id", trip_id).execute().data or []

    expenses_with_splits = []
    for item in items:
        splits = supabase.table("item_splits").select("member_id, owed_amount").eq("item_id", item["id"]).execute().data or []
        expenses_with_splits.append({
            "paid_by_member_id": item["paid_by_member_id"],
            "splits": splits
        })

    refund_txs = supabase.table("refund_transactions").select("id, recipient_member_id").eq("trip_id", trip_id).execute().data or []
    refunds_with_splits = []
    for ref in refund_txs:
        splits = supabase.table("refund_splits").select("member_id, credited_amount").eq("refund_id", ref["id"]).execute().data or []
        refunds_with_splits.append({
            "recipient_member_id": ref["recipient_member_id"],
            "splits": splits
        })

    return compute_settlements(members, expenses_with_splits, refunds_with_splits) # 4. REFUNDS & CANCELLATION LEDGER
class RefundBeneficiary(BaseModel):
    member_id: str
    credited_amount: float

class RecordRefundRequest(BaseModel):
    trip_id: str
    original_item_id: Optional[str] = None
    recipient_member_id: str
    total_refund_amount: float
    reason: Optional[str] = "Cancellation / Vendor Refund"
    beneficiaries: List[RefundBeneficiary]

@app.post("/api/refunds")
def record_refund(payload: RecordRefundRequest):
    if payload.total_refund_amount <= 0:
        raise HTTPException(status_code=400, detail="Refund amount must be positive.")
    if not payload.beneficiaries:
        raise HTTPException(status_code=400, detail="At least one beneficiary required.")

    # Validate that split amounts equal the total refund received
    total_distributed = sum([b.credited_amount for b in payload.beneficiaries])
    if round(total_distributed, 2) != round(payload.total_refund_amount, 2):
        raise HTTPException(
            status_code=400, 
            detail=f"Beneficiary distribution sum ({total_distributed}) does not match total refund ({payload.total_refund_amount})."
        )

    # 1. Insert header transaction
    refund_res = supabase.table("refund_transactions").insert({
        "trip_id": payload.trip_id,
        "original_item_id": payload.original_item_id,
        "recipient_member_id": payload.recipient_member_id,
        "amount": payload.total_refund_amount,
        "reason": payload.reason
    }).execute()

    if not refund_res.data:
        raise HTTPException(status_code=500, detail="Failed to log refund transaction.")

    refund_id = refund_res.data[0]["id"]

    # 2. Insert individual splits
    refund_splits = [
        {
            "refund_id": refund_id,
            "member_id": b.member_id,
            "credited_amount": b.credited_amount
        }
        for b in payload.beneficiaries
    ]

    supabase.table("refund_splits").insert(refund_splits).execute()

    return {
        "status": "SUCCESS",
        "refund_id": refund_id,
        "message": f"Successfully credited refund of ₹{payload.total_refund_amount}"
    }
# 5. AI BOOKING RECOMMENDATIONS
@app.get("/api/trips/{trip_id}/recommendations")
def get_trip_recommendations(trip_id: str):
    # 1. Fetch trip metadata
    trip_res = supabase.table("trips").select("destination, budget").eq("id", trip_id).execute()
    if not trip_res.data:
        raise HTTPException(status_code=404, detail="Trip not found.")
    trip = trip_res.data[0]
    
    # 2. Count members
    members = supabase.table("trip_members").select("id").eq("trip_id", trip_id).execute().data or []
    
    # 3. Sum current expenses and gather booked categories
    items = supabase.table("itinerary_items").select("total_cost, category").eq("trip_id", trip_id).execute().data or []
    total_spent = sum([float(item.get("total_cost", 0)) for item in items])
    categories = list(set([item.get("category") for item in items if item.get("category")]))
    
    # 4. Generate AI recommendations
    return generate_booking_recommendations(
        destination=trip.get("destination", "India"),
        total_budget=float(trip.get("budget", 0)),
        spent_so_far=total_spent,
        member_count=max(len(members), 1),
        booked_categories=categories
    )
# 6. OCR RECEIPT & TICKET SCANNER
@app.post("/api/expenses/scan")
async def scan_expense_receipt(file: UploadFile = File(...)):
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/heic"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Please upload a JPEG, PNG, or WEBP image."
        )

    try:
        contents = await file.read()
        extracted_data = parse_receipt_image(image_bytes=contents, mime_type=file.content_type)
        return {
            "status": "SUCCESS",
            "extracted_data": extracted_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scan document: {str(e)}")
