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
    source_page_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    local_file: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    document_family: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    extraction_status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    extraction_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dashboard_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    dashboard_summary_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dashboard_summary_version: Mapped[str | None] = mapped_column(String(64), nullable=True)


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


class DocumentEntity(Base):
    __tablename__ = "document_entities"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "entity_type",
            "entity_value",
            name="uq_document_entities_document_type_value",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_value: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_role: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
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

    is_postgres = engine.dialect.name == "postgresql"
    datetime_type = "TIMESTAMP" if is_postgres else "DATETIME"
    json_type = "JSONB" if is_postgres else "JSON"

    existing_columns = {column["name"] for column in inspector.get_columns("documents")}
    migrations = {
        "source_page_url": "ALTER TABLE documents ADD COLUMN source_page_url VARCHAR(1024)",
        "pdf_sha256": "ALTER TABLE documents ADD COLUMN pdf_sha256 VARCHAR(64)",
        "downloaded_at": f"ALTER TABLE documents ADD COLUMN downloaded_at {datetime_type}",
        "document_type": "ALTER TABLE documents ADD COLUMN document_type VARCHAR(128)",
        "document_family": "ALTER TABLE documents ADD COLUMN document_family VARCHAR(128)",
        "extraction_status": "ALTER TABLE documents ADD COLUMN extraction_status VARCHAR(64)",
        "extraction_version": "ALTER TABLE documents ADD COLUMN extraction_version VARCHAR(64)",
        "extraction_confidence": "ALTER TABLE documents ADD COLUMN extraction_confidence FLOAT",
        "needs_review": "ALTER TABLE documents ADD COLUMN needs_review BOOLEAN DEFAULT FALSE",
        "parser_output": f"ALTER TABLE documents ADD COLUMN parser_output {json_type}",
        "raw_text": "ALTER TABLE documents ADD COLUMN raw_text TEXT",
        "extracted_data": f"ALTER TABLE documents ADD COLUMN extracted_data {json_type}",
        "ai_result": f"ALTER TABLE documents ADD COLUMN ai_result {json_type}",
        "dashboard_summary": "ALTER TABLE documents ADD COLUMN dashboard_summary TEXT",
        "dashboard_summary_provider": "ALTER TABLE documents ADD COLUMN dashboard_summary_provider VARCHAR(64)",
        "dashboard_summary_version": "ALTER TABLE documents ADD COLUMN dashboard_summary_version VARCHAR(64)",
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
