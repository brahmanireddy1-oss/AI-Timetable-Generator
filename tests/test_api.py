"""Integration tests for BusMate AI FastAPI endpoints."""

from fastapi.testclient import TestClient
import pytest
from src.api import app

client = TestClient(app)


def test_health_endpoint():
    """Verify health endpoint returns status, mock counts, and telephony config."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "BusMate AI"
    assert data["mock_data"]["total_stops"] >= 10
    assert data["mock_data"]["total_routes"] >= 10
    assert "en" in data["supported_languages"]
    assert "te" in data["supported_languages"]
    assert "hi" in data["supported_languages"]


def test_get_stops_endpoint():
    """Verify stops listing and query filtering."""
    response = client.get("/api/stops")
    assert response.status_code == 200
    stops = response.json()
    assert len(stops) >= 10

    # Query search
    response_q = client.get("/api/stops?query=tukkuguda")
    assert response_q.status_code == 200
    q_stops = response_q.json()
    assert len(q_stops) > 0
    assert q_stops[0]["id"] == "S001"


def test_get_routes_endpoint():
    """Verify route listing and single route detail."""
    response = client.get("/api/routes")
    assert response.status_code == 200
    routes = response.json()
    assert len(routes) >= 10

    # Route by ID
    route_resp = client.get("/api/routes/R001")
    assert route_resp.status_code == 200
    assert route_resp.json()["route_number"] == "DEMO-101"

    # Route by route number
    route_num_resp = client.get("/api/routes/DEMO-101")
    assert route_num_resp.status_code == 200
    assert route_num_resp.json()["id"] == "R001"


def test_search_endpoint():
    """Verify route planning POST /api/search."""
    payload = {"source": "Tukkuguda", "destination": "Mehdipatnam", "language": "en"}
    response = client.post("/api/search", json=payload)
    assert response.status_code == 200
    results = response.json()
    assert len(results) > 0
    assert results[0]["is_direct"] is True
    assert results[0]["legs"][0]["route_number"] == "DEMO-101"


def test_departures_endpoint():
    """Verify upcoming departures POST /api/departures."""
    payload = {"stop_id": "S001", "route_id": "R001"}
    response = client.post("/api/departures", json=payload)
    assert response.status_code == 200
    deps = response.json()
    assert len(deps) > 0
    assert deps[0]["route_id"] == "R001"


def test_fare_endpoint():
    """Verify fare calculation POST /api/fare."""
    payload = {"source": "Tukkuguda", "destination": "Mehdipatnam"}
    response = client.post("/api/fare", json=payload)
    assert response.status_code == 200
    fare = response.json()
    assert fare["total_fare_inr"] > 0
    assert "Demonstration data only" in fare["disclaimer"]


def test_simulate_call_endpoint():
    """Verify simulated telephone call turn POST /api/simulate-call."""
    payload = {"query": "తుక్కుగూడ నుంచి మెహదీపట్నం ఎలా వెళ్లాలి?", "session_id": "test-call-1"}
    response = client.post("/api/simulate-call", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["language"] == "te"
    assert "response" in data
    assert "DEMO-101" in data["response"]


def test_sip_config_and_webhook():
    """Verify SIP configuration and inbound webhook."""
    config_resp = client.get("/api/sip/config")
    assert config_resp.status_code == 200
    config = config_resp.json()
    assert "trunk_config" in config
    assert "dispatch_rule" in config

    # Webhook
    webhook_payload = {
        "CallSid": "CA1234567890abcdef",
        "From": "+919876543210",
        "To": "+91-40-MOCKBUS",
    }
    wh_resp = client.post("/api/sip/webhook", json=webhook_payload)
    assert wh_resp.status_code == 200
    wh_data = wh_resp.json()
    assert wh_data["status"] == "call_accepted"
    assert "busmate-call-" in wh_data["room_name"]
