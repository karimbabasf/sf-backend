from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AddressType(str, Enum):
    """The kinds of address a contact can hold."""

    HOME = "Home"
    WORK = "Work"
    OTHER = "Other"


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    first_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))

    # Base64 data URL rather than a file path, so a contact stays one row with
    # no storage backend to configure. Size is capped in the schema.
    photo: Mapped[str | None] = mapped_column(Text)

    company: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(200))

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )

    # Loaded with the contact so a page of contacts costs two queries, not N+1.
    # `delete-orphan` drops rows dropped from the list; the FK's ON DELETE CASCADE
    # is the database-side backstop for a contact deleted by any other route.
    addresses: Mapped[list["Address"]] = relationship(
        back_populates="contact",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Address.id",
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Contact id={self.id} email={self.email!r}>"


class Address(Base):
    """One postal address belonging to a contact. A contact may have any number."""

    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Stored as its label ("Home") behind a CHECK constraint, so the allowed set
    # is enforced by the database and not only by the request schema.
    type: Mapped[AddressType] = mapped_column(
        SQLEnum(
            AddressType,
            name="address_type",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
    )

    street: Mapped[str] = mapped_column(String(300), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(120))

    contact: Mapped["Contact"] = relationship(back_populates="addresses")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Address id={self.id} contact_id={self.contact_id} type={self.type.value!r}>"
