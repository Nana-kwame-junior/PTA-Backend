from datetime import datetime, timedelta
from typing import Optional
import jwt
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.jwt_access_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def create_refresh_token(data: dict):
    expire = datetime.utcnow() + timedelta(days=settings.jwt_refresh_expire_days)
    to_encode = data.copy()
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    payload = decode_token(token)
    user_id = payload.get("sub")
    role = payload.get("role")
    if role == "PARENT":
        # parent is stored in Parent model, not User
        from app.models.parent import Parent
        parent = db.query(Parent).filter(Parent.id == user_id).first()
        if not parent:
            raise HTTPException(status_code=401, detail="User not found")
        return {
            "id": parent.id,
            "role": "PARENT",
            "phone": parent.phone,
            "matched_student_ids": payload.get("matched_student_ids", []),
            "match_status": parent.match_status.value if parent.match_status else "PENDING"
        }
    else:
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return {
            "id": user.id,
            "role": user.role.value,
            "email": user.email,
            "name": user.name,
            "is_first_login": user.is_first_login
        }

def require_role(required_role: str):
    async def role_dependency(current_user = Depends(get_current_user)):
        if current_user["role"] != required_role:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return role_dependency

async def require_parent_match(current_user = Depends(get_current_user)):
    if current_user["role"] != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can access")
    if current_user["match_status"] != "MATCHED":
        raise HTTPException(status_code=403, detail="Parent account not matched to any ward")
    return current_user