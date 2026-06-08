from app.core.database import SessionLocal
from app.models.user import User, UserRole
from app.core.security import hash_password

def create_admin():
    db = SessionLocal()
    admin = db.query(User).filter(User.email == "admin@mawulishs.edu.gh").first()
    if not admin:
        admin = User(
            name="System Admin",
            email="admin@mawulishs.edu.gh",
            hashed_password=hash_password("Admin@123"),
            role=UserRole.ADMIN,
            is_active=True,
            is_first_login=True
        )
        db.add(admin)
        db.commit()
        print("Admin user created.")
    else:
        print("Admin already exists.")
    db.close()

if __name__ == "__main__":
    create_admin()