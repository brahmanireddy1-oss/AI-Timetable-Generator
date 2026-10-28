"""Tests for BusMate AI agent tools, language detection, and conversation simulation."""

import pytest
from src.agent import (
    OPENING_GREETING,
    detect_language,
    simulate_turn,
    tool_clarify_stop,
    tool_estimate_fare,
    tool_find_bus_route,
    tool_get_next_departures,
)
from src.models import SupportedLanguage


def test_language_detection():
    """Verify language detection across English, Telugu, Hindi, Tenglish, and Hinglish."""
    # English
    assert detect_language("Which bus goes to Mehdipatnam?") == SupportedLanguage.EN
    assert detect_language("How much is the fare?") == SupportedLanguage.EN

    # Telugu script
    assert detect_language("తుక్కుగూడ నుంచి మెహదీపట్నం ఎలా వెళ్లాలి?") == SupportedLanguage.TE
    assert detect_language("నమస్కారం! బస్సు ఎప్పుడు వస్తుంది?") == SupportedLanguage.TE

    # Hindi script
    assert detect_language("मुझे तुक्कुगुड़ा से मेहदीपट्टनम जाना है।") == SupportedLanguage.HI
    assert detect_language("किराया कितना है?") == SupportedLanguage.HI

    # Code-mixing: Tenglish (Telugu spoken with English alphabet)
    assert detect_language("Tukkuguda nunchi Mehdipatnam ki ela vellali?") == SupportedLanguage.TE
    assert detect_language("Mehdipatnam nundi Secunderabad ki bussu undha?") == SupportedLanguage.TE

    # Code-mixing: Hinglish (Hindi spoken with English alphabet)
    assert detect_language("Tukkuguda se Mehdipatnam kaise jana hai?") == SupportedLanguage.HI
    assert detect_language("Mehdipatnam ke liye bus kab aayegi?") == SupportedLanguage.HI


def test_tool_find_bus_route():
    """Verify tool_find_bus_route returns helpful multilingual responses."""
    # English
    res_en = tool_find_bus_route("Tukkuguda", "Mehdipatnam", "en")
    assert "DEMO-101" in res_en
    assert "Tukkuguda" in res_en
    assert "Mehdipatnam" in res_en

    # Telugu
    res_te = tool_find_bus_route("Tukkuguda", "Mehdipatnam", "te")
    assert "DEMO-101" in res_te
    assert "తుక్కుగూడ" in res_te

    # Hindi
    res_hi = tool_find_bus_route("Tukkuguda", "Mehdipatnam", "hi")
    assert "DEMO-101" in res_hi
    assert "तुक्कुगुड़ा" in res_hi


def test_tool_next_departures():
    """Verify tool_get_next_departures returns scheduled timing."""
    res = tool_get_next_departures("Tukkuguda", "DEMO-101")
    assert "DEMO-101" in res
    assert "Tukkuguda" in res
    assert "Demo schedule" in res


def test_tool_estimate_fare():
    """Verify tool_estimate_fare returns transparent mock fare."""
    res = tool_estimate_fare("Tukkuguda", "Mehdipatnam")
    assert "₹" in res
    assert "Demonstration fare only" in res


def test_tool_clarify_stop():
    """Verify tool_clarify_stop suggests recognized stops."""
    res = tool_clarify_stop("tukku")
    assert "Tukkuguda" in res


def test_simulate_turn_english():
    """Verify simulated conversation turn in English."""
    result = simulate_turn("Which bus should I take from Tukkuguda to Mehdipatnam?", "session-en")
    assert result["language"] == "en"
    assert "DEMO-101" in result["response"]
    assert result["detected_route"] is not None


def test_simulate_turn_telugu():
    """Verify simulated conversation turn in Telugu."""
    result = simulate_turn("తుక్కుగూడ నుంచి మెహదీపట్నం ఎలా వెళ్లాలి?", "session-te")
    assert result["language"] == "te"
    assert "DEMO-101" in result["response"]
    assert "డైరెక్ట్" in result["response"] or "బస్సు" in result["response"]


def test_simulate_turn_hindi():
    """Verify simulated conversation turn in Hindi."""
    result = simulate_turn("मुझे तुक्कुगुड़ा से मेहदीपट्टनम जाना है।", "session-hi")
    assert result["language"] == "hi"
    assert "DEMO-101" in result["response"]
    assert "बस" in result["response"]


def test_simulate_turn_direct_bus_check():
    """Verify question 'Is there a direct bus from LB Nagar to Mehdipatnam?'."""
    result = simulate_turn("Is there a direct bus from LB Nagar to Mehdipatnam?", "session-direct")
    assert "direct" in result["response"].lower() or "transfer" in result["response"].lower()


def test_caller_questions_journey_details():
    """Verify follow-up queries: fare, next bus, and transfer requirements."""
    # First query sets context
    res1 = simulate_turn("Which bus should I take from Tukkuguda to Mehdipatnam?", "session-flow-1")
    assert "DEMO-101" in res1["response"]

    # Fare query
    res_fare = simulate_turn("What is the fare?", "session-flow-1")
    assert "₹" in res_fare["response"]

    # Next bus query
    res_next = simulate_turn("What is the next scheduled bus?", "session-flow-1")
    assert "DEMO-101" in res_next["response"]
    assert "Demo schedule" in res_next["response"]

    # Connecting journey query: "Do I need to change buses?"
    res_change = simulate_turn("Is there a direct bus from Tukkuguda to Secunderabad Station?", "session-flow-2")
    assert "transfer" in res_change["response"].lower() or "no" in res_change["response"].lower()

