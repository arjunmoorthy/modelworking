from enum import Enum

class ConversationState(str, Enum):
    """
    Defines the distinct states a conversation can be in, acting as a state machine.
    """
    CHEMO_CHECK_SENT = "chemo_check_sent"
    SYMPTOM_SELECTION_SENT = "symptom_selection_sent"
    FOLLOWUP_QUESTIONS = "followup_questions"
    COMPLETED = "COMPLETED"
    EMERGENCY = "EMERGENCY" 