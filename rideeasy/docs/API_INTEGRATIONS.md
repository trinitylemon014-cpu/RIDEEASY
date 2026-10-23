# External API Integrations Specification
**RideEasy Platform — Emtrixz Technology Company**

## 1. MTN Mobile Money (MoMo)
- **API Version**: MTN MoMo Open API v1.0
- **Use Cases**:
  - RequestToPay (Passenger fare collection)
  - Transfer (Driver weekly earnings disbursement)
- **Credentials Required**:
  - `MTN_MOMO_PRIMARY_KEY`
  - `MTN_MOMO_API_USER`
  - `MTN_MOMO_API_KEY`
  - `MTN_MOMO_TARGET_ENVIRONMENT` (`sandbox` or `live`)
- **Workflow**:
  1. RideEasy server sends `POST /collection/v1_0/requesttopay` with amount in UGX and customer MSISDN.
  2. Customer receives USSD prompt on their handset to enter MoMo PIN.
  3. MTN invokes RideEasy webhook callback with transaction confirmation code.

---

## 2. Airtel Money
- **API Version**: Airtel Africa Developer Portal v2.0
- **Use Cases**: Push USSD debit, B2C driver payouts.
- **Credentials Required**:
  - `AIRTEL_MONEY_CLIENT_ID`
  - `AIRTEL_MONEY_CLIENT_SECRET`
  - `AIRTEL_MONEY_COUNTRY` (`UG`)
  - `AIRTEL_MONEY_CURRENCY` (`UGX`)

---

## 3. Map & Location Services (Google Maps / Mapbox)
- **Primary Provider**: Google Maps Platform (Distance Matrix, Geocoding, Directions API).
- **Secondary / Offline Fallback**: Haversine formula + Uganda road network multiplier (currently active by default).
- **Enabling Live Google Maps**:
  - Provide `GOOGLE_MAPS_API_KEY` in `.env`.
  - Maps JavaScript SDK will render interactive road map with pickup and destination pins.

---

## 4. Aviation GDS & Partner Travel Agencies
- **Architecture**: Rather than claiming unauthorized direct ticket issuance, RideEasy dispatches flight requests to certified IATA partner travel agencies (such as Nile Equatorial Travel Ltd).
- **Partner Handshake**:
  1. Agency receives passenger flight request in their dashboard.
  2. Agency queries GDS (Amadeus, Sabre, or Travelport) for live inventory.
  3. Agency submits quotation via RideEasy.
  4. Passenger accepts quotation.
  5. Agency books ticket in GDS and registers official 6-character PNR reference.
  6. RideEasy initiates automated 5-stage passenger travel reminders and airport transfers.
