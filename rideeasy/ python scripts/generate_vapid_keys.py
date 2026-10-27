"""Generate a VAPID key pair for Web Push.

Usage:  python scripts/generate_vapid_keys.py
Then set VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY in your Render environment.
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


private_key = ec.generate_private_key(ec.SECP256R1())
private_number = private_key.private_numbers().private_value.to_bytes(32, "big")
public_bytes = private_key.public_key().public_bytes(
    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
)
print("VAPID_PUBLIC_KEY=" + b64url(public_bytes))
print("VAPID_PRIVATE_KEY=" + b64url(private_number))
