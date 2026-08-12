"""Keyword Intelligence API (spec Part 17).

Upload is a two-step flow on purpose (§17.4): inspect, then confirm. The
operator sees the detected snapshot date, the ASINs, which columns were
recognised, and whether this exact file has been imported before — and only
then commits. A one-shot upload would silently accept a file whose headers
changed, and the mistake would surface weeks later as a flat trend line.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.keyword_intel.models import (
    KiColumnMapping, KiSnapshot, ProductListing,
)
from app.modules.keyword_intel.service import (
    KeywordIntelService, SnapshotImportError,
)

router = APIRouter(prefix="/keyword-intel", tags=["keyword-intelligence"])

# A Cerebro export of 100k keywords is a few tens of MB. Above this something
# is wrong, and parsing it would tie up a worker for minutes.
MAX_UPLOAD_BYTES = 60 * 1024 * 1024

SourceType = Literal["cerebro", "custom_csv"]


class MappingIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: str = "custom_csv"
    mapping_json: dict[str, str]


class MappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    source_type: str
    mapping_json: dict
    created_at: datetime


class ListingIn(BaseModel):
    asin: str = Field(min_length=8, max_length=20)
    title: Optional[str] = None
    bullet_points: list[str] = Field(default_factory=list)
    backend_keywords: Optional[str] = None


async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if not content:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"File is {len(content) / 1_048_576:.0f} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // 1_048_576} MB.",
        )
    return content


@router.get("/stats")
def stats(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    return KeywordIntelService(db).stats()


@router.post("/inspect")
async def inspect_file(
    file: UploadFile = File(...),
    source_type: SourceType = Form("cerebro"),
    mapping_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Parse without saving. Step 1 of 2."""
    content = await _read_upload(file)
    try:
        result = KeywordIntelService(db).inspect(content, source_type, mapping_id)
    except SnapshotImportError as exc:
        raise HTTPException(400, str(exc))
    result["filename"] = file.filename
    return result


@router.post("/snapshots", status_code=201)
async def import_snapshot(
    file: UploadFile = File(...),
    source_type: SourceType = Form("cerebro"),
    # Not defaulted to today: the operator confirms what the data represents,
    # which is frequently not the day they got round to uploading it.
    snapshot_date: date = Form(...),
    asins: str = Form(""),
    mapping_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Commit the import. Step 2 of 2."""
    content = await _read_upload(file)
    asin_list = [a.strip().upper() for a in asins.split(",") if a.strip()]
    try:
        snapshot = KeywordIntelService(db).import_snapshot(
            content=content, source_type=source_type,
            snapshot_date=snapshot_date, filename=file.filename,
            uploaded_by=user.id, asins=asin_list, mapping_id=mapping_id,
        )
    except SnapshotImportError as exc:
        raise HTTPException(400, str(exc))
    return {
        "id": str(snapshot.id),
        "row_count": snapshot.row_count,
        "status": snapshot.status,
        "snapshot_date": snapshot.snapshot_date.isoformat(),
    }


@router.get("/snapshots")
def list_snapshots(
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    return KeywordIntelService(db).list_snapshots(limit)


@router.get("/snapshots/{snapshot_id}/keywords")
def snapshot_keywords(
    snapshot_id: uuid.UUID,
    limit: int = Query(500, le=5000),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    return KeywordIntelService(db).snapshot_keywords(str(snapshot_id), limit, search)


@router.delete("/snapshots/{snapshot_id}", status_code=204)
def delete_snapshot(
    snapshot_id: uuid.UUID,
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Remove a snapshot and its metrics.

    A hard delete, unlike the rest of the app: a wrongly-dated or wrong-file
    import is noise in every trend that crosses it, and keeping it soft-deleted
    would mean every trend query had to remember to exclude it.
    """
    snapshot = db.query(KiSnapshot).filter(KiSnapshot.id == snapshot_id).first()
    if snapshot is None:
        raise HTTPException(404, "Snapshot not found")
    db.delete(snapshot)     # metrics and asins cascade
    db.commit()


@router.get("/keywords")
def search_keywords(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    return KeywordIntelService(db).search_keywords(q, limit)


@router.get("/keywords/{keyword_id}/trend")
def keyword_trend(
    keyword_id: uuid.UUID,
    asin: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    return KeywordIntelService(db).keyword_trend(str(keyword_id), asin)


# ── Column mappings ────────────────────────────────────────────────────────

@router.get("/mappings", response_model=list[MappingOut])
def list_mappings(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    return db.query(KiColumnMapping).order_by(KiColumnMapping.created_at.desc()).all()


@router.post("/mappings", response_model=MappingOut, status_code=201)
def create_mapping(
    body: MappingIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = KiColumnMapping(
        name=body.name, source_type=body.source_type,
        mapping_json=body.mapping_json, created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ── Product listings (manual, for the Phase 3 listings gap) ────────────────

@router.get("/listings")
def list_listings(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    rows = db.query(ProductListing).order_by(ProductListing.asin).all()
    return [{
        "asin": r.asin,
        "title": r.title,
        "bullet_points": r.bullet_points or [],
        "backend_keywords": r.backend_keywords,
        # Spec §17.6: surface staleness so operators can judge it themselves.
        "last_updated_at": r.last_updated_at.isoformat() if r.last_updated_at else None,
    } for r in rows]


@router.put("/listings/{asin}")
def upsert_listing(
    asin: str,
    body: ListingIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    asin = asin.strip().upper()
    row = db.query(ProductListing).filter(ProductListing.asin == asin).first()
    if row is None:
        row = ProductListing(asin=asin)
        db.add(row)
    row.title = body.title
    row.bullet_points = body.bullet_points
    row.backend_keywords = body.backend_keywords
    row.last_updated_by = user.id
    row.last_updated_at = datetime.now()
    db.commit()
    return {"asin": row.asin, "last_updated_at": row.last_updated_at.isoformat()}
