"""
Modelo de dados para o sistema de logging estruturado.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from sqlalchemy.sql import func
from database import Base


class LogEntry(Base):
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    level = Column(String(10), nullable=False, index=True)
    module = Column(String(30), nullable=False, index=True)
    sub_module = Column(String(50), nullable=True, index=True)
    message = Column(Text, nullable=False)
    extra_json = Column(Text, nullable=True)
    traceback = Column(Text, nullable=True)
    session_id = Column(Integer, nullable=True, index=True)
    request_id = Column(String(36), nullable=True, index=True)

    # Índice composto para queries do frontend (aba + filtro de nível)
    __table_args__ = (
        Index("ix_log_module_level", "module", "level"),
    )

    def __repr__(self):
        return f"<LogEntry {self.id} [{self.level}] {self.module}.{self.sub_module}: {self.message[:50]}>"
