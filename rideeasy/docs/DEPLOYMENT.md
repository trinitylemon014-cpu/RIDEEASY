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

# Run database setup & seeding
python run.py
```
Open your browser at `http://127.0.0.1:5000` to interact with the live application.

---

## 2. Production Deployment (Linux / Ubuntu / Debian)

Before enabling payments, set deployment secrets outside source control:

```text
SECRET_KEY=<strong-random-secret>
FLASK_ENV=production
TURSO_DATABASE_URL=libsql://<database>.turso.io
TURSO_AUTH_TOKEN=<database-token>
PAYSTACK_SECRET_KEY=<Paystack-secret-key>
PAYSTACK_CALLBACK_URL=https://rideeasy.ug/payments/paystack/callback
PAYSTACK_CURRENCY=UGX
PAYSTACK_AMOUNT_MULTIPLIER=1
EGOSMS_API_URL=<configured-EgoSMS-compatible-endpoint>
EGOSMS_API_KEY=<SMS-provider-key>
LOCATIONIQ_API_KEY=<LocationIQ-server-key>
DRIVER_RIDE_OFFER_TIMEOUT_SECONDS=45
```

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
