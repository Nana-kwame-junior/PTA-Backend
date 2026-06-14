from app.core.database import SessionLocal
from app.models.user import User, UserRole
from app.core.security import hash_password

ADMIN_EMAIL = "admin@pta.com"
ADMIN_PASSWORD = "admin123"


def create_admin():
    db = SessionLocal()
    admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    if not admin:
        admin = User(
            name="PTA Admin",
            email=ADMIN_EMAIL,
            hashed_password=hash_password(ADMIN_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
            is_first_login=False,
        )
        db.add(admin)
        db.commit()
        print(f"Admin created: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    else:
        admin.hashed_password = hash_password(ADMIN_PASSWORD)
        admin.is_active = True
        db.commit()
        print(f"Admin password reset: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    db.close()


if __name__ == "__main__":
    create_admin()
