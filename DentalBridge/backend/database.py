from sqlalchemy import create_engine, Column, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import uuid

SQLALCHEMY_DATABASE_URL = "sqlite:///./dental.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class TreatmentPlan(Base):
    __tablename__ = "treatment_plans"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    patient_name = Column(String, default="Unknown Patient")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    items = relationship("PlanItem", back_populates="plan", cascade="all, delete-orphan")

class PlanItem(Base):
    __tablename__ = "plan_items"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    plan_id = Column(String, ForeignKey("treatment_plans.id"))
    
    code = Column(String)
    technical_name = Column(String)
    friendly_name = Column(String)
    explanation = Column(Text)
    urgency = Column(String)
    price = Column(Float, nullable=True)
    urgency_hook = Column(Text, nullable=True)

    plan = relationship("TreatmentPlan", back_populates="items")
