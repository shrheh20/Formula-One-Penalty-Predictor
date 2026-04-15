"""Database primitives for FIA document ingestion."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./data/fia_documents.db",
)

CONNECT_ARGS = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
    connect_args=CONNECT_ARGS,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("doc_number", "grand_prix", name="uq_documents_doc_gp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    doc_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    grand_prix: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    published_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    pdf_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    local_file: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_recalled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    extraction_status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    extraction_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("document_id", "signal_type", "entity_key", name="uq_signals_doc_type_entity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    grand_prix: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    session: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    driver: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    team: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    car_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    entity_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    published_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("signal_id", "title", name="uq_alerts_signal_title"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="medium", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    grand_prix: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    published_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


def init_db() -> None:
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations() -> None:
    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("documents")}
    migrations = {
        "document_type": "ALTER TABLE documents ADD COLUMN document_type VARCHAR(128)",
        "extraction_status": "ALTER TABLE documents ADD COLUMN extraction_status VARCHAR(64)",
        "extraction_version": "ALTER TABLE documents ADD COLUMN extraction_version VARCHAR(64)",
        "extraction_confidence": "ALTER TABLE documents ADD COLUMN extraction_confidence FLOAT",
        "needs_review": "ALTER TABLE documents ADD COLUMN needs_review BOOLEAN DEFAULT FALSE",
        "parser_output": "ALTER TABLE documents ADD COLUMN parser_output JSON",
    }

    with engine.begin() as connection:
        for column_name, ddl in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(ddl))


def get_db_session() -> Generator:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
