"""Configuration settings for BusMate AI."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# Data file paths
STOPS_FILE = DATA_DIR / "stops.json"
ROUTES_FILE = DATA_DIR / "routes.json"
ALIASES_FILE = DATA_DIR / "aliases.json"

# LiveKit Configuration
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://busmate-project.livekit.cloud")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")

# Gemini API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Puck")  # Warm, responsive voice

# Telephony & SIP Configuration
SIP_PHONE_NUMBER = os.getenv("SIP_PHONE_NUMBER", "+91-40-MOCKBUS")
SIP_TRUNK_ID = os.getenv("SIP_TRUNK_ID", "ST_mock_tgsrtc_inbound")
SIP_DISPATCH_RULE_ID = os.getenv("SIP_DISPATCH_RULE_ID", "DR_mock_dispatch")

# Application Settings
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DEBUG = os.getenv("DEBUG", "true").lower() in ("true", "1", "yes")

# Mock Disclaimer Banner
DISCLAIMER_TEXT = "Demonstration data only. Not verified TGSRTC bus information."
