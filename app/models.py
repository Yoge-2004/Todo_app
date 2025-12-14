from datetime import datetime, date
from typing import Optional, List
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship

class Status(str, Enum):
    PENDING = "Pending"
    COMPLETED = "Completed"

class Priority(str, Enum):
    LOW = "Low"
    NORMAL = "Normal"
    HIGH = "High"

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str
    tasks: List["Task"] = Relationship(back_populates="owner")

class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    deadline: date
    priority: Priority = Field(default=Priority.NORMAL)
    status: Status = Field(default=Status.PENDING)
    created_on: datetime = Field(default_factory=datetime.now)
    
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    owner: Optional[User] = Relationship(back_populates="tasks")
  
