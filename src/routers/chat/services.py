import os
import json
import uuid
from typing import Dict, Any, List, Tuple, AsyncGenerator
from uuid import UUID
from sqlalchemy.orm import Session
from datetime import datetime, time
import pytz

from .models import (
    WebSocketMessageIn, WebSocketMessageOut,
    ConnectionEstablished, Message, ProcessResponse
)
from .constants import ConversationState
from .llm.context import ContextLoader
from .llm.gpt import GPT4oProvider
from .llm.groq import GroqProvider
from .llm.cerebras import CerebrasProvider
from .llm.retrieval import retrieve_for_symptoms, cached_retrieve
from db.patient_models import Conversations as ChatModel, Messages as MessageModel

LLM_PROVIDER = "groq"  # Options: "gpt4o", "groq", "cerebras"

def get_llm_provider():
    """Factory function to get the configured LLM provider."""
    if LLM_PROVIDER == "gpt4o":
        return GPT4oProvider()
    elif LLM_PROVIDER == "groq":
        return GroqProvider()
    elif LLM_PROVIDER == "cerebras":
        return CerebrasProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {LLM_PROVIDER}")


# ===============================================================================
# Core Conversation Logic (with real database queries)
# ===============================================================================

class ConversationService:
    def __init__(self, db: Session):
        self.db = db

    def delete_chat(self, chat_uuid: UUID, patient_uuid: UUID):
        """Deletes a chat conversation after verifying ownership."""
        chat = self.db.query(ChatModel).filter(
            ChatModel.uuid == chat_uuid, 
            ChatModel.patient_uuid == patient_uuid
        ).first()

        if not chat:
            raise ValueError("Chat not found or access denied.")
        
        self.db.delete(chat)
        self.db.commit()
        return

    def create_chat(self, patient_uuid: UUID, commit: bool = True) -> Tuple[ChatModel, Dict[str, Any]]:
        """
        Creates a new chat, saves a system message, and updates the state.
        Can be part of a larger transaction if commit=False.
        """
        # 1. Create the parent Conversation object
        new_chat = ChatModel(
            patient_uuid=patient_uuid,
            conversation_state=ConversationState.CHEMO_CHECK_SENT,
            symptom_list=[]  # Always start with empty symptom list
        )
        self.db.add(new_chat)
        
        if commit:
            self.db.commit()
            self.db.refresh(new_chat)
            
        initial_question = {
            "text": "Did you get chemotherapy today?",
            "type": "single_select",  # Database format (underscore)
            "frontend_type": "single-select",  # Frontend format (hyphen)
            "options": ["Yes", "No", "I had it recently, but didn't record it"],
        }
        return new_chat, initial_question

    def _determine_next_state_and_response(self, chat: ChatModel, message: WebSocketMessageIn) -> Tuple[str, WebSocketMessageOut]:
        """The main state machine for the conversation."""
        current_state = chat.conversation_state
        next_state = current_state
        response_content = "I'm not sure how to respond to that. Can you try again?"
        response_options = []
        response_type = "text"

        if current_state == ConversationState.COMPLETED:
            response_content = "This conversation has ended. Please start a new one if you need assistance."
        
        elif current_state == ConversationState.CHEMO_CHECK_SENT:
            next_state = ConversationState.SYMPTOM_SELECTION_SENT
            response_content = "Please select any symptoms you're experiencing today."
            response_type = "multi_select"
            response_options = [
                "Fever",
                "Diarrhea",
                "Pain",
                "Nausea",
                "Vomiting",
                "Cough",
                "Fatigue",
                "Swelling",
                "Numbness or Tingling",
                "Constipation",
                "Mouth or Throat Sores",
                "Rash",
                "Urinary Issues",
                "Other",
                "None"
            ]

        elif current_state == ConversationState.SYMPTOM_SELECTION_SENT:
            next_state = ConversationState.FOLLOWUP_QUESTIONS
            # Parse symptoms from multi-select response
            symptoms = [s.strip() for s in message.content.split(',') if s.strip()]
            # Filter out "None" if it's selected
            symptoms = [s for s in symptoms if s.lower() != "none"]
            
            # Update the chat's symptom list in the database
            if symptoms:
                chat.symptom_list = list(set((chat.symptom_list or []) + symptoms))
                print(f"Updated symptom list in database: {chat.symptom_list}")
                self.db.commit()
            
            context = {"patient_state": {"current_symptoms": chat.symptom_list}}
            response_content = self._query_knowledge_base_with_rag(chat, context)

        elif current_state == ConversationState.FOLLOWUP_QUESTIONS:
            chat_history = self.db.query(MessageModel).filter(MessageModel.chat_uuid == chat.uuid).order_by(MessageModel.id.desc()).limit(20).all()
            context = {
                "patient_state": {"current_symptoms": chat.symptom_list},
                "latest_input": message.content,
                "history": [Message.from_orm(m).model_dump(mode='json') for m in reversed(chat_history)]
            }
            
            llm_response = self._query_knowledge_base_with_rag(chat, context)

            if "DONE" in llm_response:
                response_content = "DONE"
            else:
                # Check if the LLM is asking the user to add more symptoms
                if "anything else you would like to discuss" in llm_response.lower():
                    response_type = "button_prompt"
                    response_options = ["Yes", "No"]
                
                response_content = llm_response

            next_state = ConversationState.FOLLOWUP_QUESTIONS
        
        assistant_response = WebSocketMessageOut(
            type="assistant_message",
            message_type=response_type,
            content=response_content,
            options=response_options,
        )
        return next_state, assistant_response

    def _query_knowledge_base_with_rag(self, chat: ChatModel, context: Dict[str, Any]) -> str:
        """
        Query knowledge base with complete context including base documents and RAG results.
        """
        print(f"KB_RAG: Querying {LLM_PROVIDER.upper()} with complete context...")
        
        # 1. Load complete system prompt (base documents + RAG results)
        model_inputs_path = "/app/model_inputs"
        if not os.path.exists(model_inputs_path):
            model_inputs_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'model_inputs'))
        context_loader = ContextLoader(model_inputs_path)
        
        # Get patient symptoms for RAG
        patient_symptoms = context.get('patient_state', {}).get('current_symptoms', [])
        
        # Load complete context (base documents + RAG results)
        system_prompt = context_loader.load_context(patient_symptoms)
        
        print(f"Loaded complete context for symptoms: {patient_symptoms}")

        # 2. Construct the user prompt for the LLM
        user_prompt_parts = [
            "### Conversation Context ###",
            f"Current Symptoms: {context.get('patient_state', {}).get('current_symptoms', [])}",
            f"Chat History (most recent messages): {json.dumps(context.get('history', []), indent=2)}",
            f"\n### User's Latest Message ###",
            f"User: \"{context.get('latest_input', '')}\"",
            "\n### Instructions ###",
            "Follow the conversation workflow defined in your system instructions. Remember to respond with valid JSON only.",
            "IMPORTANT: If you detect new symptoms in the user's message, include them in the 'new_symptoms' field of your JSON response."
        ]
        user_prompt = "\n".join(user_prompt_parts)

        # 3. Call the LLM provider
        llm_provider = get_llm_provider()
        response_generator = llm_provider.query(
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )

        # 4. Consume the streaming generator to get a single string response
        full_response = "".join([chunk for chunk in response_generator])
        
        print(f"KB_RAG: Received response from {LLM_PROVIDER.upper()}: '{full_response[:100]}...'")
        return full_response if full_response else "I'm not sure what to ask next. Can you tell me more?"

    def _extract_json_from_response(self, text: str) -> Dict[str, Any]:
        """
        Extracts JSON from the LLM response, handling various formats.
        """
        try:
            # Try to find JSON in the response
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = text[start_idx:end_idx + 1]
                return json.loads(json_str)
            else:
                print(f"Could not find JSON in response: {text}")
                return {}
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            print(f"Response text: {text}")
            return {}

    async def process_message_stream(self, chat_uuid: UUID, message: WebSocketMessageIn) -> AsyncGenerator[Any, None]:
        """
        Processes a message and streams the response back to the client.
        """
        print(f"🔍 Processing message for chat {chat_uuid}: {message.content}")
        chat = self.db.query(ChatModel).filter(ChatModel.uuid == chat_uuid).first()
        if not chat: 
            print(f"Chat {chat_uuid} not found")
            return

        # 1. Save and yield the user's message
        user_msg = MessageModel(chat_uuid=chat_uuid, sender="user", message_type=message.message_type, content=message.content)
        self.db.add(user_msg)
        self.db.commit()
        self.db.refresh(user_msg)
        yield Message.from_orm(user_msg)

        # 2. If we are in an early deterministic state, use the state machine
        # Only CHEMO_CHECK_SENT is deterministic. SYMPTOM_SELECTION_SENT should fall through to LLM after updating symptoms.
        if chat.conversation_state in [
            ConversationState.CHEMO_CHECK_SENT,
        ]:
            try:
                next_state, assistant_response = self._determine_next_state_and_response(chat, message)
            except Exception as e:
                # Fail safe: do not drop the socket; provide a simple fallback response
                print(f"State machine error: {e}")
                next_state = ConversationState.FOLLOWUP_QUESTIONS
                assistant_response = WebSocketMessageOut(
                    type="assistant_message",
                    message_type="button_prompt",
                    content="I understand. Would you like to discuss any other health-related concerns?",
                    options=["Yes", "No"],
                )
            # Persist next state
            chat.conversation_state = next_state
            self.db.commit()

            # Normalize and save assistant message
            db_message_type = assistant_response.message_type.replace('-', '_')
            assistant_msg = MessageModel(
                chat_uuid=chat_uuid,
                sender="assistant",
                message_type=db_message_type,
                content=assistant_response.content,
                structured_data={"options": assistant_response.options} if getattr(assistant_response, 'options', None) else None,
            )
            self.db.add(assistant_msg)
            self.db.commit()
            self.db.refresh(assistant_msg)

            # Yield with frontend message type preserved
            frontend_message = Message.from_orm(assistant_msg)
            frontend_message.message_type = assistant_response.message_type
            yield frontend_message
            return

        # 2b. If we are expecting symptom selection, update the symptom list and advance state, then continue to LLM
        if chat.conversation_state == ConversationState.SYMPTOM_SELECTION_SENT and message.message_type == 'multi_select_response':
            # Parse selections (comma separated string)
            selections = [s.strip() for s in (message.content or '').split(',') if s.strip()]
            selections = [s for s in selections if s.lower() != 'none']
            if selections:
                chat.symptom_list = list(set((chat.symptom_list or []) + selections))
                print(f"[SYMPTOMS] Updated symptom_list after multi-select: {chat.symptom_list}")
            # Advance state to follow-up
            chat.conversation_state = ConversationState.FOLLOWUP_QUESTIONS
            self.db.commit()

        # 3. Get the full conversation history to send to the LLM
        chat_history = self.db.query(MessageModel).filter(MessageModel.chat_uuid == chat.uuid).order_by(MessageModel.id.asc()).all()
        history_for_llm = [Message.from_orm(m).model_dump(mode='json') for m in chat_history]
        # Debug: print history size and preview last few messages
        try:
            print(f"[HISTORY] messages_in_history={len(history_for_llm)}")
        except Exception:
            pass

        context = {
            "patient_state": {"current_symptoms": chat.symptom_list},
            "latest_input": message.content,
            "history": history_for_llm
        }

        print(f"📝 Context prepared: patient_state={context.get('patient_state')} history_len={len(history_for_llm)}")

        # 4. Get LLM response (non-streaming)
        try:
            print("🤖 Starting LLM processing...")
            llm_response_text = self._query_knowledge_base_with_rag(chat, context)
            print(f"📄 Full LLM response: {llm_response_text}")
        except Exception as e:
            print(f"❌ LLM processing error: {e}")
            # Yield a fallback error message
            yield Message(
                id=-1,
                chat_uuid=chat_uuid,
                sender="assistant",
                message_type="text",
                content="I'm sorry, I encountered an error processing your message. Please try again.",
                created_at=datetime.utcnow()
            )
            return
            
        # 5. Parse the complete JSON response
        llm_json = self._extract_json_from_response(llm_response_text)

        if not llm_json:
            print(f"ERROR: Could not parse JSON from LLM response: {llm_response_text}")
            # Yield a fallback error message
            yield Message(
                id=-1,
                chat_uuid=chat_uuid,
                sender="assistant",
                message_type="text",
                content="I'm sorry, I encountered an error. Please try again.",
                created_at=datetime.utcnow()
            )
            return
            
        # 6. Process the structured response
        response_type = llm_json.get("response_type", "text")
        content = llm_json.get("content", "I'm not sure how to respond.")
        options = llm_json.get("options")
        new_symptoms_from_model = llm_json.get("new_symptoms", [])

        # Check for new symptoms returned by the model and update the symptom list
        if new_symptoms_from_model:
            # Add new symptoms to the chat's symptom list
            chat.symptom_list = list(set((chat.symptom_list or []) + new_symptoms_from_model))
            self.db.commit()
            print(f"New symptoms detected by model: {new_symptoms_from_model}. Updated symptom list: {chat.symptom_list}")

        # If the user is responding with their feeling, save it to the chat
        if message.message_type == 'feeling_response':
            chat.overall_feeling = message.content
            self.db.commit()

        # Normalize message type for database storage (convert hyphenated to underscore)
        db_message_type = response_type.replace('-', '_')
        if response_type.lower() in ["summary", "end"]:
            db_message_type = 'text'

        # 7. Save and yield the assistant's message
        # If this is the summary, format the content for the user
        if response_type == "summary":
            summary_data = llm_json.get("summary_data", {})
            bulleted_summary = summary_data.get("bulleted_summary", "No summary available.")
            
            # Format the bulleted summary with proper bullet points
            if bulleted_summary and bulleted_summary != "No summary available.":
                # Handle both string and list formats
                if isinstance(bulleted_summary, list):
                    # If it's already a list, use it directly
                    bullet_lines = bulleted_summary
                else:
                    # If it's a string, split by newlines
                    bullet_lines = bulleted_summary.split('\n')
                
                formatted_bullets = []
                for line in bullet_lines:
                    if isinstance(line, str) and line.strip():  # Only add non-empty string lines
                        formatted_bullets.append(f"• {line.strip()}")
                    elif not isinstance(line, str) and line:  # Handle non-string items
                        formatted_bullets.append(f"• {str(line).strip()}")
                
                bullet_text = '<br>'.join(formatted_bullets) if formatted_bullets else "• No summary available."
            else:
                bullet_text = "• No summary available."
            
            content = f"<b>Thank you for completing this chat!</b><br><br>Here is your conversation summary:<br><br>{bullet_text}"

        assistant_msg = MessageModel(
            chat_uuid=chat_uuid,
            sender="assistant",
            message_type=db_message_type,
            content=content,
            structured_data={"options": options} if options else None
        )
        self.db.add(assistant_msg)
        self.db.commit()
        self.db.refresh(assistant_msg)
        
        # Create the frontend message with the original response type
        frontend_message = Message.from_orm(assistant_msg)
        frontend_message.message_type = response_type if response_type != 'summary' else 'text'
        
        yield frontend_message

        # 8. If the conversation is done, update the chat with the summary and mark as completed
        if response_type in ["summary", "end"]:
            summary_data = llm_json.get("summary_data", {})
            
            chat.symptom_list = summary_data.get("symptom_list", chat.symptom_list)
            chat.severity_list = summary_data.get("severity_list", chat.severity_list)
            chat.longer_summary = summary_data.get("longer_summary", chat.longer_summary)
            chat.medication_list = summary_data.get("medication_list", chat.medication_list)
            chat.bulleted_summary = summary_data.get("bulleted_summary", chat.bulleted_summary)
            chat.overall_feeling = summary_data.get("overall_feeling", chat.overall_feeling)

            if response_type == "summary":
                chat.conversation_state = ConversationState.COMPLETED
            elif response_type == "end":
                chat.conversation_state = ConversationState.EMERGENCY

            self.db.commit()

    def get_connection_ack(self, chat_uuid: UUID) -> ConnectionEstablished:
        """Returns a connection acknowledgment message."""
        return ConnectionEstablished(
            content="Connection established successfully.",
            chat_state={
                "chat_uuid": str(chat_uuid),
                "status": "connected"
            }
        )

    def get_or_create_today_session(self, patient_uuid: UUID, user_timezone: str = "America/Los_Angeles") -> Tuple[ChatModel, List[MessageModel], bool]:
        """
        Gets the most recent chat for today, or creates a new one if none exists.
        Uses user's timezone to determine what "today" means.
        """
        # Get today's date in user's timezone
        user_tz = pytz.timezone(user_timezone)
        user_now = datetime.now(user_tz)
        today_start = datetime.combine(user_now.date(), time.min)
        today_end = datetime.combine(user_now.date(), time.max)
        
        # Convert to UTC for database query
        utc_today_start = user_tz.localize(today_start).astimezone(pytz.UTC)
        utc_today_end = user_tz.localize(today_end).astimezone(pytz.UTC)
        
        # Query for today's chat in user's timezone
        today_chat = self.db.query(ChatModel).filter(
            ChatModel.patient_uuid == patient_uuid,
            ChatModel.created_at >= utc_today_start,
            ChatModel.created_at <= utc_today_end
        ).order_by(ChatModel.created_at.desc()).first()
        
        if today_chat:
            messages = self.db.query(MessageModel).filter(
                MessageModel.chat_uuid == today_chat.uuid
            ).order_by(MessageModel.created_at).all()
            return today_chat, messages, False
        else:
            # Create new chat for today
            new_chat, initial_question = self.create_chat(patient_uuid, commit=True)  # Commit the chat first
            
            # Create the first assistant message
            first_message = MessageModel(
                chat_uuid=new_chat.uuid,
                sender="assistant",
                message_type=initial_question["type"],
                content=initial_question["text"],
                structured_data={"options": initial_question["options"]} if initial_question.get("options") else None
            )
            
            # Add the message to the database
            self.db.add(first_message)
            self.db.commit()
            self.db.refresh(first_message)
            
            return new_chat, [first_message], True
