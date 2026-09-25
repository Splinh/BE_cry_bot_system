"""
Authentication Module - JWT + SQLite
Register (pending approval), Login, Get current user
"""
import os
import json
import time
import hashlib
import secrets
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from loguru import logger

# JWT
try:
    from jose import jwt, JWTError
except ImportError:
    from jose import jwt, JWTError

from data.database import db

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ============================================
#  CONFIG
# ============================================

JWT_SECRET = os.getenv("JWT_SECRET", "crypto-bot-super-secret-key-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

def hash_password(password: str) -> str:
    """Hash password su dung bcrypt."""
    return pwd_context.hash(password)

def verify_password(password: str, stored_hash: str) -> bool:
    """Xac thuc mat khau voi ho tro ca bcrypt va legacy sha256."""
    try:
        if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
            return pwd_context.verify(password, stored_hash)
        # Fallback ho tro legacy format: salt$sha256
        if "$" in stored_hash:
            salt, hashed = stored_hash.split("$", 1)
            return hashlib.sha256((salt + password).encode()).hexdigest() == hashed
    except Exception:
        return False
    return False

security_scheme = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ============================================
#  MODELS
# ============================================

class RegisterReq(BaseModel):
    username: str
    email: Optional[str] = ""
    password: str

class LoginReq(BaseModel):
    username: str
    password: str

# ============================================
#  HELPERS
# ============================================

def create_token(user_id: int, username: str, role: str) -> str:
    """Tao JWT access token."""
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": int(time.time()) + JWT_EXPIRE_HOURS * 3600,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(token: str) -> dict:
    """Giai ma va xac thuc JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("exp", 0) < time.time():
            raise HTTPException(401, "Token da het han")
        return payload
    except JWTError:
        raise HTTPException(401, "Token khong hop le hoac bi tu choi")

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme)
) -> dict:
    """FastAPI dependency: lay user tu JWT token va bat buoc kiem tra is_active/status."""
    if not credentials:
        raise HTTPException(401, "Chua dang nhap (thieu Bearer token)")
    
    payload = verify_token(credentials.credentials)
    user_id = int(payload.get("sub", 0))
    
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "Tai khoan khong ton tai")
    
    if not user.get("is_active"):
        raise HTTPException(403, "Tai khoan da bi khoa hoac vo hieu hoa")
        
    if user.get("status") not in ("approved", "active"):
        raise HTTPException(403, f"Tai khoan dang o trang thai '{user.get('status')}', chua duoc chap thuan")
    
    return user

def require_permission(permission: str):
    """Dependency kiem tra user co quyen permission cu the hoac la admin."""
    async def _checker(user: dict = Depends(get_current_user)):
        if user.get("role") == "admin":
            return user
        perms = parse_permissions(user)
        if permission not in perms:
            raise HTTPException(403, f"Ban khong co quyen truy cap '{permission}'")
        return user
    return _checker

async def require_admin(
    user: dict = Depends(get_current_user)
) -> dict:
    """Dependency: require admin role."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Ban khong co quyen admin")
    return user

def parse_permissions(user: dict) -> list:
    """Parse permissions JSON string to list."""
    perms = user.get("permissions", "[]")
    if isinstance(perms, str):
        try:
            return json.loads(perms)
        except Exception:
            return []
    return perms if isinstance(perms, list) else []

# ============================================
#  ENDPOINTS
# ============================================

@router.post("/register")
def register(req: RegisterReq):
    """Dang ky tai khoan moi - status = pending, cho admin duyet."""
    if len(req.username) < 3:
        raise HTTPException(400, "Username toi thieu 3 ky tu")
    if len(req.password) < 6:
        raise HTTPException(400, "Mat khau toi thieu 6 ky tu")
    
    # Check trung
    existing = db.get_user_by_username(req.username)
    if existing:
        raise HTTPException(400, "Username da ton tai")
    
    # Hash password
    password_hash = hash_password(req.password)
    
    # Create user -> status=pending, role=user
    user = db.create_user(
        username=req.username,
        email=req.email or "",
        password_hash=password_hash,
        role="user",
        status="pending"
    )
    
    if not user:
        raise HTTPException(500, "Loi tao tai khoan")
    
    logger.info(f"[AUTH] New registration (pending): {user['username']}")
    
    return {
        "success": True,
        "pending": True,
        "message": "Tài khoản đã được tạo và đang chờ admin duyệt. Vui lòng liên hệ admin để được kích hoạt.",
    }

@router.post("/login")
def login(req: LoginReq):
    """Dang nhap va nhan JWT token."""
    user = db.get_user_by_username(req.username)
    
    if not user:
        raise HTTPException(401, "Sai username hoac mat khau")
    
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Sai username hoac mat khau")
    
    # Check status
    status = user.get("status", "approved")
    if status == "pending":
        raise HTTPException(403, "Tài khoản đang chờ admin duyệt. Vui lòng chờ.")
    if status == "rejected":
        raise HTTPException(403, "Tài khoản đã bị từ chối. Liên hệ admin.")
    
    if not user.get("is_active", True):
        raise HTTPException(403, "Tai khoan bi khoa")
    
    token = create_token(user["id"], user["username"], user["role"])
    
    logger.info(f"[AUTH] Login: {user['username']}")
    
    permissions = parse_permissions(user)
    
    return {
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user.get("email", ""),
            "role": user["role"],
            "status": user.get("status", "approved"),
            "permissions": permissions,
        }
    }

@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Lay thong tin user hien tai tu token."""
    permissions = parse_permissions(user)
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user.get("email", ""),
        "role": user["role"],
        "status": user.get("status", "approved"),
        "permissions": permissions,
        "created_at": user.get("created_at", ""),
    }
