from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import logging

# Database and model imports
from db.database import get_patient_db, get_doctor_db
from db.patient_models import PatientInfo, PatientConfigurations, PatientPhysicianAssociations
from db.doctor_models import StaffProfiles, AllClinics, StaffAssociations
from routers.auth.dependencies import get_current_user, TokenData
from .models import PatientProfileResponse

router = APIRouter(prefix="/profile", tags=["Patient Profile"])
logger = logging.getLogger(__name__)

@router.get("", response_model=PatientProfileResponse, summary="Get complete patient profile")
async def get_patient_profile(
    patient_db: Session = Depends(get_patient_db),
    doctor_db: Session = Depends(get_doctor_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Fetches and assembles a complete patient profile by combining data
    from both the patient and doctor databases.
    """
    patient_uuid = current_user.sub
    logger.info(f"[PROFILE] Fetch profile patient={patient_uuid}")

    # 1. Fetch base patient info and configuration from patient_db
    patient_info = patient_db.query(PatientInfo).filter(PatientInfo.uuid == patient_uuid).first()
    if not patient_info:
        logger.error(f"[PROFILE] Patient not found patient={patient_uuid}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found.")

    patient_config = patient_db.query(PatientConfigurations).filter(PatientConfigurations.uuid == patient_uuid).first()

    # Initialize doctor and clinic names to None
    doctor_name = None
    clinic_name = None

    # 2. Fetch physician and clinic info using both databases
    association = patient_db.query(PatientPhysicianAssociations).filter(
        PatientPhysicianAssociations.patient_uuid == patient_uuid
    ).first()

    if association:
        physician_profile = doctor_db.query(StaffProfiles).filter(
            StaffProfiles.staff_uuid == association.physician_uuid
        ).first()
        if physician_profile:
            doctor_name = f"{physician_profile.first_name} {physician_profile.last_name}"

            staff_association = doctor_db.query(StaffAssociations).filter(
                StaffAssociations.physician_uuid == association.physician_uuid
            ).first()
            
            if staff_association:
                clinic_profile = doctor_db.query(AllClinics).filter(
                    AllClinics.uuid == staff_association.clinic_uuid
                ).first()
                if clinic_profile:
                    clinic_name = clinic_profile.clinic_name

    logger.info(f"[PROFILE] Profile fetched patient={patient_uuid} doctor={doctor_name} clinic={clinic_name}")

    return PatientProfileResponse(
        first_name=patient_info.first_name,
        last_name=patient_info.last_name,
        email_address=patient_info.email_address,
        phone_number=patient_info.phone_number,
        date_of_birth=patient_info.dob,
        reminder_time=patient_config.reminder_time if patient_config else None,
        doctor_name=doctor_name,
        clinic_name=clinic_name,
    )
