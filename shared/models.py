"""
SQLAlchemy ORM models — single source of truth for the database schema.
Used by both the bot and the web application.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    user = "user"
    moderator = "moderator"
    admin = "admin"
    owner = "owner"


class RequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AuditAction(str, enum.Enum):
    approve = "approve"
    reject = "reject"
    rescind = "rescind"
    promote = "promote"
    demote = "demote"
    edit = "edit"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=UserRole.user)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    requests: Mapped[list["SerialRequest"]] = relationship(
        "SerialRequest", foreign_keys="SerialRequest.requester_id", back_populates="requester"
    )
    serials: Mapped[list["Serial"]] = relationship(
        "Serial", foreign_keys="Serial.holder_id", back_populates="holder"
    )

    @property
    def avatar_url(self) -> str:
        if self.avatar_hash:
            return f"https://cdn.discordapp.com/avatars/{self.discord_id}/{self.avatar_hash}.png"
        default_index = (int(self.discord_id) >> 22) % 6
        return f"https://cdn.discordapp.com/embed/avatars/{default_index}.png"

    @property
    def is_moderator(self) -> bool:
        return self.role in (UserRole.moderator, UserRole.admin, UserRole.owner)

    @property
    def is_admin(self) -> bool:
        return self.role in (UserRole.admin, UserRole.owner)

    @property
    def is_owner(self) -> bool:
        return self.role == UserRole.owner


class PrinterType(Base):
    """
    A type of printer that can be assigned a serial number.
    Each printer type has its own independent sequential serial number series.
    e.g. BB-001 and CC-001 are entirely different serials.
    """
    __tablename__ = "printer_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # 1–3 uppercase characters used as the serial prefix (e.g. "BB", "BBP", "CC")
    identifier: Mapped[str] = mapped_column(String(3), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Discord role ID to assign when a serial of this type is approved.
    # Stored as a string to avoid integer overflow on large snowflake IDs.
    discord_role_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Discord forum tag ID used to identify this printer type from a thread's applied tags.
    discord_tag_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # NULL = system-seeded or created via CLI bootstrap
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])
    serials: Mapped[list["Serial"]] = relationship("Serial", back_populates="printer_type")

    def format_serial(self, serial_number: int, pad_width: int = 3, delimiter: str = "-") -> str:
        """Return display string like 'BBP-012'."""
        width = max(pad_width, len(str(serial_number)))
        return f"{self.identifier}{delimiter}{serial_number:0{width}d}"


class SerialRequest(Base):
    __tablename__ = "serial_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    printer_type_id: Mapped[int] = mapped_column(ForeignKey("printer_types.id"), nullable=False)
    discord_message_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    post_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RequestStatus.pending
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    requester: Mapped["User"] = relationship(
        "User", foreign_keys=[requester_id], back_populates="requests"
    )
    printer_type: Mapped["PrinterType"] = relationship("PrinterType", foreign_keys=[printer_type_id])
    reviewer: Mapped["User | None"] = relationship("User", foreign_keys=[reviewed_by_id])
    serial: Mapped["Serial | None"] = relationship(
        "Serial", back_populates="request", uselist=False
    )


class Serial(Base):
    __tablename__ = "serials"
    __table_args__ = (
        # Each (printer_type, serial_number) pair must be unique — BBP-001 and CC-001 are distinct
        UniqueConstraint("printer_type_id", "serial_number", name="uq_serial_type_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    printer_type_id: Mapped[int] = mapped_column(ForeignKey("printer_types.id"), nullable=False)
    # Per-type sequential number: BBP-001 has serial_number=1, CC-001 also has serial_number=1
    serial_number: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("serial_requests.id"), unique=True, nullable=False
    )
    holder_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    issued_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    rescinded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rescinded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rescind_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    printer_type: Mapped["PrinterType"] = relationship("PrinterType", back_populates="serials")
    request: Mapped["SerialRequest"] = relationship("SerialRequest", back_populates="serial")
    holder: Mapped["User"] = relationship("User", foreign_keys=[holder_id], back_populates="serials")
    issued_by: Mapped["User"] = relationship("User", foreign_keys=[issued_by_id])
    rescinded_by: Mapped["User | None"] = relationship("User", foreign_keys=[rescinded_by_id])

    @property
    def is_active(self) -> bool:
        return self.rescinded_at is None

    def display(self, pad_width: int = 3, delimiter: str = "-") -> str:
        """Return formatted serial string, e.g. 'BBP-012'."""
        return self.printer_type.format_serial(self.serial_number, pad_width, delimiter)


class SerialReservation(Base):
    """
    Blocks a specific (printer_type, serial_number) pair from auto-assignment.
    Each printer type has its own reservation namespace.
    """
    __tablename__ = "serial_reservations"
    __table_args__ = (
        UniqueConstraint("printer_type_id", "serial_number", name="uq_reservation_type_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    printer_type_id: Mapped[int] = mapped_column(ForeignKey("printer_types.id"), nullable=False)
    serial_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reserved_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    printer_type: Mapped["PrinterType"] = relationship("PrinterType", foreign_keys=[printer_type_id])
    reserved_by: Mapped["User"] = relationship("User", foreign_keys=[reserved_by_id])


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    serial_id: Mapped[int | None] = mapped_column(ForeignKey("serials.id"), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    actor: Mapped["User"] = relationship("User", foreign_keys=[actor_id])
    target_user: Mapped["User | None"] = relationship("User", foreign_keys=[target_user_id])
    serial: Mapped["Serial | None"] = relationship("Serial", foreign_keys=[serial_id])


class SystemConfig(Base):
    """
    Runtime-editable configuration overrides stored in the database.
    Values here take precedence over config.toml / environment variables.
    """
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
