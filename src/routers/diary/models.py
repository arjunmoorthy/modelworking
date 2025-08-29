from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class DiaryEntrySchema(BaseModel):
    id: int
    created_at: datetime
    last_updated_at: datetime
    patient_uuid: str
    title: Optional[str] = None
    diary_entry: str
    entry_uuid: str
    marked_for_doctor: bool

    class Config:
        from_attributes = True

class DiaryEntryCreate(BaseModel):
    title: Optional[str] = None
    diary_entry: str
    marked_for_doctor: bool = False

class DiaryEntryUpdate(BaseModel):
    title: Optional[str] = None
    diary_entry: Optional[str] = None
    marked_for_doctor: Optional[bool] = None 