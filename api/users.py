"""
User Management API - Admin only
CRUD operations for user accounts, approval, permissions.
"""
import json
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from loguru import logger

from data.database import db
from api.auth import get_current_user, require_admin, parse_permissions

router = APIRouter(prefix="/api/users", tags=["users"])

# ============================================
#  MODELS
# ============================================

class UpdatePermissionsReq(BaseModel):
    permissions: List[str]

class UpdateRoleReq(BaseModel):
    role: str  # "admin" or "user"

# ============================================
#  AVAILABLE PERMISSIONS (for frontend reference)
# ============================================

AVAILABLE_PERMISSIONS = [
    {"key": "overview", "label": "Overview", "description": "Dashboard tổng quan"},
    {"key": "trading", "label": "Đặt Lệnh", "description": "Paper trading"},
    {"key": "analysis", "label": "Phân Tích", "description": "Technical analysis"},
    {"key": "social", "label": "Social Airdrop", "description": "Bot-net social"},
    {"key": "wallets", "label": "Wallets", "description": "Quản lý ví"},
    {"key": "gems", "label": "Gem Scanner", "description": "DEX gem scanner"},
    {"key": "gamefi", "label": "GameFi", "description": "GameFi tracker"},
    {"key": "security", "label": "Security", "description": "Cài đặt bảo mật"},
]

# ============================================
#  ENDPOINTS (Admin only)
# ============================================

@router.get("")
async def list_users(
    status: Optional[str] = None,
    admin: dict = Depends(require_admin)
):
    """Danh sach tat ca users (admin only)."""
    users = db.get_all_users(status_filter=status)
    result = []
    for u in users:
        result.append({
            "id": u["id"],
            "username": u["username"],
            "email": u.get("email", ""),
            "role": u["role"],
            "status": u.get("status", "approved"),
            "permissions": parse_permissions(u),
            "is_active": bool(u.get("is_active", True)),
            "approved_by": u.get("approved_by"),
            "created_at": u.get("created_at", ""),
        })
    return {
        "users": result,
        "total": len(result),
        "available_permissions": AVAILABLE_PERMISSIONS,
    }

@router.put("/{user_id}/approve")
async def approve_user(user_id: int, admin: dict = Depends(require_admin)):
    """Duyet tai khoan user."""
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User khong ton tai")
    
    if target.get("status") == "approved":
        raise HTTPException(400, "User da duoc duyet roi")
    
    # Approve and give default permissions
    db.update_user_status(user_id, "approved", approved_by=admin["id"])
    default_perms = ["overview"]  # Only overview by default
    db.update_user_permissions(user_id, default_perms)
    
    logger.success(f"[USERS] Admin '{admin['username']}' approved user #{user_id}")
    return {"success": True, "message": "Da duyet tai khoan"}

@router.put("/{user_id}/reject")
async def reject_user(user_id: int, admin: dict = Depends(require_admin)):
    """Tu choi tai khoan user."""
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User khong ton tai")
    
    if target["id"] == admin["id"]:
        raise HTTPException(400, "Khong the tu choi chinh minh")
    
    db.update_user_status(user_id, "rejected", approved_by=admin["id"])
    
    logger.info(f"[USERS] Admin '{admin['username']}' rejected user #{user_id}")
    return {"success": True, "message": "Da tu choi tai khoan"}

@router.put("/{user_id}/permissions")
async def update_permissions(
    user_id: int,
    req: UpdatePermissionsReq,
    admin: dict = Depends(require_admin)
):
    """Cap nhat permissions cho user."""
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User khong ton tai")
    
    # Validate permissions
    valid_keys = [p["key"] for p in AVAILABLE_PERMISSIONS]
    invalid = [p for p in req.permissions if p not in valid_keys and p != "users"]
    if invalid:
        raise HTTPException(400, f"Invalid permissions: {invalid}")
    
    db.update_user_permissions(user_id, req.permissions)
    
    logger.info(f"[USERS] Updated permissions for user #{user_id}: {req.permissions}")
    return {"success": True, "permissions": req.permissions}

@router.put("/{user_id}/role")
async def update_role(
    user_id: int,
    req: UpdateRoleReq,
    admin: dict = Depends(require_admin)
):
    """Doi role cho user (admin/user)."""
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User khong ton tai")
    
    if target["id"] == admin["id"]:
        raise HTTPException(400, "Khong the doi role chinh minh")
    
    if req.role not in ("admin", "user"):
        raise HTTPException(400, "Role phai la 'admin' hoac 'user'")
    
    db.update_user_role(user_id, req.role)
    
    # If promoting to admin, give all permissions
    if req.role == "admin":
        all_perms = [p["key"] for p in AVAILABLE_PERMISSIONS] + ["users"]
        db.update_user_permissions(user_id, all_perms)
    
    logger.info(f"[USERS] Changed role for user #{user_id} -> {req.role}")
    return {"success": True, "role": req.role}

@router.put("/{user_id}/toggle-active")
async def toggle_active(user_id: int, admin: dict = Depends(require_admin)):
    """Khoa/Mo khoa user."""
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User khong ton tai")
    
    if target["id"] == admin["id"]:
        raise HTTPException(400, "Khong the khoa chinh minh")
    
    db.toggle_user_active(user_id)
    updated = db.get_user_by_id(user_id)
    
    action = "mo khoa" if updated["is_active"] else "khoa"
    logger.info(f"[USERS] {action} user #{user_id}")
    return {"success": True, "is_active": bool(updated["is_active"])}

@router.delete("/{user_id}")
async def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    """Xoa user."""
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User khong ton tai")
    
    if target["id"] == admin["id"]:
        raise HTTPException(400, "Khong the xoa chinh minh")
    
    db.delete_user(user_id)
    
    logger.warning(f"[USERS] Deleted user #{user_id} ({target['username']})")
    return {"success": True, "message": f"Da xoa user '{target['username']}'"}
