import os
from sqlmodel import SQLModel, create_engine, Session

# Auto-detect: Use Render's DB if available, otherwise local file
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./tasks.db")

# Fix Render's URL format if needed
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Configure connection
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
      
