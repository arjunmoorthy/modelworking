"""
Patient Configuration Routes

This module provides endpoints for managing patient settings and preferences:

Routes:
- PATCH /patient/update-reminders: Update patient reminder method (email/text) and time
- PATCH /patient/update-consent: Update patient consent flags and acknowledgements

All routes require authentication and operate on the logged-in user's data.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import uuid
import logging
import os

# Database and model imports
from db.database import get_patient_db
from db.patient_models import PatientConfigurations
from routers.auth.dependencies import get_current_user, TokenData
from .models import PatientConfigurationsUpdate, PatientConsentUpdate


# Configure logging
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/patient", tags=["Patient Data"])


@router.patch(
    "/update-reminders",
    response_model=PatientConfigurationsUpdate,
    summary="Update patient reminder settings"
)
async def update_reminder_settings(
    updates: PatientConfigurationsUpdate,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Update the reminder method and/or time for the logged-in patient.
    Provide only the fields you want to change.
    """
    config = db.query(PatientConfigurations).filter(PatientConfigurations.uuid == current_user.sub).first()

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient configuration not found.")

    update_data = updates.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided.")

    for key, value in update_data.items():
        setattr(config, key, value)
    
    db.commit()
    db.refresh(config)
    logger.info(f"Updated reminder settings for user {current_user.sub}")
    return config


@router.patch(
    "/update-consent",
    response_model=PatientConsentUpdate,
    summary="Update patient consent and acknowledgements"
)
async def update_consent_settings(
    updates: PatientConsentUpdate,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Update the terms of conditions and acknowledgement flags for the logged-in patient.
    """
    config = db.query(PatientConfigurations).filter(PatientConfigurations.uuid == current_user.sub).first()

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient configuration not found.")

    update_data = updates.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided.")

    for key, value in update_data.items():
        setattr(config, key, value)
    
    db.commit()
    db.refresh(config)
    logger.info(f"Updated consent settings for user {current_user.sub}")
    return config 