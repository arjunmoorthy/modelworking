from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from uuid import UUID, uuid4
from datetime import datetime

from .constants import ConversationState

# ===============================================================================
# Database-related Models (Pydantic representations of SQLAlchemy models)
# ===============================================================================

class Message(BaseModel):
    id: int
    chat_uuid: UUID
    sender: Literal["user", "assistant", "system"]
    message_type: Literal[
        "text", 
        "button_response", 
        "multi_select_response", 
        "multi_select",
        "system", 
        "button_prompt", 
        "single_select",
        "feeling_select", 
        "feeling_response"
    ]
    content: str
    structured_data: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class Chat(BaseModel):
    uuid: UUID = Field(default_factory=uuid4)
    patient_uuid: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    conversation_state: ConversationState
    symptom_list: Optional[List[str]] = []
    severity_list: Optional[Dict[str, int]] = {}
    medication_list: Optional[List[Dict[str, Any]]] = []
    longer_summary: Optional[str] = None
    bulleted_summary: Optional[str] = None
    overall_feeling: Optional[Literal['Very Happy', 'Happy', 'Neutral', 'Sad', 'Very Sad']] = None
    
    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

# ===============================================================================
# REST API Request/Response Models
# ===============================================================================

class CreateChatRequest(BaseModel):
    patient_uuid: UUID

class InitialQuestion(BaseModel):
    text: str
    type: str
    options: List[str]

class CreateChatResponse(BaseModel):
    chat_uuid: UUID
    initial_question: InitialQuestion

class ChatSummaryResponse(BaseModel):
    uuid: UUID
    created_at: datetime
    conversation_state: str
    bulleted_summary: Optional[str]

    class Config:
        from_attributes = True

class FullChatResponse(Chat):
    messages: List[Message]

class TodaySessionResponse(BaseModel):
    chat_uuid: UUID
    conversation_state: str
    messages: List[Message]
    is_new_session: bool
    symptom_list: Optional[List[str]] = []  # Include symptom list for localStorage

    class Config:
        from_attributes = True

class ChatStateResponse(BaseModel):
    conversation_state: str
    symptom_list: Optional[List[str]]
    severity_list: Optional[Dict[str, int]]

    class Config:
        from_attributes = True

class UpdateStateRequest(BaseModel):
    conversation_state: str
    symptom_list: Optional[List[str]] = None
    severity_list: Optional[Dict[str, int]] = None

# ===============================================================================
# WebSocket Message Models
# ===============================================================================

class WebSocketMessageIn(BaseModel):
    """A message received from the client over WebSocket."""
    type: Literal["user_message"]
    message_type: Literal["text", "button_response", "multi_select_response", "feeling_response"]
    content: str
    structured_data: Optional[Dict[str, Any]] = None

class WebSocketMessageOut(BaseModel):
    """A message sent from the server over WebSocket."""
    type: Literal["assistant_message", "system_message"]
    message_type: str
    content: str
    options: Optional[List[str]] = []

class ConnectionEstablished(BaseModel):
    """Message sent to the client upon successful WebSocket connection."""
    type: Literal["connection_established"] = "connection_established"
    content: str
    chat_state: Dict[str, Any]

class WebSocketMessageChunk(BaseModel):
    """A chunk of a streaming message from the server."""
    type: Literal["message_chunk"] = "message_chunk"
    message_id: int
    content: str

class WebSocketStreamEnd(BaseModel):
    """Signals the end of a streaming message."""
    type: Literal["message_end"] = "message_end"
    message_id: int

# ===============================================================================
# Conversation Processing Models
# ===============================================================================

class ProcessRequest(BaseModel):
    message: WebSocketMessageIn
    trigger_kb_query: bool = False

class AssistantResponse(BaseModel):
    content: str
    message_type: str
    expects_response_type: str

class ConversationUpdate(BaseModel):
    new_state: str
    symptom_list: Optional[List[str]] = None

class ProcessResponse(BaseModel):
    user_message_saved: Message
    assistant_response: Message
    conversation_updated: Optional[ConversationUpdate] = None 

    class Config:
        from_attributes = True 
        json_encoders = {
            UUID: str
        } 

