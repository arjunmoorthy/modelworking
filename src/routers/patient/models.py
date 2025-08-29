from pydantic import BaseModel, validator
from typing import Optional
from datetime import time

class PatientConfigurationsUpdate(BaseModel):
    reminder_method: Optional[str] = None
    reminder_time: Optional[time] = None

    @validator('reminder_method')
    def reminder_method_must_be_valid(cls, v):
        if v is not None and v.lower() not in ['email', 'text']:
            raise ValueError('Reminder method must be either "email" or "text"')
        return v

class PatientConsentUpdate(BaseModel):
    agreed_conditions: Optional[bool] = None
    acknowledgement_done: Optional[bool] = None 