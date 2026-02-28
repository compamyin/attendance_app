from db import SessionLocal
from models import User
from auth import hash_pin

db = SessionLocal()

admin = User(
    username="2444",
    password_hash=hash_pin("2222"),
    pin_hash=hash_pin("1234"),
    role="ADMIN",
    is_active=True
)

db.add(admin)
db.commit()

print("ADMIN CREATED")
