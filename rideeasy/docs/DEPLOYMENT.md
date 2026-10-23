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
