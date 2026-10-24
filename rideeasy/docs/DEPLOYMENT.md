# Deployment & Operations Guide
**RideEasy Platform — Emtrixz Technology Company**

## 1. Local Development Setup (VS Code)

### Prerequisites
- Python 3.10 or higher
- pip (Python package installer)
- Git

### Quickstart Commands
```bash
# Clone and enter directory
cd rideeasy

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure local development secrets (keep these out of Git)
export FLASK_ENV=development
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_PASSWORD="<initial-admin-password>"

# Run database setup and administrator provisioning
python run.py
```
Open your browser at `http://127.0.0.1:5000` to interact with the live application.

---

## 2. Production Deployment on Render

The repository includes a Render Blueprint at `render.yaml`. Create a Blueprint
deployment from this repository and provide these values when prompted:

- `TURSO_DATABASE_URL`: the database URL from Turso (use `libsql://` for
  transactional payment support).
- `TURSO_AUTH_TOKEN`: a token generated for the database.
- `ADMIN_PASSWORD`: the initial password for `admin@rideeasy.com`.

The Blueprint generates `SECRET_KEY` and configures `ADMIN_EMAIL=admin@rideeasy.com`
and `ADMIN_NAME=katongole kylee`. Keep `ADMIN_PASSWORD`, `TURSO_AUTH_TOKEN`, and
other credentials in Render's environment settings, never in Git. On first
startup, the app creates the admin account and hashes the configured password.
Production refuses to start without Turso URL/token and admin password, and
never stores persistent user or payment data in Render's ephemeral filesystem.

Create the Turso database and token as described in
[docs/DATABASE.md](./DATABASE.md), then enter those values in Render. After
deployment, verify the service logs and sign in using the configured admin email
and password.

## 3. Production Deployment (Linux / Ubuntu / Debian)

Before enabling payments, set deployment secrets outside source control:

```text
SECRET_KEY=<strong-random-secret>
FLASK_ENV=production
TURSO_DATABASE_URL=libsql://<database>.turso.io
TURSO_AUTH_TOKEN=<database-token>
ADMIN_EMAIL=admin@rideeasy.com
ADMIN_NAME=katongole kylee
ADMIN_PASSWORD=<initial-admin-password>
PAYSTACK_SECRET_KEY=<Paystack-secret-key>
PAYSTACK_CALLBACK_URL=https://rideeasy.ug/payments/paystack/callback
PAYSTACK_CURRENCY=UGX
PAYSTACK_AMOUNT_MULTIPLIER=1
EGOSMS_API_URL=<configured-EgoSMS-compatible-endpoint>
EGOSMS_API_KEY=<SMS-provider-key>
LOCATIONIQ_API_KEY=<LocationIQ-server-key>
CLOUDINARY_CLOUD_NAME=<Cloudinary-cloud-name>
CLOUDINARY_API_KEY=<Cloudinary-api-key>
CLOUDINARY_API_SECRET=<Cloudinary-api-secret>
DRIVER_RIDE_OFFER_TIMEOUT_SECONDS=45
```

Profile pictures and driver vehicle photos are resized, re-encoded, and stripped of
EXIF/location metadata before upload to Cloudinary. Configure the three Cloudinary
secrets above in the deployment secret store. New photo uploads fail visibly when
Cloudinary is not configured; existing profile URLs and legacy database-stored vehicle
photos remain available. Vehicle images are served through the authenticated RideEasy
photo route, which checks that the passenger is matched to the driver.

Register `https://rideeasy.ug/payments/paystack/webhook` in the Paystack dashboard. Confirm Uganda, UGX, the merchant's supported payment channels, and the currency amount units with Paystack before live transactions. The application records manual payout credits; it does not transfer funds to mobile numbers automatically. EgoSMS is not considered active until its real API contract and credentials are configured.

### Using Gunicorn and Systemd
1. Install Gunicorn and dependencies:
   ```bash
   pip install gunicorn
   ```
2. Run with Gunicorn WSGI:
   ```bash
   gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app
   ```
3. Nginx Reverse Proxy:
   ```nginx
   server {
       listen 80;
       server_name rideeasy.ug www.rideeasy.ug;

       location / {
           proxy_pass http://127.0.0.1:5000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```
