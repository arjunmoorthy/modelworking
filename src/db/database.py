import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv
from typing import Generator
import logging
import urllib.parse

logger = logging.getLogger(__name__)

load_dotenv()

# --- Database Connection Details ---
# A dictionary to hold connection details for multiple databases.
# This makes the setup scalable and easy to manage.
DATABASE_CONFIG = {
    "patient_db": {
        "user": os.getenv("PATIENT_DB_USER"),
        "password": os.getenv("PATIENT_DB_PASSWORD"),
        "host": os.getenv("PATIENT_DB_HOST"),
        "port": os.getenv("PATIENT_DB_PORT"),
        "name": os.getenv("PATIENT_DB_NAME"),
    },
    # Configuration for the Doctor Database
    "doctor_db": {
        "user": os.getenv("DOCTOR_DB_USER"),
        "password": os.getenv("DOCTOR_DB_PASSWORD"),
        "host": os.getenv("DOCTOR_DB_HOST"),
        "port": os.getenv("DOCTOR_DB_PORT"),
        "name": os.getenv("DOCTOR_DB_NAME"),
    }
}

# --- SQLAlchemy Engine Creation ---
# Create a separate engine for each database found in the config.
engines = {}
for db_name, config in DATABASE_CONFIG.items():
    if all(config.values()):  # Only create an engine if all details are provided
        # URL encode the password to handle special characters
        encoded_password = urllib.parse.quote_plus(config['password'])
        
        conn_url = (
            f"postgresql://{config['user']}:{encoded_password}@"
            f"{config['host']}:{config['port']}/{config['name']}"
        )
        logger.info(f"-----------------------------------Connecting to {db_name}: {config['user']}@{config['host']}:{config['port']}/{config['name']}")
        
        # Add SSL mode and connection pooling for AWS RDS
        engines[db_name] = create_engine(
            conn_url,
            pool_pre_ping=True,  # Test connections before use
            pool_recycle=1800,   # Recycle connections every 30 minutes
            pool_size=5,         # Limit pool size
            max_overflow=10,     # Allow some overflow
            connect_args={
                "sslmode": "require",  # Force SSL for AWS RDS
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
                "connect_timeout": 10,
                "application_name": "oncolife-api"
            }
        )

# --- Session Factories ---
# Create a session factory for each engine.
SessionFactories = {name: sessionmaker(autocommit=False, autoflush=False, bind=engine) for name, engine in engines.items()}

# --- Database Dependencies ---
# These are the reusable dependencies that our API routes will use.
# Each function provides a session to a specific database.

def get_patient_db() -> Generator[Session, None, None]:
    """Dependency to get a session for the Patient Database."""
    if "patient_db" not in SessionFactories:
        raise RuntimeError("Patient database is not configured. Check your .env file.")
    
    db = SessionFactories["patient_db"]()
    try:
        yield db
    finally:
        db.close()

def get_doctor_db() -> Generator[Session, None, None]:
    """Dependency to get a session for the Doctor Database."""
    if "doctor_db" not in SessionFactories:
        raise RuntimeError("Doctor database is not configured. Check your .env file.")
    
    db = SessionFactories["doctor_db"]()
    try:
        yield db
    finally:
        db.close() 
