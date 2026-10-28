"""LiveKit SIP Telephony Integration for BusMate AI.

Manages inbound phone calls, SIP trunking configuration, dispatch rules,
and caller metadata extraction for Hyderabad TGSRTC voice queries.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("busmate.telephony")


@dataclass
class CallerSession:
    """Represents an active or historical telephone caller session."""
    call_id: str
    caller_phone: str
    inbound_phone: str
    room_name: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    language_code: str = "en"
    detected_language: Optional[str] = None
    query_history: list = field(default_factory=list)
    call_status: str = "active"


class SIPTelephonyManager:
    """Manages LiveKit SIP Inbound Trunks, Dispatch Rules, and Telephone Call Sessions."""

    def __init__(
        self,
        sip_phone_number: str = "+91-40-MOCKBUS",
        trunk_id: str = "ST_mock_tgsrtc_inbound",
        dispatch_rule_id: str = "DR_mock_dispatch",
    ):
        self.sip_phone_number = sip_phone_number
        self.trunk_id = trunk_id
        self.dispatch_rule_id = dispatch_rule_id
        self.active_sessions: Dict[str, CallerSession] = {}

    def parse_sip_participant_metadata(
        self, participant_identity: str, participant_metadata: Optional[str] = None
    ) -> Dict[str, Any]:
        """Extracts caller phone number, trunk details, and SIP headers from LiveKit participant."""
        data = {
            "caller_phone": "Unknown Caller",
            "inbound_phone": self.sip_phone_number,
            "call_id": participant_identity,
            "sip_headers": {},
        }

        # Check standard LiveKit SIP identity convention: sip_<phone_number>
        if participant_identity.startswith("sip_"):
            data["caller_phone"] = participant_identity.replace("sip_", "")
        elif participant_identity.startswith("+"):
            data["caller_phone"] = participant_identity

        if participant_metadata:
            try:
                meta = json.loads(participant_metadata)
                if isinstance(meta, dict):
                    data.update(meta)
                    if "sip.callID" in meta:
                        data["call_id"] = meta["sip.callID"]
                    if "sip.phoneNumber" in meta:
                        data["caller_phone"] = meta["sip.phoneNumber"]
                    if "sip.trunkPhoneNumber" in meta:
                        data["inbound_phone"] = meta["sip.trunkPhoneNumber"]
            except Exception as e:
                logger.warning(f"Could not parse participant metadata as JSON: {e}")

        return data

    def register_call(
        self,
        call_id: str,
        caller_phone: str,
        room_name: str,
        inbound_phone: Optional[str] = None,
    ) -> CallerSession:
        """Registers a new inbound telephone call session."""
        session = CallerSession(
            call_id=call_id,
            caller_phone=caller_phone,
            inbound_phone=inbound_phone or self.sip_phone_number,
            room_name=room_name,
        )
        self.active_sessions[call_id] = session
        logger.info(f"Registered inbound SIP call {call_id} from {caller_phone} into {room_name}")
        return session

    def get_session(self, call_id: str) -> Optional[CallerSession]:
        """Retrieves active telephone session by call ID."""
        return self.active_sessions.get(call_id)

    def record_query(self, call_id: str, query: str, response: str, language: str) -> None:
        """Logs a query and response in the caller's session history."""
        session = self.get_session(call_id)
        if session:
            session.language_code = language
            session.query_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "query": query,
                "response": response,
                "language": language,
            })

    def end_call(self, call_id: str) -> Optional[CallerSession]:
        """Marks a telephone call session as completed."""
        session = self.active_sessions.get(call_id)
        if session:
            session.call_status = "ended"
            logger.info(f"SIP Call {call_id} ended. Total queries: {len(session.query_history)}")
        return session

    def generate_livekit_sip_trunk_config(self) -> Dict[str, Any]:
        """Generates the LiveKit SIP Inbound Trunk configuration JSON."""
        return {
            "sip_trunk": {
                "name": "TGSRTC BusMate Inbound Trunk",
                "numbers": [self.sip_phone_number],
                "inbound_addresses": ["sip.livekit.cloud"],
                "metadata": {
                    "application": "BusMate AI",
                    "region": "Hyderabad / Telangana",
                    "mock_mode": True,
                },
            }
        }

    def generate_livekit_dispatch_rule_config(self) -> Dict[str, Any]:
        """Generates the LiveKit SIP Dispatch Rule configuration JSON."""
        return {
            "sip_dispatch_rule": {
                "name": "BusMate AI Dispatch Rule",
                "trunk_ids": [self.trunk_id],
                "rule": {
                    "dispatch_rule_individual": {
                        "room_prefix": "busmate-call-",
                        "pin": "",
                    }
                },
                "metadata": {
                    "agent_name": "busmate-agent",
                    "languages_supported": ["en", "te", "hi"],
                },
            }
        }

    def generate_twilio_twiml(self, livekit_sip_uri: str) -> str:
        """Generates TwiML for routing Twilio inbound phone calls to LiveKit SIP trunk."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <!-- BusMate AI Telephone Gateway -->
    <Say voice="Polly.Aditi" language="en-IN">Connecting to BusMate AI Hyderabad Bus Assistant.</Say>
    <Dial>
        <Sip>{livekit_sip_uri}</Sip>
    </Dial>
</Response>"""
