from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date
import logging

from db.database import get_patient_db
from routers.auth.dependencies import get_current_user, TokenData
from . import services, models

router = APIRouter(prefix="/chemo", tags=["Chemotherapy"])
logger = logging.getLogger(__name__)

@router.post("/log", response_model=models.LogChemoDateResponse, tags=["chemo"])
def log_chemo_date(
    request: models.LogChemoDateRequest,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Logs a chemotherapy date for the authenticated patient.
    """
    try:
        logger.info(f"[CHEMO] Log chemo date: patient={current_user.sub} chemo_date={request.chemo_date} tz={request.timezone}")
        result = services.log_chemo_date_for_patient(
            db=db,
            patient_uuid=current_user.sub,
            chemo_date=request.chemo_date,
            timezone=request.timezone
        )
        logger.info(f"[CHEMO] Logged chemo date OK: patient={current_user.sub} id={getattr(result, 'id', None)}")
        return result
    except Exception as e:
        logger.error(f"[CHEMO] Failed to log chemo date: patient={current_user.sub} error={e}")
        raise HTTPException(status_code=500, detail=str(e)) 