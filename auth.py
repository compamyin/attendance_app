import base64
import hmac
import hashlib
import json
import time
from passlib.context import CryptContext
from config import JWT_SECRET

# ملاحظة مهمة:
# كنا نستخدم bcrypt، لكنه يسبب مشاكل على بعض بيئات ويندوز بسبب تعارض إصدارات مكتبة bcrypt.
# لذلك استخدمنا pbkdf2_sha256 (آمن ومناسب لتخزين PIN/Password) بدون اعتماد خارجي إضافي.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def hash_pin(pin: str) -> str:
    return pwd_context.hash(pin)

def verify_pin(pin: str, pin_hash: str) -> bool:
    return pwd_context.verify(pin, pin_hash)

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def _b64url_decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode())

def create_token(payload: dict, expires_in_seconds: int = 60 * 60 * 24 * 7) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = dict(payload)
    payload["exp"] = int(time.time()) + expires_in_seconds

    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()

    sig = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    s = _b64url(sig)
    return f"{h}.{p}.{s}"

def verify_token(token: str) -> dict | None:
    try:
        h, p, s = token.split(".")
        signing_input = f"{h}.{p}".encode()
        expected = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), s):
            return None

        payload = json.loads(_b64url_decode(p))
        if int(time.time()) > int(payload.get("exp", 0)):
            return None
        return payload
    except Exception:
        return None
