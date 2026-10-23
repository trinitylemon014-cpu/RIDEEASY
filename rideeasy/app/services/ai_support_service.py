import os
import re
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class AISupportService:
    """
    AI Customer Service Care Assistant for RideEasy & Emtrixz Technology Company.
    Uses Gemini 3.8 Flash (via google-genai SDK) with rich grounding in
    Ugandan transport tariffs, airport transfers, school charters, and trust standards.
    """

    MODEL_NAME = "gemini-3.8-flash"

    SYSTEM_INSTRUCTION = """You are the official RideEasy AI Customer Care Concierge, representing RideEasy and its parent company, Emtrixz Technology Company, headquartered in Kampala, Uganda.

Your role is to assist passengers, drivers, schools, and corporate clients with prompt, accurate, professional, and courteous guidance about RideEasy services, company background, and transport operations in Uganda.

KEY COMPANY & APP KNOWLEDGE:
1. Emtrixz Technology Company:
   - Premier Ugandan mobility and software technology company located in Kampala.
   - Founded to deliver safe, transparent, and multi-modal transport infrastructure across Uganda and East Africa.
   - Slogan: "MOVE. TRAVEL. ARRIVE."

2. City Ride Categories & Regulated Tariffs (all in Ugandan Shillings, UGX):
   - BODA (Motorcycle): Base UGX 1,500 | UGX 700/km | Min Fare UGX 2,500. Ideal for beating Kampala traffic jams.
   - ECONOMY (Saloon cars like Toyota Premio / Spacio): Base UGX 3,500 | UGX 1,500/km | Min Fare UGX 6,000.
   - COMFORT (Spacious AC sedans like Toyota Fielder / Axio): Base UGX 5,000 | UGX 2,200/km | Min Fare UGX 9,000.
   - PREMIUM (Executive SUVs like Toyota Land Cruiser Prado / Harrier): Base UGX 8,000 | UGX 3,200/km | Min Fare UGX 15,000.

3. Entebbe Airport (EBB) Transfers:
   - Dedicated direct transfers to/from Entebbe International Airport (EBB).
   - Standard fare from Central Kampala / Kololo to EBB is ~UGX 85,000.
   - Automated 5-stage flight countdown reminders (7-day passport check, 3-day airport ride booking, 2-day baggage rules, 24h online check-in, departure day reminder).

4. School Transport & Group Charters:
   - 28-seater Toyota Coasters and 60-passenger school buses for educational excursions and daily student transit.
   - Vetted drivers with clean records, on-board first-aid kits, speed limiters, and Ministry of Education & Sports compliance.

5. Flight Booking & Travel Partner Integration:
   - Partnered with licensed IATA travel agencies (such as Nile Equatorial Travel Agency Ltd) to request and issue genuine airline PNR tickets (Uganda Airlines, Emirates, Qatar Airways, etc.).

6. Payment Methods:
   - MTN Mobile Money (MoMo)
   - Airtel Money
   - Cash directly to the driver
   - Debit & Credit Cards (Visa, Mastercard)

7. Trust & Safety Standards:
   - 100% National ID (NIN) verification and Interpol certificates of good conduct for all drivers.
   - Periodic vehicle roadworthiness inspections.
   - In-app trip tracking, trip receipts, emergency contacts, and driver rating system.

8. Repeat Rides & Re-booking:
   - Passengers can view past completed rides on their dashboard and click "Request Repeat Ride" to instantly re-populate their pickup and destination coordinates.

9. Cancellation Policy:
   - Free cancellation before a driver is dispatched.
   - Once a driver has been dispatched and en route, direct in-app cancellation locks to protect drivers, but support can assist in case of genuine emergencies.

10. Support Contact:
    - Phone: +256 700 123 456 / +256 312 800 900
    - Email: support@rideeasy.ug / care@emtrixz.com
    - Office: Plot 14 Acacia Avenue & Nakasero Road, Kampala, Uganda.

GUIDELINES FOR YOUR RESPONSES:
- Maintain a warm, polite, and confident tone representing Ugandan hospitality.
- Quote prices clearly in UGX.
- Keep answers concise and readable. Use short paragraphs or bullet points where helpful.
- Answer directly without meta-commentary.
"""

    @classmethod
    def get_gemini_client(cls):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return None
        try:
            from google import genai
            return genai.Client(api_key=api_key)
        except Exception as e:
            logger.warning(f"Could not initialize google-genai Client: {e}")
            return None

    @classmethod
    def generate_reply(cls, user_message: str, chat_history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """
        Generate a customer care response using Gemini 3.8 Flash, or intelligent local knowledge engine if key/offline.
        """
        clean_prompt = (user_message or "").strip()
        if not clean_prompt:
            return {
                "success": False,
                "reply": "Please provide a question so our customer care team can assist you.",
                "source": "validation"
            }

        client = cls.get_gemini_client()
        if client:
            try:
                from google.genai import types
                
                # Build context
                contents = []
                if chat_history:
                    for turn in chat_history[-4:]:  # last 4 turns for context
                        role = "user" if turn.get("sender") == "user" else "model"
                        text = turn.get("text", "")
                        if text:
                            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))

                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=clean_prompt)]))

                response = client.models.generate_content(
                    model=cls.MODEL_NAME,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=cls.SYSTEM_INSTRUCTION,
                        temperature=0.3,
                        max_output_tokens=600
                    )
                )

                if response and response.text:
                    return {
                        "success": True,
                        "reply": response.text.strip(),
                        "model": cls.MODEL_NAME,
                        "source": "gemini"
                    }
            except Exception as e:
                logger.warning(f"Gemini API call failed, using intelligent local engine: {e}")

        # Intelligent local knowledge engine fallback
        fallback_reply = cls._get_knowledge_response(clean_prompt)
        return {
            "success": True,
            "reply": fallback_reply,
            "model": cls.MODEL_NAME,
            "source": "knowledge_engine"
        }

    @classmethod
    def _get_knowledge_response(cls, query: str) -> str:
        q = query.lower()

        # Fare / Pricing / Cost
        if any(w in q for w in ["fare", "pricing", "rate", "cost", "price", "calculate", "tariffs", "estimate"]):
            return (
                "**RideEasy Regulated Tariffs (UGX)**\n\n"
                "Our fares are calculated transparently based on route distance and category:\n"
                "• **Boda (Motorcycle)**: Base UGX 1,500 + UGX 700/km (Min fare UGX 2,500)\n"
                "• **Economy (Saloon)**: Base UGX 3,500 + UGX 1,500/km (Min fare UGX 6,000)\n"
                "• **Comfort (Sedan w/ AC)**: Base UGX 5,000 + UGX 2,200/km (Min fare UGX 9,000)\n"
                "• **Premium (Executive SUV)**: Base UGX 8,000 + UGX 3,200/km (Min fare UGX 15,000)\n\n"
                "You can test live estimates directly on your booking form before confirming."
            )

        # Emtrixz / About Company / Who founded / Ownership
        if any(w in q for w in ["emtrixz", "company", "who are you", "about", "founder", "headquarters", "location", "uganda"]):
            return (
                "**About RideEasy & Emtrixz Technology Company**\n\n"
                "RideEasy is developed and operated by **Emtrixz Technology Company**, a premier Ugandan mobility and software enterprise based in Kampala, Uganda.\n\n"
                "Our mission is encapsulated in our motto: **MOVE. TRAVEL. ARRIVE.** We provide a unified transportation platform uniting regulated city ride-hailing, dedicated Entebbe airport transfers, school coaster charters, and flight booking assistance under verified safety standards."
            )

        # Airport / Entebbe
        if any(w in q for w in ["airport", "entebbe", "ebb", "transfer", "flight", "plane", "terminal"]):
            return (
                "**Entebbe International Airport (EBB) Transfers**\n\n"
                "• RideEasy provides direct, comfortable airport transfers between Kampala/Greater Entebbe and EBB Terminal.\n"
                "• A standard transfer from Central Kampala/Kololo is approximately **UGX 85,000**.\n"
                "• When you link an airport ride to your journey, RideEasy activates our **5-stage countdown checklist** (passport checks, luggage limits, online check-in, and timely departure reminders)."
            )

        # Repeat Ride / Rebook
        if any(w in q for w in ["repeat", "again", "rebook", "history", "previous ride", "past ride", "completed"]):
            return (
                "**How to Request a Repeat Ride:**\n\n"
                "1. Go to your **Passenger Dashboard**.\n"
                "2. Scroll down to the **Recent Completed Rides** section.\n"
                "3. Find the completed trip you wish to repeat.\n"
                "4. Click the **'Request Repeat Ride'** button. This automatically pre-populates your pickup and destination locations with the latest fare calculation."
            )

        # Payment Methods
        if any(w in q for w in ["payment", "pay", "momo", "mtn", "airtel", "money", "cash", "card", "visa"]):
            return (
                "**Supported Payment Methods:**\n\n"
                "• **MTN Mobile Money (MoMo)**: Fast and cashless directly from your phone.\n"
                "• **Airtel Money**: Instant mobile wallet payments.\n"
                "• **Cash**: Pay directly in Ugandan Shillings (UGX) to your driver upon arrival.\n"
                "• **Credit / Debit Cards**: Secure Visa and Mastercard processing."
            )

        # Safety / Driver vetting / NIN
        if any(w in q for w in ["safe", "safety", "vet", "vetting", "driver", "nin", "police", "inspect", "security"]):
            return (
                "**Trust & Safety on RideEasy:**\n\n"
                "• **Driver Screening**: 100% verification with National ID (NIN), driving permit validity, and Interpol certificates of good conduct.\n"
                "• **Vehicle Standards**: Mandatory roadworthiness checks, clean interiors, and seat belts.\n"
                "• **Trip Security**: GPS journey tracking, automated digital receipts, and passenger rating feedback."
            )

        # School Transport / Coaster / Buses
        if any(w in q for w in ["school", "coaster", "bus", "charter", "student", "pupil"]):
            return (
                "**School & Institutional Transport:**\n\n"
                "RideEasy offers dedicated 28-seater Coasters and 60-seater buses for educational study tours, sports trips, and daily student transit with verified drivers, first-aid kits, speed limiters, and institutional invoicing."
            )

        # Cancellation Policy
        if any(w in q for w in ["cancel", "cancellation", "refund", "locked"]):
            return (
                "**Cancellation Policy:**\n\n"
                "• Free cancellation is permitted before a driver has been assigned and dispatched.\n"
                "• Once a driver is en route, in-app direct cancellation is locked to safeguard driver dispatch ethics. If an emergency occurs, contact our support team immediately at +256 700 123 456."
            )

        # Contact / Phone / Email / Support
        if any(w in q for w in ["contact", "phone", "email", "support", "call", "office", "reach", "help"]):
            return (
                "**Contact RideEasy Customer Support:**\n\n"
                "• **Toll-Free / Support Line**: +256 700 123 456 / +256 312 800 900\n"
                "• **Support Email**: support@rideeasy.ug\n"
                "• **Corporate Inquiries**: care@emtrixz.com\n"
                "• **Office**: Nakasero Road & Plot 14 Acacia Avenue, Kampala, Uganda\n"
                "• **Hours**: 24/7 Operations Desk"
            )

        # General welcoming fallback
        return (
            "Hello! I am the **RideEasy AI Customer Care Concierge** by **Emtrixz Technology Company** in Kampala, Uganda.\n\n"
            "I can assist you with:\n"
            "• **City Rides & Fares**: Boda, Economy, Comfort, and Premium tariffs in UGX.\n"
            "• **Airport Transfers**: Direct trips to Entebbe Airport (EBB) and flight countdown reminders.\n"
            "• **Repeat Rides**: Re-booking past journeys with one click.\n"
            "• **School Charters**: Coaster and bus bookings for groups and schools.\n"
            "• **Payments & Safety**: MTN MoMo, Airtel Money, driver NIN vetting, and vehicle inspections.\n\n"
            "How may I help you today?"
        )
