from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from src.shared.config import settings

Base = declarative_base()

class Book(Base):
    __tablename__ = 'books'
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), index=True)
    author = Column(String(255), nullable=True)
    filepath = Column(String(500), unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    wisdom_chunks = relationship("WisdomChunk", back_populates="book")

class WisdomChunk(Base):
    __tablename__ = 'wisdom_chunks'
    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey('books.id'))
    
    # Metadata extracted by LLM
    theme = Column(String(100)) # e.g., "Career", "Relationship"
    core_wisdom = Column(Text)
    original_text = Column(Text) # The raw chunk from book
    elaboration = Column(Text)
    actionable_tip = Column(Text)
    emotion_tag = Column(String(50))
    suitable_scene = Column(String(100))
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    book = relationship("Book", back_populates="wisdom_chunks")
    videos = relationship("Video", back_populates="wisdom_chunk")

class Video(Base):
    __tablename__ = 'videos'
    id = Column(Integer, primary_key=True, index=True)
    wisdom_chunk_id = Column(Integer, ForeignKey('wisdom_chunks.id'))
    
    title = Column(String(255))
    script_content = Column(Text)
    audio_path = Column(String(500))
    video_path = Column(String(500))
    
    # Publishing status
    platform = Column(String(50), default="douyin")
    status = Column(String(50), default="draft") # draft, generated, published, failed
    publish_time = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    wisdom_chunk = relationship("WisdomChunk", back_populates="videos")

# Database Setup
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """
    已弃用：建表/迁移改用 Alembic。

    - 全新环境：先 `alembic upgrade head`，再启动 app。
    - 已有 DB：先 `alembic stamp head` 标记基线，再 `alembic upgrade head`。
    - 仅在 `INIT_DB_FALLBACK=1` 时仍会跑 `Base.metadata.create_all`（仅用于开发环境的快速 hack）。
    """
    import os
    if os.environ.get("INIT_DB_FALLBACK") == "1":
        Base.metadata.create_all(bind=engine)
        return
    from src.shared.logger import logger
    logger.info(
        "init_db() noop — schema is managed by Alembic. "
        "Run `alembic upgrade head` if you haven't."
    )
