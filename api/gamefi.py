from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from data.database import db

router = APIRouter(prefix="/api/gamefi", tags=["GameFi"])

class GameFiProject(BaseModel):
    name: str
    symbol: str
    chain: str = "SOL"
    token_price: float = 0
    nft_floor_price: float = 0
    daily_roi_estimate: float = 0
    onchain_users_24h: int = 0
    note: str = ""

@router.get("/")
def get_projects():
    projects = db.get_gamefi_projects()
    return {"projects": projects, "count": len(projects)}

@router.post("/")
def add_project(req: GameFiProject):
    db.add_gamefi_project(
        name=req.name,
        symbol=req.symbol,
        chain=req.chain,
        token_price=req.token_price,
        nft_floor_price=req.nft_floor_price,
        daily_roi_estimate=req.daily_roi_estimate,
        onchain_users_24h=req.onchain_users_24h,
        note=req.note
    )
    return {"success": True}

@router.put("/{project_id}")
def update_project(project_id: int, req: GameFiProject):
    db.update_gamefi_project(project_id, req.dict())
    return {"success": True}

@router.delete("/{project_id}")
def delete_project(project_id: int):
    db.remove_gamefi_project(project_id)
    return {"success": True}
