"""
Chat and Conversation Routes

This module provides REST and WebSocket endpoints for managing real-time chat conversations.
- REST API: Handles chat creation, history retrieval, and state management.
- WebSocket: Manages real-time, bidirectional message exchange for a single chat.
"""

import json
from uuid import UUID
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Literal
from datetime import date, datetime, time
from jose import jwt, JWTError
from pydantic import BaseModel
import logging
import pytz

# Database and model imports
from db.database import get_patient_db
from routers.auth.dependencies import get_current_user, TokenData, _get_jwks  # Re-use the JWKS fetcher
import os
from .models import (
    CreateChatRequest, CreateChatResponse, FullChatResponse, ChatStateResponse,
    UpdateStateRequest, ChatSummaryResponse, WebSocketMessageIn, TodaySessionResponse,
    Message  # Import the Message model for manual conversion
)
from .services import ConversationService
from db.patient_models import Conversations as ChatModel, Messages as MessageModel
from utils.timezone_utils import utc_to_user_timezone

router = APIRouter(prefix="/chat", tags=["Chat Conversation"])
logger = logging.getLogger(__name__)

class OverallFeelingUpdate(BaseModel):
    feeling: Literal['Very Happy', 'Happy', 'Neutral', 'Sad', 'Very Sad']

def convert_message_for_frontend(message: Message) -> Message:
    """
    Converts message types from database format (underscore) to frontend format (hyphen)
    for display in the UI. Also handles converting back for any data sent to the backend.
    """
    if hasattr(message, 'message_type') and isinstance(message.message_type, str):
        message.message_type = message.message_type.replace('_', '-')
    return message

def convert_chat_to_user_timezone(chat, messages, user_timezone: str = "America/Los_Angeles"):
    """Convert chat and message timestamps to user timezone for display."""
    if chat.created_at:
        chat.created_at = utc_to_user_timezone(chat.created_at, user_timezone)
    if chat.updated_at:
        chat.updated_at = utc_to_user_timezone(chat.updated_at, user_timezone)
    
    for message in messages:
        if message.created_at:
            message.created_at = utc_to_user_timezone(message.created_at, user_timezone)
    
    return chat, messages

# ===============================================================================
# WebSocket Authentication and Authorization Helper
# ===============================================================================
async def get_user_from_token(token: str) -> Optional[TokenData]:
    """
    Validates a JWT token passed to a WebSocket and returns the user's data.
    Accepts both Cognito ID tokens and Access tokens.
    - ID token: contains 'aud' claim and is validated with audience=COGNITO_CLIENT_ID
    - Access token: lacks 'aud'; validate issuer and 'client_id' instead, skipping audience verification
    """
    if not token:
        return None
    try:
        jwks = _get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"], "kid": key["kid"], "use": key["use"],
                    "n": key["n"], "e": key["e"]
                }
        if not rsa_key:
            return None

        issuer = f"https://cognito-idp.{os.getenv('AWS_REGION')}.amazonaws.com/{os.getenv('COGNITO_USER_POOL_ID')}"
        client_id = os.getenv("COGNITO_CLIENT_ID")

        # Peek at unverified claims to branch logic
        claims = jwt.get_unverified_claims(token)
        token_use = claims.get("token_use")

        if token_use == "access":
            # Access tokens do not include 'aud'; verify issuer and optionally client_id
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                issuer=issuer,
                options={"verify_aud": False}
            )
            if client_id and payload.get("client_id") != client_id:
                return None
        else:
            # Assume ID token or other → requires audience check
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=issuer,
            )

        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        return TokenData(sub=user_id, email=payload.get("email"))
    except JWTError:
        return None

# ===============================================================================
# REST API Routes for Conversation Management
# ===============================================================================

@router.get(
    "/session/today",
    response_model=TodaySessionResponse,
    summary="Get or create the chat session for the current day"
)
def get_or_create_session(
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user),
    timezone: str = Query(default="America/Los_Angeles", description="User's timezone")
):
    """
    This is the primary endpoint for starting or resuming a conversation.
    It fetches the most recent chat for the user for the current day.
    If no chat exists, it creates a new one and returns its first message.
    If a chat exists, it returns its full history.
    """
    service = ConversationService(db)
    patient_uuid = UUID(current_user.sub)
    logger.info(f"[CHAT] [/chat/session/today] patient={patient_uuid} tz={timezone}")
    
    chat, messages, is_new = service.get_or_create_today_session(patient_uuid, timezone)
    logger.info(f"[CHAT] [/chat/session/today] chat_uuid={chat.uuid} state={chat.conversation_state} is_new={is_new} messages={len(messages)}")
    
    # Preview first few messages
    for m in messages[:5]:
        try:
            logger.info(f"  msg id={m.id} sender={m.sender} type={getattr(m, 'message_type', None)} created_at={getattr(m, 'created_at', None)}")
        except Exception:
            pass
    
    # Manually convert the list of SQLAlchemy MessageModel objects to Pydantic Message models.
    pydantic_messages = [convert_message_for_frontend(Message.from_orm(msg)) for msg in messages]
    
    # Convert timestamps to user timezone
    convert_chat_to_user_timezone(chat, pydantic_messages, timezone)
    
    # Log after conversion/coercion
    if pydantic_messages:
        logger.info(f"[CHAT] [/chat/session/today] first_message sender={pydantic_messages[0].sender} type={pydantic_messages[0].message_type} len={len(pydantic_messages)}")
    else:
        logger.info(f"[CHAT] [/chat/session/today] no messages in session")
    
    return TodaySessionResponse(
        chat_uuid=chat.uuid,
        conversation_state=chat.conversation_state,
        messages=pydantic_messages,
        is_new_session=is_new,
        symptom_list=chat.symptom_list or []
    )

@router.post(
    "/session/new",
    response_model=TodaySessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Force create a new chat session for the current day"
)
def force_create_new_session(
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user),
    timezone: str = Query(default="America/Los_Angeles", description="User's timezone")
):
    """
    This endpoint forces the creation of a new chat session for the current day,
    bypassing the check for an existing session. This is useful for allowing
    a user to start a fresh conversation at any time.
    """
    service = ConversationService(db)
    patient_uuid = UUID(current_user.sub)
    
    # Delete any existing conversations for today
    user_tz = pytz.timezone(timezone)
    user_now = datetime.now(user_tz)
    today_start = datetime.combine(user_now.date(), time.min)
    today_end = datetime.combine(user_now.date(), time.max)
    
    # Convert to UTC for database query
    utc_today_start = user_tz.localize(today_start).astimezone(pytz.UTC)
    utc_today_end = user_tz.localize(today_end).astimezone(pytz.UTC)
    
    existing_chats = db.query(ChatModel).filter(
        ChatModel.patient_uuid == patient_uuid,
        ChatModel.created_at >= utc_today_start,
        ChatModel.created_at <= utc_today_end
    ).all()
    
    for chat in existing_chats:
        db.delete(chat)
    
    db.commit()
    
    # Create a completely new chat with reset symptom list
    chat, messages, is_new = service.get_or_create_today_session(patient_uuid, timezone)
    
    pydantic_messages = [convert_message_for_frontend(Message.from_orm(msg)) for msg in messages]
    
    # Convert timestamps to user timezone
    convert_chat_to_user_timezone(chat, pydantic_messages, timezone)
    
    return TodaySessionResponse(
        chat_uuid=chat.uuid,
        conversation_state=chat.conversation_state,
        messages=pydantic_messages,
        is_new_session=is_new,
        symptom_list=chat.symptom_list or []
    )

@router.post(
    "/create-dummy",
    response_model=FullChatResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dummy conversation entry"
)
def create_dummy_conversation(
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Creates a new, fully-populated dummy conversation entry for the logged-in user.
    This is used for testing and development purposes.
    """
    # 1. Create the parent Conversation object
    dummy_conversation = ChatModel(
        patient_uuid=current_user.sub,
        conversation_state="completed",
        symptom_list=["nausea", "headache"],
        severity_list={"nausea": 4, "headache": 3},
        longer_summary="The patient is experiencing mild nausea (4/10) and a slight headache (3/10) but is otherwise feeling stable. No other acute symptoms were reported.",
        medication_list=[
            {"symptom": "nausea", "medicineName": "Ondansetron", "frequency": "as_needed", "response": "yes"},
            {"symptom": "headache", "medicineName": "Tylenol", "frequency": "daily", "response": "neutral"}
        ],
        bulleted_summary="- Symptom: Nausea (Severity: 4/10)\n- Symptom: Headache (Severity: 3/10)\n- Medications mentioned: Ondansetron, Tylenol",
        overall_feeling="Neutral"
    )
    
    # 2. Create the individual Message objects
    messages_data = [
        {"id": 1, "sender": "assistant", "content": "Hello, how are you feeling today?"},
        {"id": 2, "sender": "user", "content": "I'm feeling a bit nauseous and have a headache."},
        {"id": 3, "sender": "assistant", "content": "I'm sorry to hear that. On a scale of 1-10, how severe is the nausea?"},
        {"id": 4, "sender": "user", "content": "About a 4."},
        {"id": 5, "sender": "assistant", "content": "And the headache?"},
        {"id": 6, "sender": "user", "content": "A 3."},
    ]
    
    for msg_data in messages_data:
        message = MessageModel(
            sender=msg_data["sender"],
            message_type="text",
            content=msg_data["content"],
            conversation=dummy_conversation
        )
        db.add(message)

    # 3. Add the conversation to the session and commit
    db.add(dummy_conversation)
    db.commit()
    db.refresh(dummy_conversation)
    
    db.refresh(dummy_conversation, attribute_names=['messages'])
    
    return dummy_conversation

@router.post(
    "/create",
    response_model=CreateChatResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new conversation"
)
def create_chat(
    request: CreateChatRequest,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Initializes a new chat session for the authenticated patient,
    returning the new chat UUID and the first question to ask the user.
    """
    if request.patient_uuid != UUID(current_user.sub):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create chat for another patient.")
    
    service = ConversationService(db)
    chat, initial_question = service.create_chat(request.patient_uuid)
    
    return CreateChatResponse(
        chat_uuid=chat.uuid,
        initial_question=initial_question
    )

@router.get(
    "/{chat_uuid}/full",
    response_model=FullChatResponse,
    summary="Get a complete conversation with all messages"
)
def get_full_chat(
    chat_uuid: UUID,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Fetches the entire history of a specific chat, including all messages.
    This is useful for rehydrating the UI when a user resumes a conversation.
    """
    chat = db.query(ChatModel).filter(
        ChatModel.uuid == chat_uuid,
        ChatModel.patient_uuid == UUID(current_user.sub)
    ).first()

    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found or access denied.")
        
    # The `messages` are automatically loaded by SQLAlchemy thanks to the relationship
    # defined in the `patient_models.py` file.
    return FullChatResponse.from_orm(chat)

@router.get(
    "/{chat_uuid}/state",
    response_model=ChatStateResponse,
    summary="Get the current state of a conversation"
)
def get_chat_state(
    chat_uuid: UUID,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Quickly retrieves the current state and key data of a chat without
    fetching the entire message history.
    """
    chat = db.query(ChatModel).filter(
        ChatModel.uuid == chat_uuid,
        ChatModel.patient_uuid == UUID(current_user.sub)
    ).first()
    
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found or access denied.")
    
    return ChatStateResponse.from_orm(chat)

# Note: The PUT /state endpoint is not exposed to clients as per the design.
# It's intended for internal use by the conversation processing engine.

@router.delete(
    "/{chat_uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation"
)
def delete_chat(
    chat_uuid: UUID,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Deletes a specific conversation and all of its associated messages.
    The user must be the owner of the chat.
    """
    service = ConversationService(db)
    try:
        service.delete_chat(chat_uuid, UUID(current_user.sub))
    except ValueError as e:
        # This catches the "Chat not found or access denied" error from the service
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    
    return # Returns a 204 No Content response on success

@router.post(
    "/{chat_uuid}/feeling",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update overall feeling for a chat"
)
def update_overall_feeling(
    chat_uuid: UUID,
    payload: OverallFeelingUpdate,
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    chat = db.query(ChatModel).filter(
        ChatModel.uuid == chat_uuid,
        ChatModel.patient_uuid == UUID(current_user.sub)
    ).first()

    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found or access denied.")

    chat.overall_feeling = payload.feeling
    db.commit()
    return


# ===============================================================================
# WebSocket Endpoint for Real-Time Communication
# ===============================================================================

@router.websocket("/ws/{chat_uuid}")
async def websocket_endpoint(
    websocket: WebSocket,
    chat_uuid: UUID,
    token: str = Query(...),
    db: Session = Depends(get_patient_db)
):
    """
    Handles real-time, bidirectional communication for a single chat session.
    The connection is authenticated and authorized using a JWT token from query params.
    """
    # 1. Authenticate the user
    current_user = await get_user_from_token(token)
    if not current_user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token.")
        return

    # 2. Authorize the user for the chat
    chat = db.query(ChatModel).filter(
        ChatModel.uuid == chat_uuid,
        ChatModel.patient_uuid == UUID(current_user.sub)
    ).first()
    if not chat:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Chat not found or access denied.")
        return

    await websocket.accept()
    service = ConversationService(db)
    
    # Send connection acknowledgment
    ack_message = service.get_connection_ack(chat_uuid)
    if ack_message:
        await websocket.send_text(ack_message.json())

    try:
        while True:
            data = await websocket.receive_text()
            message_data = WebSocketMessageIn(**json.loads(data))
            
            # This now returns a generator, so we iterate over it without awaiting it first
            response_generator = service.process_message_stream(chat_uuid, message_data)
            
            async for chunk in response_generator:
                # Convert message before sending to frontend
                frontend_chunk = convert_message_for_frontend(chunk)
                json_payload = frontend_chunk.json()
                logger.info(f"[CHAT] --> Sending WebSocket message | Type: {frontend_chunk.type if hasattr(frontend_chunk, 'type') else 'Unknown'} | Size: {len(json_payload)} bytes")
                await websocket.send_text(json_payload)

    except WebSocketDisconnect:
        logger.info(f"[CHAT] Client disconnected from chat {chat_uuid}")
    except Exception as e:
        logger.error(f"[CHAT] An error occurred in chat {chat_uuid}: {e}")
        # Truncate the error reason to prevent WebSocket protocol errors
        reason = str(e)[:120] + "..." if len(str(e)) > 120 else str(e)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=reason) 