"""FastAPI application for BusMate AI.

Exposes REST endpoints for stop search, route planning, departure schedules,
fare estimation, SIP telephony integration, and interactive web playground.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import __version__
from src.agent import OPENING_GREETING, engine, simulate_turn
from src.config import (
    DISCLAIMER_TEXT,
    LIVEKIT_URL,
    SIP_PHONE_NUMBER,
    SIP_TRUNK_ID,
)
from src.models import (
    DepartureInfo,
    FareEstimate,
    Route,
    RouteSearchResult,
    Stop,
    StopSearchResult,
)
from src.telephony import SIPTelephonyManager

app = FastAPI(
    title="BusMate AI API",
    description="Multilingual Voice-Based Bus Route Assistant for Hyderabad (TGSRTC Mock Data)",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

telephony_mgr = SIPTelephonyManager()

STATIC_DIR = Path(__file__).resolve().parent / "static"


# Request & Response Schemas
class RouteSearchRequest(BaseModel):
    source: str = Field(..., json_schema_extra={"example": "Tukkuguda"})
    destination: str = Field(..., json_schema_extra={"example": "Mehdipatnam"})
    language: Optional[str] = Field("en", json_schema_extra={"example": "en"})


class DepartureRequest(BaseModel):
    stop_id: str = Field(..., json_schema_extra={"example": "S001"})
    route_id: Optional[str] = Field(None, json_schema_extra={"example": "R001"})


class FareEstimateRequest(BaseModel):
    source: str = Field(..., json_schema_extra={"example": "Tukkuguda"})
    destination: str = Field(..., json_schema_extra={"example": "Mehdipatnam"})


class SimulateCallRequest(BaseModel):
    query: str = Field(..., json_schema_extra={"example": "తుక్కుగూడ నుంచి మెహదీపట్నం ఎలా వెళ్లాలి?"})
    session_id: Optional[str] = Field("web-session-1")


class SIPCallWebhookRequest(BaseModel):
    CallSid: Optional[str] = None
    From: Optional[str] = "+919876543210"
    To: Optional[str] = SIP_PHONE_NUMBER
    CallStatus: Optional[str] = "ringing"


# Routes
@app.get("/api/health")
def health_check() -> Dict[str, Any]:
    """Health status and metadata."""
    return {
        "status": "healthy",
        "service": "BusMate AI",
        "version": __version__,
        "disclaimer": DISCLAIMER_TEXT,
        "mock_data": {
            "total_stops": len(engine.stops),
            "total_routes": len(engine.routes),
            "total_aliases": len(engine.aliases),
        },
        "telephony": {
            "sip_inbound_number": SIP_PHONE_NUMBER,
            "sip_trunk_id": SIP_TRUNK_ID,
            "livekit_url": LIVEKIT_URL,
        },
        "supported_languages": ["en", "te", "hi"],
    }


@app.get("/api/stops", response_model=List[Stop])
def get_stops(query: Optional[str] = None) -> List[Stop]:
    """List all Hyderabad stops or search stops."""
    if query:
        matches = engine.search_stops(query)
        stop_ids = [m.stop_id for m in matches]
        return [engine.stops[sid] for sid in stop_ids if sid in engine.stops]
    return list(engine.stops.values())


@app.get("/api/stops/{stop_id}", response_model=Stop)
def get_stop(stop_id: str) -> Stop:
    """Get single stop by ID or alias."""
    stop = engine.resolve_stop(stop_id)
    if not stop:
        raise HTTPException(status_code=404, detail=f"Stop '{stop_id}' not found")
    return stop


@app.get("/api/routes", response_model=List[Route])
def get_routes() -> List[Route]:
    """List all demonstration routes."""
    return list(engine.routes.values())


@app.get("/api/routes/{route_id}", response_model=Route)
def get_route(route_id: str) -> Route:
    """Get details for a specific route."""
    route = engine.get_route_details(route_id)
    if not route:
        # Check by route_number
        route = next(
            (r for r in engine.routes.values() if r.route_number.lower() == route_id.lower()),
            None,
        )
    if not route:
        raise HTTPException(status_code=404, detail=f"Route '{route_id}' not found")
    return route


@app.post("/api/search", response_model=List[RouteSearchResult])
def search_routes(payload: RouteSearchRequest) -> List[RouteSearchResult]:
    """Find direct and connecting bus routes between two stops."""
    results = engine.find_routes(payload.source, payload.destination)
    return results


@app.post("/api/departures", response_model=List[DepartureInfo])
def get_departures(payload: DepartureRequest) -> List[DepartureInfo]:
    """Get upcoming bus departures for a given stop and optional route."""
    stop = engine.resolve_stop(payload.stop_id)
    if not stop:
        raise HTTPException(status_code=404, detail=f"Stop '{payload.stop_id}' not found")

    route_id = payload.route_id
    if not route_id:
        passing = [r.id for r in engine.routes.values() if stop.id in r.stops]
        if not passing:
            return []
        route_id = passing[0]

    return engine.get_next_departures(route_id, stop.id)


@app.post("/api/fare", response_model=FareEstimate)
def estimate_fare(payload: FareEstimateRequest) -> FareEstimate:
    """Calculate journey fare estimate."""
    return engine.estimate_fare(source=payload.source, destination=payload.destination)


@app.post("/api/simulate-call")
def simulate_call(payload: SimulateCallRequest) -> Dict[str, Any]:
    """Simulate a phone call interaction turn with BusMate AI in English, Telugu, or Hindi."""
    result = simulate_turn(payload.query, payload.session_id or "web-session")
    return result


@app.get("/api/sip/config")
def get_sip_config() -> Dict[str, Any]:
    """Returns LiveKit SIP Trunk & Dispatch Rule configuration."""
    return {
        "trunk_config": telephony_mgr.generate_livekit_sip_trunk_config(),
        "dispatch_rule": telephony_mgr.generate_livekit_dispatch_rule_config(),
        "twilio_twiml_example": telephony_mgr.generate_twilio_twiml("sip:busmate@sip.livekit.cloud"),
    }


@app.post("/api/sip/webhook")
def sip_webhook(payload: SIPCallWebhookRequest) -> Dict[str, Any]:
    """Inbound webhook for telephony provider handling incoming calls."""
    call_id = payload.CallSid or f"sip-{datetime.now(timezone.utc).timestamp()}"
    caller_phone = payload.From or "Unknown"
    inbound_phone = payload.To or SIP_PHONE_NUMBER
    room_name = f"busmate-call-{call_id[-8:]}"

    session = telephony_mgr.register_call(
        call_id=call_id,
        caller_phone=caller_phone,
        room_name=room_name,
        inbound_phone=inbound_phone,
    )

    return {
        "status": "call_accepted",
        "room_name": room_name,
        "caller_phone": session.caller_phone,
        "welcome_greeting": OPENING_GREETING,
        "disclaimer": DISCLAIMER_TEXT,
    }


# Mount static files if directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    @app.get("/index.html")
    def serve_frontend():
        return FileResponse(STATIC_DIR / "index.html")
