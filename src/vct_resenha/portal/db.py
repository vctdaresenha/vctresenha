from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from ..config import AppSettings


class Base(DeclarativeBase):
    pass


class PortalUser(Base):
    __tablename__ = "portal_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(120))
    global_name: Mapped[str] = mapped_column(String(120), default="")
    avatar_hash: Mapped[str] = mapped_column(String(120), default="")
    riot_id: Mapped[str] = mapped_column(String(64), default="")
    riot_id_normalized: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team: Mapped[PortalTeam | None] = relationship(back_populates="owner", uselist=False)
    submissions: Mapped[list[TeamSubmission]] = relationship(back_populates="owner")


class PortalTeam(Base):
    __tablename__ = "portal_teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("portal_users.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    coach: Mapped[str] = mapped_column(String(120))
    logo_filename: Mapped[str] = mapped_column(String(255), default="")
    players: Mapped[list[str]] = mapped_column(JSON)
    last_submission_id: Mapped[int | None] = mapped_column(ForeignKey("team_submissions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner: Mapped[PortalUser] = relationship(back_populates="team")


class PortalSetting(Base):
    __tablename__ = "portal_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TeamSubmission(Base):
    __tablename__ = "team_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("portal_users.id"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("portal_teams.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(32), index=True)
    coach: Mapped[str] = mapped_column(String(120))
    logo_filename: Mapped[str] = mapped_column(String(255), default="")
    players: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    terms_accepted: Mapped[int] = mapped_column(Integer, default=0)
    review_notes: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner: Mapped[PortalUser] = relationship(back_populates="submissions")


def build_engine(settings: AppSettings):
    database_file = settings.portal_database_file
    database_file.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{database_file.as_posix()}", future=True)


def build_session_factory(settings: AppSettings) -> sessionmaker:
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        existing_columns = {
            str(row[1]).strip().lower()
            for row in connection.exec_driver_sql("PRAGMA table_info(portal_users)").fetchall()
        }
        if "riot_id" not in existing_columns:
            connection.exec_driver_sql("ALTER TABLE portal_users ADD COLUMN riot_id VARCHAR(64) DEFAULT ''")
        if "riot_id_normalized" not in existing_columns:
            connection.exec_driver_sql("ALTER TABLE portal_users ADD COLUMN riot_id_normalized VARCHAR(64) DEFAULT ''")
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_portal_users_riot_id_normalized ON portal_users (riot_id_normalized) WHERE riot_id_normalized IS NOT NULL AND riot_id_normalized != ''"
        )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)