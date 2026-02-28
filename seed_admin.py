from db import SessionLocal
from models import User
from auth import hash_password, hash_pin

USERNAME = "att_user"
PASSWORD = "2222"
PIN = "1234"

db = SessionLocal()
u = db.query(User).filter(User.username == USERNAME).first()
if not u:
    u = User(username=USERNAME, role="ADMIN", is_active=True)
    db.add(u)

u.password_hash = hash_password(PASSWORD)
u.pin_hash = hash_pin(PIN)

db.commit()
print("DONE")
