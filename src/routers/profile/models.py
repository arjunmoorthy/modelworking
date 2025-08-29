from pydantic import BaseModel
from typing import Optional
from datetime import date, time

class PatientConfigurationsUpdate(BaseModel):
    reminder_method: Optional[str] = None
    reminder_time: Optional[time] = None
    acknowledgement_done: Optional[bool] = None
    agreed_conditions: Optional[bool] = None

class PatientConsentUpdate(BaseModel):
    acknowledgement_done: Optional[bool] = None
    agreed_conditions: Optional[bool] = None

class PatientProfileResponse(BaseModel):
    first_name: str
    last_name: str
    email_address: str
    phone_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    reminder_time: Optional[time] = None
    doctor_name: Optional[str] = None
    clinic_name: Optional[str] = None

class PatientInfoSchema(BaseModel):
    uuid: str
    created_at: str
    email_address: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    sex: Optional[str] = None
    dob: Optional[date] = None
    mrn: Optional[str] = None
    ethnicity: Optional[str] = None
    phone_number: Optional[str] = None
    disease_type: Optional[str] = None
    treatment_type: Optional[str] = None
    is_deleted: bool

    class Config:
        from_attributes = True
