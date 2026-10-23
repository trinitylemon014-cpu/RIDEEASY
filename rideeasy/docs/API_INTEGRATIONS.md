# External API Integrations Specification
**RideEasy Platform — Emtrixz Technology Company**

## 1. Paystack ride payments
- Passenger checkout is initialized server-side at `POST /payments/paystack/checkout/<ride_id>` after a ride is completed.
- The provider's return URL and signed `POST /payments/paystack/webhook` are both verified against Paystack's transaction verification API. A browser redirect or submitted status is never treated as proof of payment.
- Required deployment settings: `PAYSTACK_SECRET_KEY`, `PAYSTACK_CALLBACK_URL` (public HTTPS URL ending in `/payments/paystack/callback`), and `SECRET_KEY`.
- Optional settings: `PAYSTACK_CURRENCY` (default `UGX`), `PAYSTACK_AMOUNT_MULTIPLIER` (default `1`), `PAYSTACK_COLLECTION_PHONE` (admin-visible contact/reference number), and `PAYSTACK_ADMIN_PAYOUT_PHONE`.
- Confirm that the Paystack merchant account is enabled for the configured currency and requested mobile-money/card channels. Confirm the currency's amount units with Paystack before live use; the default multiplier assumes UGX is passed as a whole shilling amount.
- The collection phone is a RideEasy contact/reference only. Paystack settlement destination is managed in the merchant dashboard; this application does not redirect settlements to a phone number.

### Payment ledger and payouts
- A successfully verified, completed ride is split into a 20% admin ledger credit and an 80% driver ledger credit (the driver’s registered number).
- RideEasy does not initiate mobile-money transfers. Admins must send payouts using their authorized provider and then record the confirmed transfer in **Admin → Payments & Payouts**. Ledger credits and manual payout confirmations are audited.
- Successful settlement awards exactly 100 passenger points once. A 5,000-point redemption creates a 25% voucher for one ride selected at booking.
- Webhook processing is idempotent and uses transactional database writes. Configure Turso with a transactional `libsql://`, `ws://`, or `wss://` URL; the HTTP-only `https://` client is not sufficient for payment settlement.

## 2. EgoSMS payment notifications
- The payment flow records an SMS delivery attempt for the admin, driver, and passenger. Failures and unconfigured delivery are visible on the admin payments page and can be retried there.
- Set `EGOSMS_API_URL` and `EGOSMS_API_KEY` in the deployment secret store. The configured endpoint must accept `POST` JSON `{"to": "<phone>", "message": "<text>"}` with an `Authorization: Bearer <key>` header and return a successful 2xx response.
- EgoSMS account credentials and a provider endpoint were not present in this repository. Confirm the account's actual API contract and configure an adapter/endpoint matching the contract before expecting SMS delivery.
- In-app notifications and database ledger entries do not depend on SMS delivery.

---

## 3. Map & Location Services (LocationIQ)
- The authenticated Route Map workspace is available to passengers, drivers, schools, and administrators at `/map`.
- Geocoding and driving directions are requested server-side from LocationIQ. Configure `LOCATIONIQ_API_KEY` in the deployment secret store; the credential is never included in browser HTML or JavaScript.
- The route page renders the returned road geometry with Leaflet and OpenStreetMap tiles. Route distance is the provider's driving distance, not the legacy straight-line fare estimate.
- Without a LocationIQ key, the map remains visible but route calculation returns an explicit configuration error. No inaccurate coordinates or distance fallback is presented as a verified route.
- Set provider timeouts, quota alerts, request budgets, and an appropriate LocationIQ plan before launch. Do not log API keys or raw provider URLs.
- The default OpenStreetMap tile endpoint is suitable for development and low-volume evaluation only. For production scale, use a contracted tile provider or self-hosted tile infrastructure, honor its caching and attribution terms, and monitor tile usage separately from routing usage.
- Route distance and time are planning estimates and do not account for live traffic. Continue to calculate booking fares through the existing fare-pricing service unless pricing is explicitly migrated to routed distance.

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
