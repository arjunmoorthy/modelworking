from sqlalchemy import (
    Column, 
    Integer, 
    String, 
    DateTime, 
    func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
import uuid

# A separate Base for the doctor database models
DoctorBase = declarative_base()

class AllClinics(DoctorBase):
    __tablename__ = 'all_clinics'
    uuid = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, server_default=func.now())
    clinic_name = Column(String)
    address = Column(String)
    phone_number = Column(String)
    fax_number = Column(String)

class StaffProfiles(DoctorBase):
    __tablename__ = 'staff_profiles'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, server_default=func.now())
    staff_uuid = Column(UUID(as_uuid=True), unique=True, default=uuid.uuid4)
    email_address = Column(String, unique=True, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    role = Column(String)
    npi_number = Column(String, nullable=True)

class StaffAssociations(DoctorBase):
    __tablename__ = 'staff_associations'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, server_default=func.now())
    staff_uuid = Column(UUID(as_uuid=True), nullable=False, index=True)
    physician_uuid = Column(UUID(as_uuid=True), nullable=False, index=True)
    clinic_uuid = Column(UUID(as_uuid=True), nullable=False, index=True) 
