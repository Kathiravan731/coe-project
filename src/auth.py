"""
Role-based access control (RBAC) and least-privilege security helpers.
Restricts high-impact actions (override, approval, status change) to authorized roles.
"""

from fastapi import Header, HTTPException, status
from typing import Optional, List
from src.models import UserRole

def get_current_user(
    x_user_role: Optional[str] = Header(default="coordinator"),
    x_user_id: Optional[str] = Header(default="STF-COORDINATOR-01")
) -> dict:
    """Extracts authenticated user context from request headers."""
    role_str = (x_user_role or "coordinator").lower()
    try:
        role = UserRole(role_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Invalid or unauthorized role: '{role_str}'."
        )
    return {"user_id": x_user_id or "STF-ANON", "role": role}

def require_roles(allowed_roles: List[UserRole]):
    """FastAPI dependency to enforce role requirements on sensitive endpoints."""
    def role_checker(user: dict = None):
        # We will call this directly in route handlers
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Role '{user['role'].value}' lacks permission. Required: {[r.value for r in allowed_roles]}."
            )
        return user
    return role_checker
