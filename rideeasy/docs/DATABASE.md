# Turso Database Integration Guide
**RideEasy Platform — Emtrixz Technology Company**

## 1. Production Database: Turso (libSQL)
RideEasy uses **Turso** as its primary production database. Turso is an edge-hosted, SQLite-compatible database platform powered by **libSQL**.

### Python Driver
RideEasy integrates via the official `libsql-client` Python driver:
```python
import libsql_client

client = libsql_client.create_client_sync(
    url=os.getenv("TURSO_DATABASE_URL"),
    auth_token=os.getenv("TURSO_AUTH_TOKEN")
)
```

## 2. Environment Variables Configuration
To connect to your production Turso database instance:

```bash
# In your .env file:
TURSO_DATABASE_URL="libsql://your-database-name-organization.turso.io"
TURSO_AUTH_TOKEN="eyJhbGciOiJFZERTQ..."
SECRET_KEY="your-production-secret-key"
FLASK_ENV="production"
```

### Creating Turso Database & Generating Auth Tokens
Using the Turso CLI:
```bash
# 1. Install Turso CLI
curl -sSfL https://get.tur.so/install.sh | bash

# 2. Authenticate
turso auth login

# 3. Create RideEasy Database in Europe (London or Frankfurt nearest to Uganda)
turso db create rideeasy-db --location lhr

# 4. Generate persistent database authentication token
turso db tokens create rideeasy-db

# 5. Obtain database URL
turso db show rideeasy-db --url
```

## 3. Local Development Database
When `TURSO_DATABASE_URL` is omitted or empty, RideEasy initializes local SQLite (`rideeasy.db`). A configured Turso connection failure raises an error; RideEasy does not silently switch production traffic or payment records to a local file. Payment settlement requires a transactional `libsql://`, `ws://`, or `wss://` connection; the HTTP-only `https://` transport cannot atomically commit ledger entries.

## 4. Initial Administrator and Production Data
Production startup provisions `ADMIN_EMAIL` (default `admin@rideeasy.com`) with
`ADMIN_NAME` (default `katongole kylee`) when that account does not already
exist. Set `ADMIN_PASSWORD` in the deployment's secret store before the first
startup; only a password hash is stored. Existing built-in demo accounts and
their seeded sample records are removed during production initialization.
Sample users and journeys are created only by automated tests.

Render deployments must configure both `TURSO_DATABASE_URL` and
`TURSO_AUTH_TOKEN`. Startup fails if either is missing, preventing production
from silently using Render's non-persistent local filesystem.

## 5. Key Relational Tables & Constraints
- `users`: Core authentication identity with role enum check (`PASSENGER`, `DRIVER`, `SCHOOL`, `TRAVEL_COMPANY`, `ADMIN`).
- `driver_profiles` & `driver_documents`: National ID (NIN), permit, police clearances, rating aggregates.
- `vehicles`: License plates, seating capacities, vehicle types (`BODA`, `ECONOMY`, `COMFORT`, `PREMIUM`, `COASTER`, `BUS`).
- `school_transport_requests`: Institutional excursion bookings, assigned buses, agreed prices, invoices.
- `flight_requests`, `flight_quotations`, `flight_bookings`: Three-way aviation assistance workflow (inquiry → quotation → confirmed PNR).
- `confirmed_journeys` & `journey_reminders`: 5-tier scheduled notifications (7-day, 3-day, 2-day, 1-day, travel day).
- `rides` & `ride_ratings`: City trips with state-machine workflow, pricing configs, and driver reviews.
- `audit_logs`: Tamper-evident logging of administrative and operational actions.
