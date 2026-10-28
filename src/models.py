"""Data models for BusMate AI bus route search engine and voice agent."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SupportedLanguage(str, Enum):
    EN = "en"
    TE = "te"
    HI = "hi"


class Stop(BaseModel):
    id: str
    name: str
    aliases: List[str] = Field(default_factory=list)
    supported_languages: Dict[str, str] = Field(default_factory=dict)
    locality: Optional[str] = None
    landmark: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = None


class StopTiming(BaseModel):
    stop_id: str
    minutes_from_start: int


class Schedule(BaseModel):
    first_bus: str = "06:00"
    last_bus: str = "22:00"
    frequency_minutes: int = 30


class Route(BaseModel):
    id: str
    route_number: str
    name: str
    direction: str = "Forward"
    service_type: str = "City Ordinary (MOCK)"
    stops: List[str]
    stop_timings: List[StopTiming] = Field(default_factory=list)
    schedule: Schedule = Field(default_factory=Schedule)
    frequency_minutes: int = 30
    estimated_duration_minutes: int = 45
    fare_inr: int = 25
    data_source: str = "MOCK"
    disclaimer: str = "Demonstration data only. Not official TGSRTC schedule."


class JourneyLeg(BaseModel):
    route_id: str
    route_number: str
    service_type: str
    board_stop_id: str
    board_stop_name: str
    board_stop_localized: Dict[str, str]
    alight_stop_id: str
    alight_stop_name: str
    alight_stop_localized: Dict[str, str]
    intermediate_stops: List[str] = Field(default_factory=list)
    duration_minutes: int
    fare_inr: int


class RouteSearchResult(BaseModel):
    is_direct: bool
    legs: List[JourneyLeg]
    total_duration_minutes: int
    total_fare_inr: int
    transfer_stop_id: Optional[str] = None
    transfer_stop_name: Optional[str] = None
    summary: Dict[str, str] = Field(default_factory=dict)
    data_source: str = "MOCK"
    disclaimer: str = "Demonstration data only. Not official TGSRTC schedule."


class DepartureInfo(BaseModel):
    route_id: str
    route_number: str
    route_name: str
    stop_id: str
    stop_name: str
    scheduled_time: str
    minutes_from_now: int
    data_source: str = "MOCK"
    disclaimer: str = "Demonstration data only. Not official TGSRTC schedule."


class FareEstimate(BaseModel):
    source_stop: str
    destination_stop: str
    total_fare_inr: int
    currency: str = "INR"
    legs_count: int = 1
    breakdown: List[Dict[str, Any]] = Field(default_factory=list)
    data_source: str = "MOCK"
    disclaimer: str = "Demonstration data only. Not official TGSRTC schedule."


class StopSearchResult(BaseModel):
    stop_id: str
    canonical_name: str
    matched_term: str
    confidence: float
    locality: Optional[str] = None
    localized_names: Dict[str, str] = Field(default_factory=dict)
