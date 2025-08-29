from sqlalchemy.orm import Session
from datetime import date, datetime
from uuid import UUID
import pytz
import logging

from db.patient_models import PatientChemoDates
from .models import LogChemoDateResponse
from utils.timezone_utils import get_today_in_user_timezone, user_timezone_to_utc

logger = logging.getLogger(__name__)


def log_chemo_date_for_patient(db: Session, patient_uuid: UUID, chemo_date: date, timezone: str = "America/Los_Angeles") -> LogChemoDateResponse:
    """
    Creates a new chemotherapy date entry for a given patient.
    """
    try:
        print(f"[CHEMO] Logging chemotherapy date for patient {patient_uuid}: {chemo_date} in timezone: {timezone}")
        
        # Store UTC timestamp in database
        utc_now = datetime.utcnow()
        if utc_now.tzinfo is None:
            utc_now = pytz.UTC.localize(utc_now)
        
        new_chemo_date_entry = PatientChemoDates(
            patient_uuid=patient_uuid,
            chemo_date=chemo_date,
            created_at=utc_now
        )
        db.add(new_chemo_date_entry)
        db.commit()
        db.refresh(new_chemo_date_entry)
        print(f"[CHEMO] Successfully logged chemotherapy date id={new_chemo_date_entry.id} at {utc_now} UTC")
        
        return LogChemoDateResponse(
            success=True,
            message="Chemotherapy date successfully logged.",
            chemo_date=chemo_date
        )
    except Exception as e:
        db.rollback()
        print(f"[CHEMO] Failed to log chemotherapy date: {e}")
        raise e 