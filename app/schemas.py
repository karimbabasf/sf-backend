import base64
import binascii
import re
from datetime import datetime, timezone
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    field_validator,
)

from app.models import AddressType

MAX_PHOTO_BYTES = 512 * 1024
MAX_PHOTO_KB = MAX_PHOTO_BYTES // 1024
# Base64 inflates by 4/3 and pads to a multiple of 4. Checked before decoding so
# an oversized payload costs a length comparison rather than an allocation.
MAX_PHOTO_B64_CHARS = ((MAX_PHOTO_BYTES + 2) // 3) * 4

PHOTO_MIME_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")

_PHOTO_DATA_URL = re.compile(
    r"data:(?P<mime>image/(?:png|jpeg|webp|gif));base64,(?P<data>[A-Za-z0-9+/]+={0,2})",
    re.DOTALL,
)

# Leading bytes every decoder uses to recognise the format, so the declared MIME
# type has to match the actual content. Cheaper and narrower than an imaging
# dependency, which this service does not otherwise need.
_PHOTO_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}


def _is_webp(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def _check_photo(value: str) -> str:
    """Reject anything that is not a small, base64-encoded raster image."""
    photo = value.strip()

    match = _PHOTO_DATA_URL.fullmatch(photo)
    if match is None:
        raise ValueError(f"Photo must be a base64 data URL for one of: {', '.join(PHOTO_MIME_TYPES)}")

    encoded = match.group("data")
    if len(encoded) > MAX_PHOTO_B64_CHARS:
        raise ValueError(f"Photo must be {MAX_PHOTO_KB} KB or smaller")

    try:
        decoded = base64.b64decode(encoded, validate=True)
    except binascii.Error as exc:
        raise ValueError("Photo is not valid base64") from exc

    if not decoded:
        raise ValueError("Photo is empty")
    # Backstop: padding means the encoded length bounds the decoded size loosely.
    if len(decoded) > MAX_PHOTO_BYTES:
        raise ValueError(f"Photo must be {MAX_PHOTO_KB} KB or smaller")

    mime = match.group("mime")
    signatures = _PHOTO_SIGNATURES.get(mime)
    matches = _is_webp(decoded) if signatures is None else decoded.startswith(signatures)
    if not matches:
        raise ValueError(f"Photo content does not match the declared type {mime}")

    return photo


PhotoDataUrl = Annotated[str, AfterValidator(_check_photo)]

_EXAMPLE_PHOTO = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _trim(value: object) -> object:
    """Strip padding whitespace so `"  "` fails the length check instead of being stored."""
    return value.strip() if isinstance(value, str) else value


def _trim_or_none(value: object) -> object:
    """Same as `_trim`, but an optional field left blank is stored as `null`, never `""`."""
    trimmed = _trim(value)
    return (trimmed or None) if isinstance(trimmed, str) else trimmed


Trimmed = Annotated[str, BeforeValidator(_trim)]
TrimmedOrNone = Annotated[str | None, BeforeValidator(_trim_or_none)]


class AddressBase(BaseModel):
    """Fields shared by every address request and response."""

    type: AddressType = Field(
        description="Which kind of address this is. One of `Home`, `Work`, or `Other`.",
        examples=[AddressType.HOME],
    )
    street: Trimmed = Field(
        min_length=1,
        max_length=300,
        description="Street address, including unit or suite. Required: an address needs a line to be one.",
        examples=["1 Market St, Suite 400"],
    )
    city: TrimmedOrNone = Field(
        default=None, max_length=120, description="City or locality.", examples=["San Francisco"]
    )
    state: TrimmedOrNone = Field(
        default=None,
        max_length=120,
        description="State, province, or region.",
        examples=["CA"],
    )
    postal_code: TrimmedOrNone = Field(
        default=None,
        max_length=20,
        description="Postal or ZIP code.",
        examples=["94105"],
    )
    country: TrimmedOrNone = Field(default=None, max_length=120, description="Country name.", examples=["USA"])


_HOME_ADDRESS_EXAMPLE = {
    "type": "Home",
    "street": "12 Ockham Rd",
    "city": "Ockham",
    "state": "Surrey",
    "postal_code": "GU23 6NP",
    "country": "UK",
}
_WORK_ADDRESS_EXAMPLE = {
    "type": "Work",
    "street": "1 Market St, Suite 400",
    "city": "San Francisco",
    "state": "CA",
    "postal_code": "94105",
    "country": "USA",
}

MAX_ADDRESSES = 10
ADDRESSES_DESCRIPTION = (
    "Every address held for this contact, in any mix of types. A contact can have as "
    "many as you send. Omit the field or send `[]` for a contact with no address."
)


class AddressCreate(AddressBase):
    """One address inside a contact create, replace, or update request."""

    model_config = ConfigDict(json_schema_extra={"examples": [_HOME_ADDRESS_EXAMPLE, _WORK_ADDRESS_EXAMPLE]})


class AddressRead(AddressBase):
    """A stored address, as returned inside its contact."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{**_HOME_ADDRESS_EXAMPLE, "id": 1}]},
    )

    id: int = Field(description="Server-assigned identifier.", examples=[1])


class ContactBase(BaseModel):
    """Fields shared by every contact request and response."""

    first_name: str = Field(
        min_length=1,
        max_length=100,
        description="Given name. Required, must not be blank.",
        examples=["Ada"],
    )
    last_name: str = Field(
        min_length=1,
        max_length=100,
        description="Family name. Required, must not be blank.",
        examples=["Lovelace"],
    )
    email: EmailStr = Field(
        max_length=320,
        description=(
            "Primary email address. Required and unique across all contacts; "
            "compared case-insensitively and stored lowercased."
        ),
        examples=["ada@example.com"],
    )
    phone: str | None = Field(
        default=None,
        max_length=40,
        description="Phone number. Stored verbatim — any format is accepted.",
        examples=["+1-415-555-0101"],
    )
    photo: PhotoDataUrl | None = Field(
        default=None,
        description=(
            "Profile picture as a base64 data URL. "
            f"One of {', '.join(PHOTO_MIME_TYPES)}, up to {MAX_PHOTO_KB} KB decoded. "
            "Omit or send `null` for no photo."
        ),
        examples=[_EXAMPLE_PHOTO],
    )
    company: str | None = Field(
        default=None,
        max_length=200,
        description="Employer or organisation name.",
        examples=["Analytical Engines"],
    )
    job_title: str | None = Field(
        default=None,
        max_length=200,
        description="Role held at the company.",
        examples=["Mathematician"],
    )
    notes: str | None = Field(
        default=None,
        description="Free-form notes about the contact. No length limit.",
        examples=["Met at the SF hackathon."],
    )
    addresses: list[AddressCreate] = Field(
        default_factory=list,
        max_length=MAX_ADDRESSES,
        description=f"{ADDRESSES_DESCRIPTION} At most {MAX_ADDRESSES}.",
        examples=[[_HOME_ADDRESS_EXAMPLE, _WORK_ADDRESS_EXAMPLE]],
    )


_FULL_EXAMPLE = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.com",
    "phone": "+1-415-555-0101",
    "photo": _EXAMPLE_PHOTO,
    "company": "Analytical Engines",
    "job_title": "Mathematician",
    "notes": "Met at the SF hackathon.",
    "addresses": [_HOME_ADDRESS_EXAMPLE, _WORK_ADDRESS_EXAMPLE],
}
_MINIMAL_EXAMPLE = {"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"}


class ContactCreate(ContactBase):
    """Body of `POST /api/v1/contacts`. Only the two names and email are required."""

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE, _MINIMAL_EXAMPLE]})


class ContactReplace(ContactBase):
    """
    Body of `PUT /api/v1/contacts/{contact_id}`.

    This is a full replacement: any optional field you omit is set back to `null`.
    Use `PATCH` if you only want to change some fields.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE]})


class ContactUpdate(BaseModel):
    """
    Body of `PATCH /api/v1/contacts/{contact_id}`.

    Every field is optional. Only the fields actually present in the request are
    written; omitted fields keep their current value. Sending an explicit `null`
    clears that field.
    """

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"phone": "+1-415-555-0199", "job_title": "Chief Engineer"}]}
    )

    first_name: str | None = Field(default=None, min_length=1, max_length=100, description="New given name.")
    last_name: str | None = Field(default=None, min_length=1, max_length=100, description="New family name.")
    email: EmailStr | None = Field(
        default=None,
        max_length=320,
        description="New email address. Must not belong to another contact.",
    )
    phone: str | None = Field(default=None, max_length=40, description="New phone number.")
    photo: PhotoDataUrl | None = Field(
        default=None,
        description="New profile picture as a base64 data URL, or `null` to remove the current one.",
    )
    company: str | None = Field(default=None, max_length=200, description="New company.")
    job_title: str | None = Field(default=None, max_length=200, description="New job title.")
    notes: str | None = Field(default=None, description="New notes; replaces the existing text.")
    addresses: list[AddressCreate] | None = Field(
        default=None,
        max_length=MAX_ADDRESSES,
        description=(
            "Replaces the contact's whole address set. Sending `[]` or `null` removes "
            "every address; omitting the field leaves them untouched."
        ),
    )


class ContactRead(ContactBase):
    """A stored contact, as returned by every contact endpoint."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    **_FULL_EXAMPLE,
                    "id": 1,
                    "full_name": "Ada Lovelace",
                    "addresses": [{**_HOME_ADDRESS_EXAMPLE, "id": 1}, {**_WORK_ADDRESS_EXAMPLE, "id": 2}],
                    "created_at": "2026-08-19T16:22:58.189507Z",
                    "updated_at": "2026-08-19T16:22:58.189511Z",
                }
            ]
        },
    )

    id: int = Field(description="Server-assigned identifier.", examples=[1])
    addresses: list[AddressRead] = Field(
        description=f"{ADDRESSES_DESCRIPTION} Ordered oldest first.",
        examples=[[{**_HOME_ADDRESS_EXAMPLE, "id": 1}]],
    )
    created_at: datetime = Field(
        description="UTC timestamp of when the contact was created.",
        examples=["2026-08-19T16:22:58.189507Z"],
    )
    updated_at: datetime = Field(
        description="UTC timestamp of the last modification.",
        examples=["2026-08-19T16:22:58.189511Z"],
    )

    @field_validator("created_at", "updated_at")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        # SQLite discards tzinfo on write; the stored values are UTC, so label
        # them as such rather than emitting an ambiguous naive timestamp.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @computed_field(description="Convenience concatenation of first and last name.", examples=["Ada Lovelace"])
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class ContactPage(BaseModel):
    """One page of contacts plus the totals a client needs to paginate."""

    items: list[ContactRead] = Field(description="Contacts on this page, ordered by the requested sort.")
    total: int = Field(
        description="Total contacts matching the query, ignoring `limit` and `offset`.",
        examples=[42],
    )
    limit: int = Field(description="Page size that was applied.", examples=[50])
    offset: int = Field(description="Number of records skipped.", examples=[0])


class HealthResponse(BaseModel):
    """Result of the liveness probe."""

    status: str = Field(description="Always `ok` when the service can serve traffic.", examples=["ok"])
    database: str = Field(description="Active SQLAlchemy dialect.", examples=["sqlite"])
    contacts: int = Field(description="Number of contacts currently stored.", examples=[3])


class RootResponse(BaseModel):
    """Discovery document listing the API's entry points."""

    name: str = Field(description="Human-readable service name.", examples=["Contacts API"])
    version: str = Field(description="Service version.", examples=["0.1.0"])
    docs: str = Field(description="Path to the Swagger UI.", examples=["/docs"])
    redoc: str = Field(description="Path to the ReDoc UI.", examples=["/redoc"])
    openapi: str = Field(description="Path to the OpenAPI 3.1 document.", examples=["/openapi.json"])
    contacts: str = Field(description="Base path of the contacts collection.", examples=["/api/v1/contacts"])
    health: str = Field(description="Path to the liveness probe.", examples=["/health"])


class ErrorResponse(BaseModel):
    """Shape of every non-validation error returned by the API."""

    detail: str = Field(
        description="Human-readable explanation of the failure.",
        examples=["Contact 42 not found"],
    )
