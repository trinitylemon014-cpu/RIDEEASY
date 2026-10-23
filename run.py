import os
import sys

# Add rideeasy to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "rideeasy"))

from app import create_app
from app.config import Config

app = create_app(Config)

if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    
    print(f"Starting RideEasy on http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)
