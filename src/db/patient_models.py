from sqlalchemy import (
    Column, 
    Integer, 
    String, 
    DateTime, 
    Date, 
    Time, 
    Boolean,
    func,
    ForeignKey,
    Text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
import uuid

# A single Base for all models in this file to inherit from.
Base = declarative_base()

class Conversations(Base):
    __tablename__ = 'conversations'
    uuid = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    patient_uuid = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    conversation_state = Column(String)
    symptom_list = Column(JSONB, nullable=True)
    severity_list = Column(JSONB, nullable=True)
    longer_summary = Column(Text, nullable=True)
    medication_list = Column(JSONB, nullable=True)
    bulleted_summary = Column(Text, nullable=True)
    overall_feeling = Column(String, nullable=True)

    # Relationship to the Messages table
    messages = relationship(
        "Messages", 
        back_populates="conversation", 
        cascade="all, delete-orphan",
        order_by="Messages.created_at"
    )

class Messages(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_uuid = Column(UUID(as_uuid=True), ForeignKey('conversations.uuid'), nullable=False, index=True)
    
    sender = Column(String, nullable=False) # 'user', 'assistant', 'system'
    message_type = Column(String, nullable=False) # e.g., 'text', 'button_response'
    content = Column(Text, nullable=False)
    structured_data = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    conversation = relationship("Conversations", back_populates="messages")


class PatientChemoDates(Base):
    __tablename__ = 'patient_chemo_dates'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    patient_uuid = Column(UUID(as_uuid=True), nullable=False, index=True)
    chemo_date = Column(Date, nullable=False)

class PatientDiaryEntries(Base):
    __tablename__ = 'patient_diary_entries'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    patient_uuid = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(String, nullable=True)
    diary_entry = Column(String, nullable=False)
    entry_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    marked_for_doctor = Column(Boolean, server_default='false', nullable=False)

class PatientConfigurations(Base):
    __tablename__ = 'patient_configurations'
    uuid = Column(UUID(as_uuid=True), primary_key=True, comment="This is the patient's Cognito sub/uuid.")
    reminder_method = Column(String)
    reminder_time = Column(Time)
    acknowledgement_done = Column(Boolean)
    agreed_conditions = Column(Boolean)
    is_deleted = Column(Boolean, nullable=False, server_default='false')

class PatientInfo(Base):
    __tablename__ = 'patient_info'
    uuid = Column(UUID(as_uuid=True), primary_key=True, comment="This is the patient's Cognito sub/uuid.")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    email_address = Column(String, unique=True, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    sex = Column(String)
    dob = Column(Date)
    mrn = Column(String, unique=True)
    ethnicity = Column(String)
    phone_number = Column(String)
    disease_type = Column(String)
    treatment_type = Column(String)
    is_deleted = Column(Boolean, nullable=False, server_default='false')

class PatientPhysicianAssociations(Base):
    __tablename__ = 'patient_physician_associations'
    id = Column(Integer, primary_key=True)
    patient_uuid = Column(UUID(as_uuid=True), nullable=False, index=True)
    physician_uuid = Column(UUID(as_uuid=True), nullable=False, index=True)
    clinic_uuid = Column(UUID(as_uuid=True), nullable=False, index=True)
    is_deleted = Column(Boolean, nullable=False, server_default='false') 