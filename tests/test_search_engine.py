"""Comprehensive unit tests for BusMate AI Route Search Engine."""

from datetime import datetime
import pytest

from src.models import SupportedLanguage
from src.search_engine import RouteSearchEngine


@pytest.fixture
def engine():
    return RouteSearchEngine()


def test_data_loading(engine):
    """Verify that stops, routes, and aliases load properly from data files."""
    assert len(engine.stops) >= 10, "Should have loaded at least 10 stops"
    assert len(engine.routes) >= 10, "Should have loaded at least 10 routes"
    assert len(engine.aliases) >= 30, "Should have loaded aliases mapping"

    # Verify Tukkuguda exists
    tukkuguda = engine.resolve_stop("Tukkuguda")
    assert tukkuguda is not None
    assert tukkuguda.id == "S001"
    assert "te" in tukkuguda.supported_languages
    assert "hi" in tukkuguda.supported_languages


def test_multilingual_alias_resolution(engine):
    """Verify stop resolution across English, Telugu, and Hindi aliases and spellings."""
    # Tukkuguda variants
    assert engine.resolve_stop("Tukkuguda").id == "S001"
    assert engine.resolve_stop("tukuguda").id == "S001"
    assert engine.resolve_stop("తుక్కుగూడ").id == "S001"
    assert engine.resolve_stop("तुक्कुगुड़ा").id == "S001"

    # Mehdipatnam variants
    assert engine.resolve_stop("Mehdipatnam").id == "S002"
    assert engine.resolve_stop("mehdi patnam").id == "S002"
    assert engine.resolve_stop("మెహదీపట్నం").id == "S002"
    assert engine.resolve_stop("मेहदीपट्टनम").id == "S002"

    # Aramghar variants
    assert engine.resolve_stop("Aramghar").id == "S004"
    assert engine.resolve_stop("aram ghar").id == "S004"
    assert engine.resolve_stop("ఆరంఘర్").id == "S004"
    assert engine.resolve_stop("आरामघर").id == "S004"

    # LB Nagar variants
    assert engine.resolve_stop("LB Nagar").id == "S003"
    assert engine.resolve_stop("l b nagar").id == "S003"
    assert engine.resolve_stop("ఎల్బీ నగర్").id == "S003"
    assert engine.resolve_stop("एलबी नगर").id == "S003"

    # MGBS / Imlibun
    assert engine.resolve_stop("mgbs").id == "S010"
    assert engine.resolve_stop("imlibun").id == "S010"
    assert engine.resolve_stop("ఇమ్లీబన్").id == "S010"


def test_find_direct_routes(engine):
    """Test finding direct route from Tukkuguda to Mehdipatnam (DEMO-101)."""
    routes = engine.find_routes("Tukkuguda", "Mehdipatnam")
    assert len(routes) > 0, "Should find at least one direct route"

    best = routes[0]
    assert best.is_direct is True
    assert len(best.legs) == 1
    assert best.legs[0].route_number == "DEMO-101"
    assert best.legs[0].board_stop_name == "Tukkuguda"
    assert best.legs[0].alight_stop_name == "Mehdipatnam"
    assert best.total_duration_minutes > 0
    assert best.total_fare_inr > 0
    assert best.data_source == "MOCK"

    # Check multilingual summaries
    assert "en" in best.summary
    assert "te" in best.summary
    assert "hi" in best.summary
    assert "DEMO-101" in best.summary["en"]
    assert "DEMO-101" in best.summary["te"]
    assert "DEMO-101" in best.summary["hi"]


def test_find_reverse_direct_route(engine):
    """Test reverse journey from Mehdipatnam to Tukkuguda (DEMO-101R)."""
    routes = engine.find_routes("Mehdipatnam", "Tukkuguda")
    assert len(routes) > 0
    best = routes[0]
    assert best.is_direct is True
    assert best.legs[0].route_number == "DEMO-101R"


def test_find_connecting_routes(engine):
    """Test 1-transfer connecting journey (e.g., Tukkuguda to Secunderabad Station)."""
    routes = engine.find_routes("Tukkuguda", "Secunderabad Station")
    assert len(routes) > 0

    best = routes[0]
    # Should require a transfer (e.g. transfer at Mehdipatnam or Lakdikapul)
    assert best.is_direct is False
    assert len(best.legs) == 2
    assert best.transfer_stop_id is not None
    assert best.legs[0].board_stop_name == "Tukkuguda"
    assert best.legs[1].alight_stop_name == "Secunderabad Station"
    assert best.legs[0].alight_stop_id == best.legs[1].board_stop_id

    # Summaries should mention transfer
    assert "switch" in best.summary["en"].lower() or "take bus" in best.summary["en"].lower()
    assert "బస్సు" in best.summary["te"]
    assert "बस" in best.summary["hi"]


def test_fuzzy_stop_search(engine):
    """Test search_stops function with typos and confidence scoring."""
    results = engine.search_stops("tukkaguda")
    assert len(results) > 0
    assert results[0].stop_id == "S001"
    assert results[0].confidence >= 0.7

    results_te = engine.search_stops("తుక్కుగూడ")
    assert len(results_te) > 0
    assert results_te[0].stop_id == "S001"


def test_next_departures_calculation(engine):
    """Test scheduled departure generation at a specific time."""
    # Test morning 10:00 AM
    ref_time = datetime(2026, 10, 28, 10, 0, 0)
    departures = engine.get_next_departures("R001", "S001", reference_time=ref_time, limit=2)

    assert len(departures) == 2
    assert departures[0].route_number == "DEMO-101"
    assert departures[0].data_source == "MOCK"
    assert departures[0].minutes_from_now >= 0


def test_estimate_fare(engine):
    """Test fare calculation and breakdown with mock disclaimer."""
    fare = engine.estimate_fare(source="Tukkuguda", destination="Mehdipatnam")
    assert fare.total_fare_inr > 0
    assert fare.data_source == "MOCK"
    assert "Demonstration data only" in fare.disclaimer
    assert len(fare.breakdown) >= 1


def test_edge_cases(engine):
    """Test edge cases such as identical source/dest and non-existent stops."""
    # Same stop
    assert engine.find_routes("Tukkuguda", "Tukkuguda") == []

    # Non-existent stop
    assert engine.find_routes("Atlantis", "Mehdipatnam") == []
    assert engine.find_routes("Tukkuguda", "Mars") == []

    # Empty inputs
    assert engine.resolve_stop("") is None
    assert engine.resolve_stop(None) is None
    assert engine.search_stops("") == []
