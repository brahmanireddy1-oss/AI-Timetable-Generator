"""BusMate AI - Voice Agent using Gemini Live and LiveKit Agents.

Multilingual telephone voice assistant for Hyderabad city bus information (TGSRTC mock data).
Supports English, Telugu, and Hindi with code-mixing and real-time language switching.
"""

import asyncio
from datetime import datetime
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from src.config import (
    DISCLAIMER_TEXT,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_VOICE,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_URL,
)
from src.models import SupportedLanguage
from src.search_engine import RouteSearchEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("busmate.agent")

# Global singleton search engine
engine = RouteSearchEngine()

# Opening Greeting
OPENING_GREETING = (
    "Namaskaram! Welcome to BusMate AI, your Hyderabad bus information assistant. "
    "You can speak in Telugu, English, or Hindi. Where would you like to travel from and to?"
)

OPENING_GREETING_TE = (
    "నమస్కారం! బస్‌మేట్ ఏఐ కు స్వాగతం. మీరు తెలుగు, ఇంగ్లీష్ లేదా హిందీలో మాట్లాడవచ్చు. "
    "మీరు ఎక్కడి నుంచి ఎక్కడికి వెళ్లాలి?"
)

OPENING_GREETING_HI = (
    "नमस्कार! बसमेट एआई में आपका स्वागत है। आप तेलुगु, अंग्रेज़ी या हिंदी में बात कर सकते हैं। "
    "आप कहाँ से कहाँ जाना चाहते हैं?"
)

# System Prompt for Gemini Live / LLM
SYSTEM_PROMPT = f"""You are BusMate AI, a polite, friendly, and patient telephone voice assistant for Hyderabad city bus travel (TGSRTC).

CRITICAL INSTRUCTIONS:
1. GREETING:
   Start with: "Namaskaram! Welcome to BusMate AI, your Hyderabad bus information assistant. You can speak in Telugu, English, or Hindi. Where would you like to travel from and to?"

2. MULTILINGUAL BEHAVIOR:
   - Support English, Telugu (తెలుగు), and Hindi (हिंदी).
   - Detect the caller's spoken language dynamically.
   - If the caller speaks Telugu (e.g. "తుక్కుగూడ నుంచి మెహదీపట్నం ఎలా వెళ్లాలి?"), reply in natural, conversational Telugu.
   - If the caller speaks Hindi (e.g. "मुझे तुक्कुगुड़ा से मेहदीपट्टनम जाना है।"), reply in natural, polite Hindi.
   - If the caller speaks English, reply in clear, simple English.
   - Support code-mixing (Tenglish / Hinglish) naturally. Accept English place names spoken within Telugu or Hindi.
   - Allow the caller to switch languages anytime (e.g. "Telugu lo cheppandi", "Hindi mein bataiye").

3. VOICE AGENT CONVERSATION STYLE (TELEPHONE CALL):
   - Keep answers CONCISE and easy to listen to over the phone (2 to 3 sentences maximum per turn).
   - Be patient and respectful to elderly callers and people unfamiliar with Hyderabad.
   - Do NOT overwhelm the caller with too many route numbers or stops at once.
   - Ask clarifying questions if source or destination is ambiguous.
   - Never silently alter a location.

4. MOCK DATA DISCLAIMER:
   - The bus schedules, fares, and route numbers provided are DEMONSTRATION / MOCK DATA for testing ({DISCLAIMER_TEXT}).
   - Always mention or keep in mind that this is demo schedule information.

5. TOOL CALLING:
   - Always call `find_bus_route` when a caller asks how to go between two places.
   - Call `get_next_departures` when a caller asks when the next bus arrives or departs.
   - Call `estimate_fare` when a caller asks about ticket prices.
   - Call `clarify_stop` if the stop name is incomplete or ambiguous.
"""


def detect_language(text: str) -> SupportedLanguage:
    """Detects whether text is primarily Telugu, Hindi, or English."""
    if not text:
        return SupportedLanguage.EN

    # Check for Telugu Unicode range: \u0c00-\u0c7f
    telugu_chars = len(re.findall(r"[\u0c00-\u0c7f]", text))
    # Check for Devanagari (Hindi) Unicode range: \u0900-\u097f
    hindi_chars = len(re.findall(r"[\u0900-\u097f]", text))

    total_len = len(text.replace(" ", ""))

    if telugu_chars > 0 and (telugu_chars >= hindi_chars or telugu_chars >= total_len * 0.2):
        return SupportedLanguage.TE
    if hindi_chars > 0 and (hindi_chars > telugu_chars or hindi_chars >= total_len * 0.2):
        return SupportedLanguage.HI

    # Check for Telugu Romanized keywords (Tenglish)
    te_keywords = {"nunchi", "nundi", "velli", "vellali", "ekkadiki", "undha", "cheppandi", "bussu", "eppudu", "ela", "kavali"}
    clean_words = set(re.findall(r"[a-zA-Z]+", text.lower()))
    if te_keywords.intersection(clean_words):
        return SupportedLanguage.TE

    # Check for Hindi Romanized keywords (Hinglish)
    hi_keywords = {"kahan", "jana", "hai", "se", "tak", "batao", "bataiye", "kitna", "kiraya", "milegi", "liye", "kab", "aayegi", "kaise", "kaha", "kis", "kaunsi", "aayega", "milega", "chahiye"}
    if hi_keywords.intersection(clean_words):
        return SupportedLanguage.HI

    return SupportedLanguage.EN


# Tool definitions for Gemini / LiveKit function calling
def tool_find_bus_route(source: str, destination: str, language: Optional[str] = None) -> str:
    """Search available bus routes between source and destination stops in Hyderabad."""
    src_stop = engine.resolve_stop(source)
    dst_stop = engine.resolve_stop(destination)

    if not src_stop:
        return f"Could not find stop matching '{source}'. Please specify a recognized Hyderabad location (e.g., Tukkuguda, Mehdipatnam, LB Nagar, Aramghar, Koti, Secunderabad)."
    if not dst_stop:
        return f"Could not find stop matching '{destination}'. Please specify a recognized Hyderabad location."

    if src_stop.id == dst_stop.id:
        return f"Source and destination are both {src_stop.name}. Please provide two different locations."

    routes = engine.find_routes(src_stop.name, dst_stop.name)
    if not routes:
        return f"No direct or 1-transfer mock route found between {src_stop.name} and {dst_stop.name} in demo database."

    best = routes[0]
    lang = language or "en"
    if lang in best.summary:
        return best.summary[lang]
    return best.summary.get("en", "")


def tool_get_next_departures(stop_name: str, route_number: Optional[str] = None) -> str:
    """Get the next scheduled bus departures for a given Hyderabad bus stop."""
    stop = engine.resolve_stop(stop_name)
    if not stop:
        return f"Could not find bus stop '{stop_name}'."

    # Find matching route if provided, otherwise check routes passing through this stop
    target_route = None
    if route_number:
        clean_num = route_number.strip().upper()
        target_route = next((r for r in engine.routes.values() if r.route_number.upper() == clean_num or r.id.upper() == clean_num), None)

    if not target_route:
        # Pick first route passing through stop
        passing_routes = [r for r in engine.routes.values() if stop.id in r.stops]
        if not passing_routes:
            return f"No scheduled mock routes found passing through {stop.name}."
        target_route = passing_routes[0]

    departures = engine.get_next_departures(target_route.id, stop.id, limit=2)
    if not departures:
        return f"No upcoming departures found today for {target_route.route_number} at {stop.name}."

    dep_strings = [f"{d.scheduled_time} (in {d.minutes_from_now} mins)" for d in departures]
    return (
        f"Next scheduled departures for bus {target_route.route_number} ({target_route.name}) "
        f"at {stop.name}: {', '.join(dep_strings)}. (Demo schedule)"
    )


def tool_estimate_fare(source: str, destination: str) -> str:
    """Calculate the estimated bus fare between two stops in Hyderabad."""
    estimate = engine.estimate_fare(source=source, destination=destination)
    return (
        f"The estimated mock fare from {estimate.source_stop} to {estimate.destination_stop} "
        f"is ₹{estimate.total_fare_inr}. (Demonstration fare only, not official TGSRTC tariff)."
    )


def tool_clarify_stop(stop_query: str) -> str:
    """Search for matching stop names if speech recognition is uncertain."""
    results = engine.search_stops(stop_query)
    if not results:
        return f"No stops found matching '{stop_query}'. Available stops include Tukkuguda, Mehdipatnam, LB Nagar, Aramghar, Secunderabad, Koti, Hitec City, Charminar, Gachibowli, Lakdikapul, Uppal."
    top_matches = [r.canonical_name for r in results[:3]]
    return f"Did you mean one of these stops: {', '.join(top_matches)}?"


class CallSessionState:
    """Tracks state for an individual telephone call."""
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.language: SupportedLanguage = SupportedLanguage.EN
        self.current_source: Optional[str] = None
        self.current_destination: Optional[str] = None
        self.last_route_id: Optional[str] = None
        self.history: List[Dict[str, str]] = []


# In-memory session store
sessions: Dict[str, CallSessionState] = {}


def get_or_create_session(session_id: str) -> CallSessionState:
    if session_id not in sessions:
        sessions[session_id] = CallSessionState(session_id)
    return sessions[session_id]


def simulate_turn(user_query: str, session_id: str = "sim-1") -> Dict[str, Any]:
    """Simulates an interactive conversation turn for web playground and testing.

    Parses caller query, identifies language, calls route engine tools,
    and returns a natural multilingual response.
    """
    state = get_or_create_session(session_id)
    detected_lang = detect_language(user_query)
    state.language = detected_lang
    q_lower = user_query.lower()

    # 1. Check for standalone greetings
    words = re.findall(r"[\w]+", q_lower)
    greeting_words = {"hello", "hi", "hey", "namaste", "namaskaram", "హలో", "నమస్కారం", "नमस्ते", "నమస్తే"}
    is_pure_greeting = len(words) <= 3 and any(w in greeting_words for w in words)
    if is_pure_greeting:
        if detected_lang == SupportedLanguage.TE:
            reply = "నమస్కారం! మీరు ఎక్కడి నుంచి ఎక్కడికి ప్రయాణించాలి? మీ స్టాప్ పేరు చెప్పండి."
        elif detected_lang == SupportedLanguage.HI:
            reply = "नमस्ते! आप कहाँ से कहाँ जाना चाहते हैं? कृपया अपने स्टॉप का नाम बताएं।"
        else:
            reply = "Hello! Where would you like to travel from and to in Hyderabad?"
        return {"response": reply, "language": state.language.value, "detected_route": None}

    # 2. Check for next bus / timing inquiry first if explicitly requested
    if any(w in q_lower for w in ["next bus", "next", "timing", "departure", "schedule", "when is the bus", "ఎప్పుడు", "समय", "कब"]):
        stop_to_check = state.current_source or "Tukkuguda"
        for s in engine.stops.values():
            if s.name.lower() in q_lower:
                stop_to_check = s.name
                break
        reply = tool_get_next_departures(stop_to_check, state.last_route_id)
        return {"response": reply, "language": state.language.value, "detected_route": None}

    # 3. Check for fare inquiry first if explicitly requested
    if any(w in q_lower for w in ["fare", "ticket", "cost", "price", "ఛార్జీ", "టికెట్", "కిరాయి", "किराया"]):
        src = state.current_source or "Tukkuguda"
        dst = state.current_destination or "Mehdipatnam"
        reply = tool_estimate_fare(src, dst)
        return {"response": reply, "language": state.language.value, "detected_route": None}

    # 4. Check for route inquiry: "from X to Y", "X nunchi Y", "X se Y"
    source = None
    dest = None

    # Telugu pattern: "<src> nunchi <dst>" or "<src> నుంచి <dst>"
    te_match = re.search(r"(.+?)(?:\s+నుంచి|\s+నుండి|\s+nunchi|\s+nundi)\s+(.+?)(?:\s+ki|\s+ku|\s+ela|\s+vellali|\s+వెళ్లాలి|\?|$)", user_query, re.IGNORECASE)
    if te_match:
        source = te_match.group(1).strip()
        dest = te_match.group(2).strip()

    # Hindi pattern: "<src> se <dst>" or "<src> से <dst>"
    if not source:
        hi_match = re.search(r"(.+?)(?:\s+से|\s+se)\s+(.+?)(?:\s+tak|\s+jana|\s+जाना|\?|$)", user_query, re.IGNORECASE)
        if hi_match:
            source = hi_match.group(1).strip()
            dest = hi_match.group(2).strip()

    # English pattern: "from <src> to <dst>"
    if not source:
        en_match = re.search(r"(?:from|board at)\s+(.+?)\s+(?:to|reach)\s+(.+?)(?:\?|\.|$)", user_query, re.IGNORECASE)
        if en_match:
            source = en_match.group(1).strip()
            dest = en_match.group(2).strip()

    # Direct bus question for previous context or detected locations
    if not source and not dest:
        # Check if caller mentions single stops
        resolved_stops = []
        for word in q_lower.replace("?", "").replace(".", "").split():
            st = engine.resolve_stop(word)
            if st and st.name not in [s.name for s in resolved_stops]:
                resolved_stops.append(st)

        if len(resolved_stops) >= 2:
            source = resolved_stops[0].name
            dest = resolved_stops[1].name

    # If both source and destination are found
    if source and dest:
        state.current_source = source
        state.current_destination = dest

        # Check if direct bus question
        is_direct_q = any(w in q_lower for w in ["direct", "డైరెక్ట్", "सीधी", "सीधा", "change", "బస్సు మారాలా"])

        routes = engine.find_routes(source, dest)
        if not routes:
            if detected_lang == SupportedLanguage.TE:
                reply = f"క్షమించండి, {source} మరియు {dest} మధ్య డెమో మార్గం లభించలేదు. దయచేసి సమీప ప్రధాన స్టాప్‌ను పేర్కొనండి."
            elif detected_lang == SupportedLanguage.HI:
                reply = f"माफ़ कीजिए, {source} और {dest} के बीच डेमो रूट नहीं मिला। कृपया किसी मुख्य स्टॉप का नाम बताएं।"
            else:
                reply = f"Sorry, no mock route found between {source} and {dest}. Please verify the stop names."
            return {"response": reply, "language": state.language.value, "detected_route": None}

        best = routes[0]
        state.last_route_id = best.legs[0].route_id

        summary_text = best.summary.get(state.language.value, best.summary["en"])

        # If specifically asking about direct bus
        if is_direct_q:
            if best.is_direct:
                if detected_lang == SupportedLanguage.TE:
                    prefix = f"అవును, డైరెక్ట్ బస్సు ఉంది! "
                elif detected_lang == SupportedLanguage.HI:
                    prefix = f"हाँ, सीधी बस उपलब्ध है! "
                else:
                    prefix = f"Yes, there is a direct bus! "
                reply = prefix + summary_text
            else:
                if detected_lang == SupportedLanguage.TE:
                    reply = f"డైరెక్ట్ బస్సు లేదు. మీరు బస్సు మారవలసి ఉంటుంది: " + summary_text
                elif detected_lang == SupportedLanguage.HI:
                    reply = f"सीधी बस नहीं है। आपको बस बदलनी होगी: " + summary_text
                else:
                    reply = f"No, there is no direct bus. You will need to transfer: " + summary_text
        else:
            reply = summary_text

        return {
            "response": reply,
            "language": state.language.value,
            "detected_route": best.model_dump(),
        }

    # 5. Default conversational fallback
    clarification = tool_clarify_stop(user_query)
    if detected_lang == SupportedLanguage.TE:
        fallback = f"నమస్కారం! మీరు ఏ స్టాప్ నుంచి ఎక్కడికి వెళ్లాలి? (ఉదాహరణకు: తుక్కుగూడ నుంచి మెహదీపట్నం). {clarification}"
    elif detected_lang == SupportedLanguage.HI:
        fallback = f"नमस्ते! आप किस स्टॉप से कहाँ जाना चाहते हैं? (उदाहरण के लिए: तुक्कुगुड़ा से मेहदीपट्टनम). {clarification}"
    else:
        fallback = f"Please tell me your starting stop and destination in Hyderabad (for example: from Tukkuguda to Mehdipatnam). {clarification}"

    return {"response": fallback, "language": state.language.value, "detected_route": None}


async def entrypoint(ctx: Any) -> None:
    """Main LiveKit Agents worker entrypoint."""
    logger.info("Connecting BusMate AI Voice Agent to LiveKit room...")

    try:
        # Check if livekit.agents is installed and active
        from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
        from livekit.plugins import google, silero

        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

        # Detect SIP caller identity and telephone metadata
        participant = await ctx.wait_for_participant()
        logger.info(f"Connected participant: {participant.identity}, kind: {participant.kind}")

        # Initialize voice pipeline using Gemini Live / Google LiveKit plugin
        # If API key is present, instantiate Gemini Live / Google LLM
        if GEMINI_API_KEY:
            gemini_model = google.LLM(
                model=GEMINI_MODEL,
                api_key=GEMINI_API_KEY,
            )
        else:
            logger.warning("No GEMINI_API_KEY found in environment. Using fallback voice responder.")
            gemini_model = None

        logger.info(f"BusMate AI initialized with voice: {GEMINI_VOICE}")

    except ImportError as e:
        logger.warning(f"LiveKit agents plugin optional dependency notice: {e}")
    except Exception as e:
        logger.error(f"Error initializing LiveKit session: {e}")


def run_agent() -> None:
    """Launches the LiveKit Agents worker process."""
    try:
        from livekit.agents import WorkerOptions, cli
        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
    except Exception as e:
        logger.error(f"Could not start LiveKit CLI: {e}")
        logger.info("Run in standalone simulation mode with: python -m src.agent --simulate")


if __name__ == "__main__":
    import sys
    if "--simulate" in sys.argv:
        print("=== BusMate AI Interactive Voice Simulation Console ===")
        print(OPENING_GREETING)
        session_id = "cli-session"
        while True:
            try:
                user_input = input("\nCaller: ")
                if user_input.strip().lower() in ("exit", "quit"):
                    print("Call ended. Dhanyavaadalu / Shukriya / Thank you for calling BusMate AI.")
                    break
                result = simulate_turn(user_input, session_id)
                print(f"BusMate AI ({result['language']}): {result['response']}")
            except (KeyboardInterrupt, EOFError):
                break
    else:
        run_agent()
