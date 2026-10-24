# RideEasy — Professional Transportation & Travel Platform
> **MOVE. TRAVEL. ARRIVE.**  
> Developed by **Emtrixz Technology Company** for Uganda and expanding East African markets.

---

## 1. Executive Summary

RideEasy is a unified African mobility and travel application built using **Python, Flask, Jinja2, HTML5, CSS3, vanilla JavaScript**, and **Turso (libSQL)**.

The platform provides four core services:
1. **City Ride-Hailing**: Boda, Economy, Comfort, and Premium point-to-point urban transport with vetted drivers and regulated tariffs in Ugandan Shillings (UGX).
2. **School Transport Charter**: Dedicated institutional portal for schools to charter certified 30-seater Coasters and 60-seater Buses with background-checked drivers. Parents do not book directly.
3. **Flight Booking Assistance**: Passenger inquiries routed to accredited IATA travel partner agencies who issue authentic PNR bookings.
4. **Automated 5-Tier Travel Reminders**: 7-day passport checks, 3-day airport transfers, 2-day baggage prep, 1-day online check-in, and travel day flight alerts.

---

## 2. Technology Stack & Strict Rules

- **Backend**: Python 3.10+, Flask, Jinja2, Werkzeug (PBKDF2 password security).
- **Frontend**: HTML5, Modern CSS3, Vanilla JavaScript (ES2022). **No React, No Vue, No Angular, No third-party UI frameworks.**
- **Aesthetic**: Minimalist monochrome black-and-white (`#000000`, `#111111`, `#FFFFFF`, `#F7F7F7`, `#E5E5E5`, `#777777`).
- **Icons**: 100% black SVG line icons. **Strictly zero emojis or candy pills.**
- **Database**: **Turso** edge-hosted libSQL as primary production database, with local SQLite for development. A configured but unavailable Turso database fails closed; it never silently falls back for payment records.
- **Mobile**: Progressive Web App (PWA) with manifest & service worker, ready for native Android & iOS bundling via **Capacitor**.

---

## 3. How to Run Locally in VS Code

```bash
# 1. Clone or open the repository in VS Code
cd rideeasy

# 2. Create and activate a Python virtual environment
python3 -m venv venv
source venv/bin/activate       # macOS / Linux
# or: venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set a private SECRET_KEY in your environment (required)
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export FLASK_ENV=development
# For production, also configure Turso, Paystack, callback URL, and EgoSMS secrets.
# See docs/API_INTEGRATIONS.md and docs/DEPLOYMENT.md.

# 5. Launch the application
python run.py
```

The platform will automatically initialize tables, seed demo data, and start on `http://127.0.0.1:5000`. Payment checkout is disabled until a Paystack secret and public HTTPS callback URL are configured.

---

## 4. Demo Accounts & Credentials

RideEasy includes a 1-click **Demo Switcher** at the top of every screen. You can also sign in manually using:

| Role | Email Address | Password | Profile Overview |
| :--- | :--- | :--- | :--- |
| **Passenger** | `passenger@rideeasy.ug` | `password123` | Grace Namubiru (Kololo, Kampala) |
| **Driver** | `driver@rideeasy.ug` | `password123` | David Okello (Toyota Premio `UBD 204K`) |
| **School** | `school@rideeasy.ug` | `password123` | Greenhill Academy Kibuli (Charter Coasters/Buses) |
| **Travel Partner** | `travel@rideeasy.ug` | `password123` | Nile Equatorial Travel Ltd (IATA Accredited Agency) |
| **Administrator** | `admin@rideeasy.ug` | `admin123` | Arthur Katende (Operations Director) |

---

## 5. Running the Test Suite

```bash
python3 -m pytest tests
```
The test suite validates authentication, role-based access control, database seeding, LocationIQ road-route fare estimates and server-recalculated bookings, Paystack payment verification and idempotent ledger allocation, school transport restrictions, and aviation PNR confirmation workflows.

---

## 6. Directory Structure

```
rideeasy/
├── app/
│   ├── config.py                # Environment and app configuration
│   ├── __init__.py              # Flask app factory, filters, blueprints
│   ├── repositories/
│   │   └── database.py          # Unified Turso libSQL & SQLite layer
│   ├── services/
│   │   ├── auth_service.py      # RBAC & password hashing
│   │   ├── pricing_service.py   # Configurable tariffs applied to routed distance and duration
│   │   ├── reminder_service.py  # 5-tier travel reminder scheduler
│   │   ├── payment_service.py   # Paystack verification, settlement ledger & rewards
│   │   └── sms_service.py       # EgoSMS-compatible payment message delivery
│   ├── routes/
│   │   ├── main.py              # Homepage, about, pricing, safety, contact
│   │   ├── auth.py              # Login, register, demo switchers
│   │   ├── passenger.py         # Passenger booking, receipts, journeys
│   │   ├── driver.py            # Driver console, trip transitions
│   │   ├── school.py            # School coaster & bus bookings
│   │   ├── travel_partner.py    # Travel partner quotations & PNR bookings
│   │   ├── admin.py             # Operations control desk & audit logs
│   │   └── api.py               # JSON fare estimation & status polling
│   ├── static/
│   │   ├── css/                 # base.css, components.css, dashboard.css, responsive.css
│   │   ├── js/app.js            # Vanilla JS application scripts
│   │   └── manifest.json        # PWA web manifest
│   └── templates/               # Jinja2 HTML templates
├── database/
│   ├── schema/schema.sql        # Turso & SQLite schema
│   └── migrations/seed_data.py  # Ugandan transportation fixtures & demo accounts
├── docs/                        # Complete architecture, database, security, and packaging guides
├── tests/                       # Comprehensive pytest suite
├── requirements.txt
├── run.py
├── wsgi.py
└── README.md
```
