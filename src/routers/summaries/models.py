from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class ConversationSummarySchema(BaseModel):
    uuid: str
    created_at: datetime
    conversation_state: str
    symptom_list: Optional[List[str]] = None
    severity_list: Optional[dict] = None
    longer_summary: Optional[str] = None
    medication_list: Optional[List] = None
    bulleted_summary: Optional[str] = None
    overall_feeling: Optional[str] = None

    class Config:
        from_attributes = True

class ConversationDetailSchema(BaseModel):
    uuid: str
    created_at: datetime
    conversation_state: str
    symptom_list: Optional[List[str]] = None
    severity_list: Optional[dict] = None
    longer_summary: Optional[str] = None
    medication_list: Optional[List] = None
    bulleted_summary: Optional[str] = None
    overall_feeling: Optional[str] = None

    class Config:
        from_attributes = True 