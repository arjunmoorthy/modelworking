"""
Diary Entry Routes

This module provides endpoints for managing patient diary entries:

Routes:
- GET /diary/{year}/{month}: Fetch diary entries for a specific month and year
- POST /diary/: Create a new diary entry with text and doctor flag
- DELETE /diary/{entry_uuid}: Permanently delete a diary entry by UUID

All routes require authentication and operate on the logged-in user's data.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import extract
from typing import List
import uuid
import logging

# Database and model imports
from db.database import get_patient_db
from db.patient_models import PatientDiaryEntries
from routers.auth.dependencies import get_current_user, TokenData
from .models import DiaryEntrySchema, DiaryEntryCreate, DiaryEntryUpdate
from utils.timezone_utils import utc_to_user_timezone, format_datetime_for_display

router = APIRouter(prefix="/diary", tags=["Patient Diary"])
logger = logging.getLogger(__name__)

def convert_diary_entry_to_user_timezone(entry, user_timezone: str = "America/Los_Angeles"):
    """Convert diary entry timestamps to user timezone for display."""
    # Create a copy of the entry data to avoid modifying the database object
    entry_data = {
        "id": entry.id,
        "created_at": entry.created_at,
        "last_updated_at": entry.last_updated_at,
        "patient_uuid": str(entry.patient_uuid),  # Convert UUID to string
        "title": entry.title,
        "diary_entry": entry.diary_entry,
        "entry_uuid": str(entry.entry_uuid),  # Convert UUID to string
        "marked_for_doctor": entry.marked_for_doctor,

    }
    
    # Convert timestamps to user timezone
    if entry_data["created_at"]:
        try:
            entry_data["created_at"] = utc_to_user_timezone(entry_data["created_at"], user_timezone)
        except Exception as e:
            logger.error(f"[DIARY] Failed to convert created_at: {e}")
            entry_data["created_at"] = entry.created_at  # Keep original if conversion fails
    
    if entry_data["last_updated_at"]:
        try:
            entry_data["last_updated_at"] = utc_to_user_timezone(entry_data["last_updated_at"], user_timezone)
        except Exception as e:
            logger.error(f"[DIARY] Failed to convert last_updated_at: {e}")
            entry_data["last_updated_at"] = entry.last_updated_at  # Keep original if conversion fails
    
    return entry_data

@router.get("/{year}/{month}", response_model=list[DiaryEntrySchema])
async def get_diary_entries_by_month(
    year: int,
    month: int,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user),
    timezone: str = Query(default="America/Los_Angeles", description="User's timezone")
):
    """
    Get all diary entries for a specific month and year.
    """
    try:
        logger.info(f"[DIARY] Fetch month year={year} month={month} patient={current_user.sub} tz={timezone}")
        entries = db.query(PatientDiaryEntries).filter(
            PatientDiaryEntries.patient_uuid == current_user.sub,
            extract('year', PatientDiaryEntries.created_at) == year,
            extract('month', PatientDiaryEntries.created_at) == month
        ).order_by(PatientDiaryEntries.last_updated_at.desc()).all()
        logger.info(f"[DIARY] Fetched entries count={len(entries)} for patient={current_user.sub}")
        
        # Convert timestamps to user timezone and create proper response objects
        response_data = []
        for entry in entries:
            entry_data = convert_diary_entry_to_user_timezone(entry, timezone)
            response_data.append(DiaryEntrySchema(**entry_data))
        
        return response_data
    except Exception as e:
        logger.error(f"[DIARY] Fetch month failed patient={current_user.sub} error={e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("", response_model=DiaryEntrySchema)
async def create_diary_entry(
    entry_data: DiaryEntryCreate,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user),
    timezone: str = Query(default="America/Los_Angeles", description="User's timezone")
):
    """
    Create a new diary entry for the authenticated patient.
    """
    try:
        logger.info(f"[DIARY] Creating entry patient={current_user.sub} title='{entry_data.title}' content_length={len(entry_data.diary_entry)}")
        
        new_entry = PatientDiaryEntries(
            patient_uuid=current_user.sub,
            title=entry_data.title,
            diary_entry=entry_data.diary_entry,
            marked_for_doctor=entry_data.marked_for_doctor
        )
        db.add(new_entry)
        db.commit()
        db.refresh(new_entry)
        
        logger.info(f"[DIARY] Created entry id={new_entry.id} entry_uuid={new_entry.entry_uuid} patient={current_user.sub}")
        
        # Convert to proper response format with timezone conversion
        entry_data_converted = convert_diary_entry_to_user_timezone(new_entry, timezone)
        return DiaryEntrySchema(**entry_data_converted)
        
    except Exception as e:
        db.rollback()
        logger.error(f"[DIARY] Create failed patient={current_user.sub} error={e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{entry_uuid}", response_model=DiaryEntrySchema)
async def update_diary_entry(
    entry_uuid: str,
    update_data: DiaryEntryUpdate,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user),
    timezone: str = Query(default="America/Los_Angeles", description="User's timezone")
):
    """
    Update a diary entry for the authenticated patient.
    """
    try:
        entry_to_update = db.query(PatientDiaryEntries).filter(
            PatientDiaryEntries.entry_uuid == entry_uuid,
            PatientDiaryEntries.patient_uuid == current_user.sub
        ).first()

        if not entry_to_update:
            logger.warning(f"[DIARY] Update not found entry_uuid={entry_uuid} patient={current_user.sub}")
            raise HTTPException(status_code=404, detail="Diary entry not found")

        update_data_dict = update_data.dict(exclude_unset=True)
        if not update_data_dict:
            raise HTTPException(
                status_code=400,
                detail="No update data provided."
            )

        for key, value in update_data_dict.items():
            setattr(entry_to_update, key, value)

        db.commit()
        db.refresh(entry_to_update)
        logger.info(f"[DIARY] Updated entry id={entry_to_update.id} patient={current_user.sub}")
        entry_data = convert_diary_entry_to_user_timezone(entry_to_update, timezone)
        return DiaryEntrySchema(**entry_data)
    except Exception as e:
        db.rollback()
        logger.error(f"[DIARY] Update failed entry_uuid={entry_uuid} patient={current_user.sub} error={e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("", response_model=list[DiaryEntrySchema])
async def get_all_diary_entries(
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user),
    timezone: str = Query(default="America/Los_Angeles", description="User's timezone")
):
    """
    Get all diary entries for the authenticated patient.
    """
    try:
        logger.info(f"[DIARY] Fetch all patient={current_user.sub} tz={timezone}")
        entries = db.query(PatientDiaryEntries).filter(
            PatientDiaryEntries.patient_uuid == current_user.sub
        ).order_by(PatientDiaryEntries.last_updated_at.desc()).all()
        logger.info(f"[DIARY] Fetched all count={len(entries)} patient={current_user.sub}")
        
        response_data = []
        for entry in entries:
            entry_data = convert_diary_entry_to_user_timezone(entry, timezone)
            response_data.append(DiaryEntrySchema(**entry_data))
        
        return response_data
    except Exception as e:
        logger.error(f"[DIARY] Fetch all failed patient={current_user.sub} error={e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete(
    "/{entry_uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a diary entry permanently"
)
async def delete_diary_entry(
    entry_uuid: uuid.UUID,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Permanently deletes a diary entry from the database.
    Ensures the entry belongs to the logged-in user before deleting.
    """
    try:
        logger.info(f"[DIARY] Delete entry_uuid={entry_uuid} patient={current_user.sub}")
        
        entry_to_delete = db.query(PatientDiaryEntries).filter(
            PatientDiaryEntries.entry_uuid == entry_uuid,
            PatientDiaryEntries.patient_uuid == current_user.sub
        ).first()

        if not entry_to_delete:
            logger.warning(f"[DIARY] Delete not found entry_uuid={entry_uuid} patient={current_user.sub}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Diary entry not found or you do not have permission to delete it."
            )

        # Actually delete from database
        db.delete(entry_to_delete)
        db.commit()
        logger.info(f"[DIARY] Permanently deleted entry_id={entry_to_delete.id} patient={current_user.sub}")
        return
        
    except Exception as e:
        logger.error(f"[DIARY] Delete failed entry_uuid={entry_uuid} patient={current_user.sub} error={e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete diary entry: {str(e)}") 