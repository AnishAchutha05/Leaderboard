
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Float,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint,
    Enum,
)
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    public_profile_url = Column(String(500), nullable=False)

    completions = relationship("Completion", back_populates="user")
    scrape_logs = relationship("ScrapeLog", back_populates="user")


class Badge(Base):
    __tablename__ = "badges"

    id = Column(String(100), primary_key=True)
    name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)

    labs = relationship("Lab", back_populates="badge")
    completions = relationship("Completion", back_populates="badge")


class Lab(Base):
    __tablename__ = "labs"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    item_type = Column(
        Enum("Course", "Challenge Lab", name="lab_item_type"),
        nullable=False
    )
    total_credits = Column(Integer, nullable=False)
    url = Column(String(1000), nullable=False)
    badge_id = Column(
        String(100),
        ForeignKey("badges.id"),
        nullable=False
    )

    __table_args__ = (Index("ix_labs_badge_id", "badge_id"),)

    badge = relationship("Badge", back_populates="labs")
    completions = relationship("Completion", back_populates="lab")


class Completion(Base):
    __tablename__ = "completions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    badge_id = Column(String(100), ForeignKey("badges.id"), nullable=False)
    lab_id = Column(Integer, ForeignKey("labs.id"), nullable=False)
    is_completed = Column(Boolean, default=True, nullable=False)
    earned_at = Column(DateTime(timezone=True), nullable=True)
    first_detected_at = Column(DateTime(timezone=True), nullable=False)
    last_verified_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),
        Index("ix_completions_user_id", "user_id"),
        Index("ix_completions_badge_id", "badge_id"),
        Index("ix_completions_lab_id", "lab_id"),
    )

    user = relationship("User", back_populates="completions")
    badge = relationship("Badge", back_populates="completions")
    lab = relationship("Lab", back_populates="completions")


class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(
        Enum("Success", "Failed", name="scrape_status"),
        nullable=False
    )
    badges_found = Column(Integer, default=0, nullable=False)
    new_badges_found = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (Index("ix_scrape_logs_user_id", "user_id"),)

    user = relationship("User", back_populates="scrape_logs")


class EventStat(Base):
    __tablename__ = "event_stats"

    id = Column(Integer, primary_key=True)
    hour_bucket = Column(DateTime(timezone=True), nullable=False, unique=True)
    total_users = Column(Integer, nullable=False)
    total_completed_badges = Column(Integer, nullable=False)
    new_badge_completions = Column(Integer, nullable=False)
    unique_users_with_new_badges = Column(Integer, nullable=False)
    completion_rate = Column(Float, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
