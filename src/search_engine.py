"""Bus route search engine for Hyderabad city bus network (TGSRTC mock data).

Supports:
- Case-insensitive stop resolution with multilingual aliases (English, Telugu, Hindi).
- Fuzzy matching for spelling variations and transliterations.
- Direct routes and 1-transfer connecting journeys.
- Next scheduled bus departures calculation.
- Fare estimation with transparent MOCK disclaimers.
"""

from datetime import datetime, time, timedelta
import difflib
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from src.config import ALIASES_FILE, ROUTES_FILE, STOPS_FILE
from src.models import (
    DepartureInfo,
    FareEstimate,
    JourneyLeg,
    Route,
    RouteSearchResult,
    Stop,
    StopSearchResult,
    SupportedLanguage,
)


class RouteSearchEngine:
    def __init__(
        self,
        stops_path: Union[str, Path] = STOPS_FILE,
        routes_path: Union[str, Path] = ROUTES_FILE,
        aliases_path: Union[str, Path] = ALIASES_FILE,
    ):
        self.stops_path = Path(stops_path)
        self.routes_path = Path(routes_path)
        self.aliases_path = Path(aliases_path)

        self.stops: Dict[str, Stop] = {}
        self.routes: Dict[str, Route] = {}
        self.aliases: Dict[str, str] = {}

        self.load_data()

    def load_data(self) -> None:
        """Loads stops, routes, and aliases from JSON files."""
        # Load stops
        if self.stops_path.exists():
            with open(self.stops_path, "r", encoding="utf-8") as f:
                stops_raw = json.load(f)
                self.stops = {s["id"]: Stop(**s) for s in stops_raw}

        # Load routes
        if self.routes_path.exists():
            with open(self.routes_path, "r", encoding="utf-8") as f:
                routes_raw = json.load(f)
                self.routes = {r["id"]: Route(**r) for r in routes_raw}

        # Load aliases
        if self.aliases_path.exists():
            with open(self.aliases_path, "r", encoding="utf-8") as f:
                self.aliases = json.load(f)

        # Index canonical names and stop aliases into the alias dictionary
        for stop_id, stop in self.stops.items():
            self.aliases[stop.name.lower().strip()] = stop_id
            for alias in stop.aliases:
                self.aliases[alias.lower().strip()] = stop_id
            for lang, localized in stop.supported_languages.items():
                self.aliases[localized.lower().strip()] = stop_id

    def normalize_term(self, term: str) -> str:
        """Normalizes search query for consistent matching."""
        if not term:
            return ""
        # Remove extra whitespace and lower case
        cleaned = " ".join(term.strip().lower().split())
        return cleaned

    def resolve_stop(self, query: str) -> Optional[Stop]:
        """Resolves a stop name, alias, ID, or localized string to a Stop object."""
        if not query:
            return None

        # Check if direct stop_id
        if query in self.stops:
            return self.stops[query]

        normalized = self.normalize_term(query)

        # Common English/transit words that must not be accidentally matched as stops
        STOPWORDS = {
            "is", "the", "a", "an", "at", "to", "in", "on", "for", "from", "of", "and", "or",
            "bus", "stop", "buses", "next", "what", "where", "how", "when", "which", "me", "i",
            "take", "go", "get", "scheduled", "there", "direct", "change", "fare", "ticket"
        }
        if normalized in STOPWORDS:
            return None

        # Check alias exact match
        if normalized in self.aliases:
            stop_id = self.aliases[normalized]
            return self.stops.get(stop_id)

        # Check case-insensitive canonical names
        for stop_id, stop in self.stops.items():
            if normalized == stop.name.lower():
                return stop
            for alias in stop.aliases:
                if normalized == alias.lower():
                    return stop
            for lang, localized in stop.supported_languages.items():
                if normalized == localized.lower():
                    return stop

        # Fuzzy match across all aliases (minimum length 4 to prevent false positives)
        if len(normalized) >= 4:
            candidates = [k for k in self.aliases.keys() if len(k) >= 4]
            matches = difflib.get_close_matches(normalized, candidates, n=1, cutoff=0.75)
            if matches:
                matched_alias = matches[0]
                stop_id = self.aliases[matched_alias]
                return self.stops.get(stop_id)

        # Substring search: alias is contained inside the query phrase
        # Sort by length descending to match longest alias first
        sorted_aliases = sorted(self.aliases.items(), key=lambda x: len(x[0]), reverse=True)
        for alias, stop_id in sorted_aliases:
            if len(alias) >= 4 and (f" {alias} " in f" {normalized} " or alias == normalized):
                return self.stops.get(stop_id)

        return None

    def search_stops(
        self, query: str, language: Optional[str] = None
    ) -> List[StopSearchResult]:
        """Fuzzy searches stops matching the given query with confidence scores."""
        normalized = self.normalize_term(query)
        if not normalized:
            return []

        results: List[StopSearchResult] = []
        seen_stops = set()

        # 1. Exact alias or name match (1.0 confidence)
        if normalized in self.aliases:
            stop_id = self.aliases[normalized]
            stop = self.stops.get(stop_id)
            if stop and stop_id not in seen_stops:
                seen_stops.add(stop_id)
                results.append(
                    StopSearchResult(
                        stop_id=stop.id,
                        canonical_name=stop.name,
                        matched_term=normalized,
                        confidence=1.0,
                        locality=stop.locality,
                        localized_names=stop.supported_languages,
                    )
                )

        # 2. Substring & Alias similarity
        for alias, stop_id in self.aliases.items():
            if stop_id in seen_stops:
                continue
            ratio = difflib.SequenceMatcher(None, normalized, alias).ratio()
            if normalized in alias or alias in normalized:
                confidence = max(0.85, ratio)
            elif ratio >= 0.65:
                confidence = ratio
            else:
                continue

            stop = self.stops.get(stop_id)
            if stop:
                seen_stops.add(stop_id)
                results.append(
                    StopSearchResult(
                        stop_id=stop.id,
                        canonical_name=stop.name,
                        matched_term=alias,
                        confidence=round(confidence, 2),
                        locality=stop.locality,
                        localized_names=stop.supported_languages,
                    )
                )

        # Sort by confidence descending
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results

    def get_route_details(self, route_id: str) -> Optional[Route]:
        """Returns detailed route information for a route ID."""
        return self.routes.get(route_id)

    def _calculate_leg_timing_and_fare(
        self, route: Route, source_idx: int, dest_idx: int
    ) -> Tuple[int, int]:
        """Computes journey duration and fare between two stops on a route."""
        total_stops = len(route.stops)
        stops_count = abs(dest_idx - source_idx)

        # Use stop_timings if available
        src_timing = next(
            (st.minutes_from_start for st in route.stop_timings if st.stop_id == route.stops[source_idx]),
            None,
        )
        dst_timing = next(
            (st.minutes_from_start for st in route.stop_timings if st.stop_id == route.stops[dest_idx]),
            None,
        )

        if src_timing is not None and dst_timing is not None:
            duration = abs(dst_timing - src_timing)
        else:
            # Fallback proportional estimate
            duration = max(
                10, int((stops_count / max(1, total_stops - 1)) * route.estimated_duration_minutes)
            )

        # Fare calculation: base 15 INR + distance-based increments
        fare = max(15, int((stops_count / max(1, total_stops - 1)) * route.fare_inr))
        # Round fare to nearest 5
        fare = int(round(fare / 5.0) * 5)
        return duration, fare

    def _build_leg(
        self, route: Route, source_stop: Stop, dest_stop: Stop
    ) -> JourneyLeg:
        """Constructs a JourneyLeg object between source and destination stops on a route."""
        source_idx = route.stops.index(source_stop.id)
        dest_idx = route.stops.index(dest_stop.id)

        duration, fare = self._calculate_leg_timing_and_fare(route, source_idx, dest_idx)

        intermediate_stop_ids = route.stops[source_idx + 1 : dest_idx]
        intermediate_names = [
            self.stops[sid].name for sid in intermediate_stop_ids if sid in self.stops
        ]

        return JourneyLeg(
            route_id=route.id,
            route_number=route.route_number,
            service_type=route.service_type,
            board_stop_id=source_stop.id,
            board_stop_name=source_stop.name,
            board_stop_localized=source_stop.supported_languages,
            alight_stop_id=dest_stop.id,
            alight_stop_name=dest_stop.name,
            alight_stop_localized=dest_stop.supported_languages,
            intermediate_stops=intermediate_names,
            duration_minutes=duration,
            fare_inr=fare,
        )

    def _generate_multilingual_summaries(
        self,
        is_direct: bool,
        source_stop: Stop,
        dest_stop: Stop,
        legs: List[JourneyLeg],
        transfer_stop: Optional[Stop] = None,
    ) -> Dict[str, str]:
        """Generates natural, concise multilingual speech summaries for callers."""
        src_en = source_stop.name
        dst_en = dest_stop.name
        src_te = source_stop.supported_languages.get("te", src_en)
        dst_te = dest_stop.supported_languages.get("te", dst_en)
        src_hi = source_stop.supported_languages.get("hi", src_en)
        dst_hi = dest_stop.supported_languages.get("hi", dst_en)

        total_duration = sum(leg.duration_minutes for leg in legs)
        total_fare = sum(leg.fare_inr for leg in legs)

        if is_direct:
            leg = legs[0]
            summary_en = (
                f"You can take direct bus {leg.route_number} ({leg.service_type}) "
                f"from {src_en} to {dst_en}. The journey takes approximately {leg.duration_minutes} "
                f"minutes with a fare of {leg.fare_inr} rupees. (Demo schedule)"
            )
            summary_te = (
                f"{src_te} నుంచి {dst_te} కు డైరెక్ట్ బస్సు {leg.route_number} ఉంది. "
                f"ప్రయాణ సమయం సుమారు {leg.duration_minutes} నిమిషాలు, ఛార్జీ {leg.fare_inr} రూపాయలు."
            )
            summary_hi = (
                f"{src_hi} से {dst_hi} के लिए सीधी बस {leg.route_number} उपलब्ध है। "
                f"सफ़र में लगभग {leg.duration_minutes} मिनट लगेंगे और किराया {leg.fare_inr} रुपये है।"
            )
        else:
            leg1 = legs[0]
            leg2 = legs[1]
            t_en = transfer_stop.name if transfer_stop else leg1.alight_stop_name
            t_te = transfer_stop.supported_languages.get("te", t_en) if transfer_stop else t_en
            t_hi = transfer_stop.supported_languages.get("hi", t_en) if transfer_stop else t_en

            # Add 10 mins transfer buffer
            total_duration += 10

            summary_en = (
                f"There is no direct bus. Take bus {leg1.route_number} from {src_en} to {t_en}, "
                f"then switch to bus {leg2.route_number} to reach {dst_en}. "
                f"Total journey time is about {total_duration} minutes, total fare is {total_fare} rupees."
            )
            summary_te = (
                f"డైరెక్ట్ బస్సు లేదు. ముందుగా {src_te} వద్ద బస్సు {leg1.route_number} ఎక్కి {t_te} వరకు వెళ్లండి. "
                f"అక్కడ బస్సు మారి {leg2.route_number} లో {dst_te} చేరుకోండి. "
                f"మొత్తం సమయం సుమారు {total_duration} నిమిషాలు, ఛార్జీ {total_fare} రూపాయలు."
            )
            summary_hi = (
                f"सीधी बस उपलब्ध नहीं है। पहले {src_hi} से बस {leg1.route_number} लेकर {t_hi} तक जाएँ, "
                f"फिर वहाँ से बस बदलकर {leg2.route_number} से {dst_hi} पहुँचें। "
                f"कुल समय लगभग {total_duration} मिनट और किराया {total_fare} रुपये है।"
            )

        return {"en": summary_en, "te": summary_te, "hi": summary_hi}

    def find_routes(
        self, source_query: str, destination_query: str
    ) -> List[RouteSearchResult]:
        """Finds direct and 1-transfer connecting routes between source and destination.

        Matches stop aliases case-insensitively and handles transliterations.
        """
        source_stop = self.resolve_stop(source_query)
        dest_stop = self.resolve_stop(destination_query)

        if not source_stop or not dest_stop:
            return []

        if source_stop.id == dest_stop.id:
            return []

        results: List[RouteSearchResult] = []

        # 1. Search for direct routes
        for route in self.routes.values():
            if source_stop.id in route.stops and dest_stop.id in route.stops:
                src_idx = route.stops.index(source_stop.id)
                dst_idx = route.stops.index(dest_stop.id)
                # Bus must travel forward from source to destination
                if src_idx < dst_idx:
                    leg = self._build_leg(route, source_stop, dest_stop)
                    summaries = self._generate_multilingual_summaries(
                        is_direct=True,
                        source_stop=source_stop,
                        dest_stop=dest_stop,
                        legs=[leg],
                    )
                    results.append(
                        RouteSearchResult(
                            is_direct=True,
                            legs=[leg],
                            total_duration_minutes=leg.duration_minutes,
                            total_fare_inr=leg.fare_inr,
                            summary=summaries,
                            data_source="MOCK",
                            disclaimer="Demonstration data only. Not official TGSRTC schedule.",
                        )
                    )

        # If direct routes found, sort by duration and return
        if results:
            results.sort(key=lambda r: r.total_duration_minutes)
            return results

        # 2. Search for 1-transfer connecting routes
        connecting_results: List[RouteSearchResult] = []

        # Find routes passing through source
        source_routes = [
            r for r in self.routes.values() if source_stop.id in r.stops
        ]
        # Find routes passing through destination
        dest_routes = [
            r for r in self.routes.values() if dest_stop.id in r.stops
        ]

        seen_transfers = set()

        for r1 in source_routes:
            src_idx = r1.stops.index(source_stop.id)
            # Candidate transfer stops on r1 that come AFTER source
            candidate_transfers = r1.stops[src_idx + 1 :]

            for r2 in dest_routes:
                if r1.id == r2.id:
                    continue

                dst_idx = r2.stops.index(dest_stop.id)
                # Stops on r2 that come BEFORE destination
                prior_stops_r2 = r2.stops[:dst_idx]

                # Common transfer stops
                common_stops = [
                    sid for sid in candidate_transfers if sid in prior_stops_r2
                ]

                for transfer_id in common_stops:
                    transfer_key = (r1.id, r2.id, transfer_id)
                    if transfer_key in seen_transfers:
                        continue
                    seen_transfers.add(transfer_key)

                    transfer_stop = self.stops.get(transfer_id)
                    if not transfer_stop:
                        continue

                    leg1 = self._build_leg(r1, source_stop, transfer_stop)
                    leg2 = self._build_leg(r2, transfer_stop, dest_stop)

                    # Add 10 mins transfer wait time to total duration
                    total_dur = leg1.duration_minutes + leg2.duration_minutes + 10
                    total_fare = leg1.fare_inr + leg2.fare_inr

                    summaries = self._generate_multilingual_summaries(
                        is_direct=False,
                        source_stop=source_stop,
                        dest_stop=dest_stop,
                        legs=[leg1, leg2],
                        transfer_stop=transfer_stop,
                    )

                    connecting_results.append(
                        RouteSearchResult(
                            is_direct=False,
                            legs=[leg1, leg2],
                            total_duration_minutes=total_dur,
                            total_fare_inr=total_fare,
                            transfer_stop_id=transfer_stop.id,
                            transfer_stop_name=transfer_stop.name,
                            summary=summaries,
                            data_source="MOCK",
                            disclaimer="Demonstration data only. Not official TGSRTC schedule.",
                        )
                    )

        connecting_results.sort(key=lambda r: r.total_duration_minutes)
        return connecting_results[:3]

    def get_next_departures(
        self,
        route_id: str,
        stop_id: str,
        reference_time: Optional[datetime] = None,
        limit: int = 3,
    ) -> List[DepartureInfo]:
        """Calculates upcoming scheduled bus departure timings for a given route and stop."""
        route = self.routes.get(route_id)
        stop = self.resolve_stop(stop_id)

        if not route or not stop or stop.id not in route.stops:
            return []

        if reference_time is None:
            reference_time = datetime.now()

        # Parse schedule
        first_dt = datetime.strptime(route.schedule.first_bus, "%H:%M").time()
        last_dt = datetime.strptime(route.schedule.last_bus, "%H:%M").time()
        freq = route.frequency_minutes

        # Calculate offset minutes from route start to this stop
        stop_timing = next(
            (st.minutes_from_start for st in route.stop_timings if st.stop_id == stop.id),
            None,
        )
        if stop_timing is None:
            idx = route.stops.index(stop.id)
            stop_timing = int((idx / max(1, len(route.stops) - 1)) * route.estimated_duration_minutes)

        # Generate all departure times today
        departures: List[DepartureInfo] = []
        today = reference_time.date()

        current_bus_start = datetime.combine(today, first_dt)
        end_bus_start = datetime.combine(today, last_dt)

        while current_bus_start <= end_bus_start:
            stop_arrival = current_bus_start + timedelta(minutes=stop_timing)
            diff_minutes = int((stop_arrival - reference_time).total_seconds() / 60)

            if diff_minutes >= 0:
                departures.append(
                    DepartureInfo(
                        route_id=route.id,
                        route_number=route.route_number,
                        route_name=route.name,
                        stop_id=stop.id,
                        stop_name=stop.name,
                        scheduled_time=stop_arrival.strftime("%I:%M %p"),
                        minutes_from_now=diff_minutes,
                        data_source="MOCK",
                        disclaimer="Demonstration data only. Not official TGSRTC schedule.",
                    )
                )
                if len(departures) >= limit:
                    break

            current_bus_start += timedelta(minutes=freq)

        # If no more departures today, show first departures tomorrow
        if not departures:
            tomorrow = today + timedelta(days=1)
            current_bus_start = datetime.combine(tomorrow, first_dt)
            for _ in range(limit):
                stop_arrival = current_bus_start + timedelta(minutes=stop_timing)
                diff_minutes = int((stop_arrival - reference_time).total_seconds() / 60)
                departures.append(
                    DepartureInfo(
                        route_id=route.id,
                        route_number=route.route_number,
                        route_name=route.name,
                        stop_id=stop.id,
                        stop_name=stop.name,
                        scheduled_time=f"Tomorrow at {stop_arrival.strftime('%I:%M %p')}",
                        minutes_from_now=diff_minutes,
                        data_source="MOCK",
                        disclaimer="Demonstration data only. Not official TGSRTC schedule.",
                    )
                )
                current_bus_start += timedelta(minutes=freq)

        return departures

    def estimate_fare(
        self,
        route_ids: Optional[List[str]] = None,
        source: Optional[str] = None,
        destination: Optional[str] = None,
    ) -> FareEstimate:
        """Estimates journey fare for a route or pair of stops with full mock disclaimer."""
        source_stop = self.resolve_stop(source) if source else None
        dest_stop = self.resolve_stop(destination) if destination else None

        src_name = source_stop.name if source_stop else (source or "Unknown Source")
        dst_name = dest_stop.name if dest_stop else (destination or "Unknown Destination")

        # If source and dest provided, find routes
        if source_stop and dest_stop:
            routes = self.find_routes(source_stop.name, dest_stop.name)
            if routes:
                best = routes[0]
                breakdown = [
                    {
                        "route_number": leg.route_number,
                        "service_type": leg.service_type,
                        "from": leg.board_stop_name,
                        "to": leg.alight_stop_name,
                        "duration_minutes": leg.duration_minutes,
                        "fare_inr": leg.fare_inr,
                    }
                    for leg in best.legs
                ]
                return FareEstimate(
                    source_stop=src_name,
                    destination_stop=dst_name,
                    total_fare_inr=best.total_fare_inr,
                    currency="INR",
                    legs_count=len(best.legs),
                    breakdown=breakdown,
                    data_source="MOCK",
                    disclaimer="Demonstration data only. Not official TGSRTC fares.",
                )

        # Fallback using route_ids
        total_fare = 0
        breakdown = []
        if route_ids:
            for rid in route_ids:
                route = self.routes.get(rid)
                if route:
                    total_fare += route.fare_inr
                    breakdown.append(
                        {
                            "route_number": route.route_number,
                            "service_type": route.service_type,
                            "fare_inr": route.fare_inr,
                        }
                    )

        if total_fare == 0:
            total_fare = 25  # default ordinary minimum fare

        return FareEstimate(
            source_stop=src_name,
            destination_stop=dst_name,
            total_fare_inr=total_fare,
            currency="INR",
            legs_count=len(breakdown) if breakdown else 1,
            breakdown=breakdown,
            data_source="MOCK",
            disclaimer="Demonstration data only. Not official TGSRTC fares.",
        )
