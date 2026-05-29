import os
import uuid
import random
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
import httpx

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("securebank")

app = FastAPI(title="SecureBank Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Environment
# ──────────────────────────────────────────────
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID", "")
GOOGLE_LOCATION = os.getenv("GOOGLE_LOCATION", "us")
DOCUMENT_AI_PROCESSOR_ID = os.getenv("DOCUMENT_AI_PROCESSOR_ID", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
BANK_API_BASE = os.getenv("BANK_API_BASE", "http://localhost:9090")
CRM_API_BASE = os.getenv("CRM_API_BASE", "http://localhost:9091")

# ──────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────
class ApplicationRequest(BaseModel):
    product: str = "banking"
    customer_name: Optional[str] = ""

class ApplicationResponse(BaseModel):
    reference: str
    status: str
    message: str

class ContactRequest(BaseModel):
    reason: str = "general"

class ContactResponse(BaseModel):
    email: str
    phone: str
    hours: str
    reason: str

class ManagerCheckResponse(BaseModel):
    available: bool
    message: str
    estimated_wait_minutes: int = 0

class FeedbackRequest(BaseModel):
    customer_name: str = "Valued Customer"
    phone_number: str = ""
    reason: str = "general feedback"

class FeedbackResponse(BaseModel):
    callback_id: str
    scheduled_time: str
    message: str
    phone_number: str
    reason: str

class InvoiceAnalysisResponse(BaseModel):
    total: float
    currency: str
    formatted: str
    vendor: str
    confidence: float
    items: list = []
    message: str

class TwilioVoiceRequest(BaseModel):
    CallSid: str = ""
    From: str = ""
    To: str = ""
    SpeechResult: str = ""

# ──────────────────────────────────────────────
# Mock DB (replace with real DB in production)
# ──────────────────────────────────────────────
applications_db: dict = {}
feedbacks_db: dict = {}

# ──────────────────────────────────────────────
# HEALTH
# ──────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "securebank-backend", "timestamp": datetime.now(timezone.utc).isoformat()}

# ──────────────────────────────────────────────
# TOOL 1 — Create Application Reference
# ──────────────────────────────────────────────
@app.post("/tools/create-application", response_model=ApplicationResponse)
async def create_application(req: ApplicationRequest):
    ref = "APP-" + uuid.uuid4().hex[:8].upper()
    record = {
        "reference": ref,
        "product": req.product,
        "customer_name": req.customer_name or "",
        "status": "Received",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    applications_db[ref] = record
    logger.info("Application created: %s", ref)
    return ApplicationResponse(
        reference=ref,
        status="Received",
        message=f"Your unique application reference is {ref}. Please save it to check your status later.",
    )

# ──────────────────────────────────────────────
# TOOL 2 — Get Application Status
# ──────────────────────────────────────────────
@app.get("/tools/application-status/{reference}")
async def get_application_status(reference: str):
    record = applications_db.get(reference)
    if not record:
        raise HTTPException(status_code=404, detail="Application reference not found")
    return record

# ──────────────────────────────────────────────
# TOOL 3 — Get Bank Contact
# ──────────────────────────────────────────────
@app.post("/tools/get-contact", response_model=ContactResponse)
async def get_contact(req: ContactRequest):
    return ContactResponse(
        email="support@securebank.com",
        phone="1-800-SECURE-BANK",
        hours="24/7 phone support; email responses within 24 hours",
        reason=req.reason,
    )

# ──────────────────────────────────────────────
# TOOL 4 — Check Manager Availability (real via CRM)
# ──────────────────────────────────────────────
@app.post("/tools/manager-check", response_model=ManagerCheckResponse)
async def manager_check():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{CRM_API_BASE}/managers/availability")
            data = resp.json()
            return ManagerCheckResponse(
                available=data.get("available", False),
                message=data.get("message", "Manager availability unknown"),
                estimated_wait_minutes=data.get("estimated_wait_minutes", 10),
            )
    except Exception as e:
        logger.warning("CRM unavailable, using fallback: %s", e)
        available = random.random() < 0.6
        return ManagerCheckResponse(
            available=available,
            message="Manager is available" if available else "Manager is currently attending to another customer",
            estimated_wait_minutes=0 if available else random.randint(5, 15),
        )

# ──────────────────────────────────────────────
# TOOL 5 — Schedule Feedback Call (real via CRM)
# ──────────────────────────────────────────────
@app.post("/tools/schedule-feedback", response_model=FeedbackResponse)
async def schedule_feedback(req: FeedbackRequest):
    callback_id = "CB-" + uuid.uuid4().hex[:6].upper()
    scheduled_time = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%I:%M %p")
    record = {
        "callback_id": callback_id,
        "customer_name": req.customer_name,
        "phone_number": req.phone_number,
        "reason": req.reason,
        "scheduled_time": scheduled_time,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    feedbacks_db[callback_id] = record
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{CRM_API_BASE}/callbacks", json=record)
    except Exception as e:
        logger.warning("CRM callback save failed: %s", e)
    logger.info("Feedback callback scheduled: %s", callback_id)
    return FeedbackResponse(
        callback_id=callback_id,
        scheduled_time=scheduled_time,
        message=f"A manager will call you back at {req.phone_number} around {scheduled_time}. Reference: {callback_id}",
        phone_number=req.phone_number,
        reason=req.reason,
    )

# ──────────────────────────────────────────────
# TOOL 6 — Analyze Invoice (Document AI)
# ──────────────────────────────────────────────
@app.post("/tools/analyze-invoice")
async def analyze_invoice(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are supported (JPEG, PNG)")

    image_bytes = await file.read()

    if DOCUMENT_AI_PROCESSOR_ID and GOOGLE_PROJECT_ID:
        try:
            from google.cloud import documentai_v1 as documentai
            from google.api_core.client_options import ClientOptions

            opts = ClientOptions(api_endpoint=f"{GOOGLE_LOCATION}-documentai.googleapis.com")
            client = documentai.DocumentProcessorServiceClient(client_options=opts)

            name = client.processor_path(GOOGLE_PROJECT_ID, GOOGLE_LOCATION, DOCUMENT_AI_PROCESSOR_ID)
            raw_doc = documentai.RawDocument(content=image_bytes, mime_type=file.content_type)
            request = documentai.ProcessRequest(name=name, raw_document=raw_doc)
            result = client.process_document(request=request)
            doc = result.document

            total = 0.0
            currency = "USD"
            vendor = ""
            items = []
            for entity in doc.entities:
                if entity.type_ == "invoice_amount" or entity.type_ == "total_amount":
                    total = float(entity.normalized_value.text) if entity.normalized_value.text else float(entity.mention_text.replace("$", "").replace(",", ""))
                elif entity.type_ == "supplier_name" or entity.type_ == "vendor_name":
                    vendor = entity.mention_text
                elif entity.type_ == "currency":
                    currency = entity.mention_text
                elif entity.type_ in ("line_item", "line_item / item"):
                    items.append({"description": entity.mention_text})

            if items:
                total = sum(
                    float(e.normalized_value.text) if e.normalized_value.text else 0.0
                    for e in doc.entities if e.type_ in ("line_item", "line_item / amount")
                )

            confidence = doc.text_anchor.content_confidence if hasattr(doc.text_anchor, "content_confidence") and doc.text_anchor else 0.95

            return InvoiceAnalysisResponse(
                total=total,
                currency=currency,
                formatted=f"{currency} {total:.2f}",
                vendor=vendor or "Extracted from invoice",
                items=items,
                confidence=float(confidence),
                message=f"The total amount on this invoice is {currency} {total:.2f}. Would you like to proceed with payment?",
            )

        except Exception as e:
            logger.error("Document AI processing failed: %s", e)
            raise HTTPException(status_code=500, detail=f"Document AI processing failed: {str(e)}")

    # Fallback mock
    sample_totals = [1250.00, 3499.50, 750.25, 5200.00, 189.99]
    total = random.choice(sample_totals)
    return InvoiceAnalysisResponse(
        total=total,
        currency="USD",
        formatted=f"USD {total:.2f}",
        vendor="Sample Vendor Inc.",
        items=[{"description": "Invoice items (mock)"}],
        confidence=round(random.uniform(0.85, 0.99), 2),
        message=f"The total amount on this invoice is USD {total:.2f}. Would you like to proceed with payment?",
    )

# ──────────────────────────────────────────────
# TOOL 7 — Process Invoice Payment
# ──────────────────────────────────────────────
class PaymentRequest(BaseModel):
    application_ref: str = ""
    invoice_total: float = 0.0
    currency: str = "USD"
    vendor: str = ""

class PaymentResponse(BaseModel):
    status: str
    transaction_id: str
    message: str

@app.post("/tools/process-payment", response_model=PaymentResponse)
async def process_payment(req: PaymentRequest):
    if not req.application_ref and not req.invoice_total:
        raise HTTPException(status_code=400, detail="Missing payment details")
    txn_id = "TXN-" + uuid.uuid4().hex[:10].upper()
    logger.info("Payment recorded: ref=%s total=%.2f txn=%s", req.application_ref or "N/A", req.invoice_total, txn_id)
    return PaymentResponse(
        status="pending_approval",
        transaction_id=txn_id,
        message=f"Payment of {req.currency} {req.invoice_total:.2f} is pending approval. "
                f"Please complete via mobile app. Transaction ID: {txn_id}",
    )

# ──────────────────────────────────────────────
# TWILIO — Incoming Voice Call Webhook
# ──────────────────────────────────────────────
@app.post("/twilio/voice/incoming")
async def twilio_incoming_voice(request: Request):
    form = await request.form()
    caller = form.get("From", "unknown")
    logger.info("Incoming call from: %s", caller)

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather input="speech dtmf" timeout="5" speechTimeout="auto"
            action="/twilio/voice/process-input" method="POST">
        <Say voice="Polly.Joanna">Hi, I'm Eva from SecureBank. Please tell me your name.</Say>
    </Gather>
    <Redirect>/twilio/voice/incoming</Redirect>
</Response>"""
    return Response(content=twiml, media_type="text/xml")

@app.post("/twilio/voice/process-input")
async def twilio_process_input(request: Request):
    form = await request.form()
    speech = form.get("SpeechResult", "").strip()
    dtmf = form.get("Digits", "").strip()
    caller = form.get("From", "unknown")
    input_text = speech or dtmf

    logger.info("Call input from %s: %s", caller, input_text)

    if not input_text:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather input="speech dtmf" timeout="5" speechTimeout="auto"
            action="/twilio/voice/process-input" method="POST">
        <Say voice="Polly.Joanna">I didn't catch that. Please tell me your name.</Say>
    </Gather>
</Response>"""
        return Response(content=twiml, media_type="text/xml")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Nice to meet you! I am routing you to our banking assistant.</Say>
    <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="text/xml")

# ──────────────────────────────────────────────
# TWILIO — Send SMS
# ──────────────────────────────────────────────
class SmsRequest(BaseModel):
    to: str
    body: str

@app.post("/twilio/sms/send")
async def send_sms(req: SmsRequest):
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        logger.warning("Twilio not configured — SMS not sent to %s", req.to)
        return {"status": "skipped", "message": "Twilio not configured, SMS queued locally"}
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=req.body,
            from_=TWILIO_PHONE_NUMBER,
            to=req.to,
        )
        logger.info("SMS sent: sid=%s to=%s", msg.sid, req.to)
        return {"status": "sent", "sid": msg.sid}
    except Exception as e:
        logger.error("Twilio SMS failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

# ──────────────────────────────────────────────
# DIALOGFLOW CX Fulfillment Webhook
# ──────────────────────────────────────────────
class DFCXRequest(BaseModel):
    session: str = ""
    tag: str = ""
    parameters: dict = {}
    fulfillmentInfo: Optional[dict] = None
    sessionInfo: Optional[dict] = None

@app.post("/dfcx-fulfillment")
async def dfcx_fulfillment(req: DFCXRequest, raw_request: Request):
    body = await raw_request.json()
    tag = body.get("fulfillmentInfo", {}).get("tag", "")
    session_info = body.get("sessionInfo", {})
    params = session_info.get("parameters", {})

    response = {"sessionInfo": session_info, "fulfillmentResponse": {}}

    if tag == "create-application":
        product = params.get("product_type", "banking")
        name = params.get("customer_name", "")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{request.base_url}tools/create-application",
                                     json={"product": product, "customer_name": name})
            data = resp.json()
        session_info["parameters"]["application_ref"] = data["reference"]
        session_info["parameters"]["application_status"] = data["status"]
        response["fulfillmentResponse"] = {"messages": [{"text": {"text": [data["message"]]}}]}

    elif tag == "manager-check":
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{request.base_url}tools/manager-check")
            data = resp.json()
        session_info["parameters"]["manager_available"] = "yes" if data["available"] else "no"
        msg = data["message"]
        response["fulfillmentResponse"] = {"messages": [{"text": {"text": [msg]}}]}

    elif tag == "schedule-feedback":
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{request.base_url}tools/schedule-feedback",
                                     json={
                                         "customer_name": params.get("customer_name", ""),
                                         "phone_number": params.get("customer_phone", ""),
                                         "reason": params.get("session_purpose", "feedback"),
                                     })
            data = resp.json()
        session_info["parameters"]["feedback_scheduled"] = "yes"
        response["fulfillmentResponse"] = {"messages": [{"text": {"text": [data["message"]]}}]}

    elif tag == "analyze-invoice":
        img_data = params.get("invoice_image", "")
        if img_data:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{request.base_url}tools/analyze-invoice")
                data = resp.json()
        else:
            data = {"total": 0, "currency": "USD", "formatted": "USD 0.00", "vendor": "Unknown",
                    "message": "Please upload a clear invoice image."}
        session_info["parameters"]["invoice_total"] = data["formatted"]
        response["fulfillmentResponse"] = {"messages": [{"text": {"text": [data["message"]]}}]}

    elif tag == "get-contact":
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{request.base_url}tools/get-contact",
                                     json={"reason": params.get("session_purpose", "general")})
            data = resp.json()
        response["fulfillmentResponse"] = {
            "messages": [{"text": {"text": [f"Email: {data['email']}. Phone: {data['phone']}. Hours: {data['hours']}"]}}]
        }

    else:
        response["fulfillmentResponse"] = {"messages": [{"text": {"text": ["I'm sorry, I don't understand that request."]}}]}

    return response
