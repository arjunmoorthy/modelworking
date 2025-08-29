from pydantic import BaseModel
from datetime import date
from typing import Optional

class LogChemoDateRequest(BaseModel):
    chemo_date: date
    timezone: Optional[str] = "America/Los_Angeles"  # Default to PST if not provided

class LogChemoDateResponse(BaseModel):
    success: bool
    message: str
    chemo_date: date

    class Config:
        from_attributes = True 