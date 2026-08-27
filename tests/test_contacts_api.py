import base64
import struct
import zlib

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Address
from app.schemas import MAX_ADDRESSES, MAX_PHOTO_BYTES

BASE = "/api/v1/contacts"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"


def test_create_contact(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["created_at"] and body["updated_at"]


def test_create_requires_valid_email(client, payload):
    response = client.post(BASE, json={**payload, "email": "not-an-email"})
    assert response.status_code == 422


def test_create_requires_names(client, payload):
    response = client.post(BASE, json={**payload, "first_name": ""})
    assert response.status_code == 422


def test_duplicate_email_conflicts(client, payload):
    assert client.post(BASE, json=payload).status_code == 201
    response = client.post(BASE, json={**payload, "email": "ADA@example.com"})
    assert response.status_code == 409


def test_get_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.get(f"{BASE}/{contact_id}")
    assert response.status_code == 200
    assert response.json()["id"] == contact_id


def test_get_missing_contact_returns_404(client):
    assert client.get(f"{BASE}/9999").status_code == 404


def test_list_pagination_and_total(client, payload):
    for index in range(5):
        client.post(BASE, json={**payload, "email": f"user{index}@example.com"})

    response = client.get(BASE, params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2 and body["offset"] == 2


def test_list_search(client, payload):
    client.post(BASE, json=payload)
    client.post(
        BASE,
        json={**payload, "first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com", "company": "US Navy"},
    )

    hits = client.get(BASE, params={"search": "hopper"}).json()
    assert hits["total"] == 1
    assert hits["items"][0]["last_name"] == "Hopper"

    by_company = client.get(BASE, params={"search": "navy"}).json()
    assert by_company["total"] == 1

    misses = client.get(BASE, params={"search": "nobody"}).json()
    assert misses["total"] == 0


def test_list_sorting(client, payload):
    client.post(BASE, json={**payload, "last_name": "Zhang", "email": "z@example.com"})
    client.post(BASE, json={**payload, "last_name": "Adams", "email": "a@example.com"})

    names = [
        item["last_name"]
        for item in client.get(BASE, params={"sort_by": "last_name", "order": "asc"}).json()["items"]
    ]
    assert names == ["Adams", "Zhang"]


def test_list_rejects_bad_sort_field(client):
    assert client.get(BASE, params={"sort_by": "; DROP TABLE contacts"}).status_code == 422


def test_patch_updates_only_sent_fields(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1-000-000-0000"
    assert body["first_name"] == "Ada"
    assert body["company"] == "Analytical Engines"


def test_patch_duplicate_email_conflicts(client, payload):
    first = client.post(BASE, json=payload).json()["id"]
    client.post(BASE, json={**payload, "email": "grace@example.com"})
    response = client.patch(f"{BASE}/{first}", json={"email": "grace@example.com"})
    assert response.status_code == 409


def test_patch_same_email_is_allowed(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"email": payload["email"]})
    assert response.status_code == 200


def test_put_replaces_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Grace Hopper"
    assert body["company"] is None  # omitted fields are cleared by PUT


def test_put_missing_contact_returns_404(client):
    response = client.put(
        f"{BASE}/9999",
        json={"first_name": "A", "last_name": "B", "email": "ab@example.com"},
    )
    assert response.status_code == 404


def test_delete_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert client.get(f"{BASE}/{contact_id}").status_code == 404
    assert client.delete(f"{BASE}/{contact_id}").status_code == 404


def test_root_lists_entrypoints(client):
    body = client.get("/").json()
    assert body["contacts"] == BASE


def _png(size: int = 8) -> bytes:
    """Smallest real PNG we can build without an imaging dependency."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    rows = b"".join(b"\x00" + bytes((10, 120, 200)) * size for _ in range(size))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _data_url(mime: str, raw: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def test_create_contact_with_photo(client, payload):
    photo = _data_url("image/png", _png())
    response = client.post(BASE, json={**payload, "photo": photo})
    assert response.status_code == 201
    assert response.json()["photo"] == photo


def test_photo_defaults_to_null(client, payload):
    assert client.post(BASE, json=payload).json()["photo"] is None


def test_put_carrying_photo_keeps_it(client, payload):
    photo = _data_url("image/png", _png())
    contact_id = client.post(BASE, json={**payload, "photo": photo}).json()["id"]
    response = client.put(f"{BASE}/{contact_id}", json={**payload, "photo": photo})
    assert response.json()["photo"] == photo


def test_put_omitting_photo_clears_it(client, payload):
    photo = _data_url("image/png", _png())
    contact_id = client.post(BASE, json={**payload, "photo": photo}).json()["id"]
    assert client.put(f"{BASE}/{contact_id}", json=payload).json()["photo"] is None


@pytest.mark.parametrize(
    "photo",
    [
        "https://example.com/ada.png",
        "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",  # SVG can carry script
        "data:image/png;base64,!!!not-base64!!!",
        "data:image/png;base64,",
    ],
)
def test_photo_rejects_bad_data_urls(client, payload, photo):
    assert client.post(BASE, json={**payload, "photo": photo}).status_code == 422


def test_photo_rejects_content_that_is_not_the_declared_type(client, payload):
    disguised = _data_url("image/png", b"PK\x03\x04 this is a zip, not a png")
    assert client.post(BASE, json={**payload, "photo": disguised}).status_code == 422
    mislabelled = _data_url("image/jpeg", _png())
    assert client.post(BASE, json={**payload, "photo": mislabelled}).status_code == 422


def test_photo_rejects_oversized_image(client, payload):
    oversized = _data_url("image/png", _png() + b"\x00" * MAX_PHOTO_BYTES)
    assert client.post(BASE, json={**payload, "photo": oversized}).status_code == 422


HOME_ADDRESS = {
    "type": "Home",
    "street": "12 Ockham Rd",
    "city": "San Francisco",
    "state": "CA",
    "postal_code": "94110",
    "country": "USA",
}
WORK_ADDRESS = {
    "type": "Work",
    "street": "1 Market St, Suite 400",
    "city": "San Francisco",
    "state": "CA",
    "postal_code": "94105",
    "country": "USA",
}


def _stored_address_count() -> int:
    """Count rows in the addresses table itself, not the ones a contact reports."""
    with SessionLocal() as db:
        return db.execute(select(func.count()).select_from(Address)).scalar_one()


def test_create_contact_with_two_addresses(client, payload):
    response = client.post(BASE, json={**payload, "addresses": [HOME_ADDRESS, WORK_ADDRESS]})
    assert response.status_code == 201
    addresses = response.json()["addresses"]
    assert len(addresses) == 2
    assert [address["type"] for address in addresses] == ["Home", "Work"]
    assert all(address["id"] > 0 for address in addresses)


def test_addresses_read_back_grouped_by_type(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME_ADDRESS, WORK_ADDRESS]}).json()["id"]

    body = client.get(f"{BASE}/{contact_id}").json()
    by_type = {address["type"]: address for address in body["addresses"]}
    assert set(by_type) == {"Home", "Work"}
    assert by_type["Home"]["street"] == HOME_ADDRESS["street"]
    assert by_type["Work"]["postal_code"] == "94105"


def test_contact_without_addresses_is_allowed(client, payload):
    body = client.post(BASE, json={**payload, "addresses": []}).json()
    assert body["addresses"] == []
    omitted = {key: value for key, value in payload.items() if key != "addresses"}
    assert client.post(BASE, json={**omitted, "email": "grace@example.com"}).json()["addresses"] == []


@pytest.mark.parametrize(
    "address",
    [
        {**HOME_ADDRESS, "type": "Holiday"},  # outside the allowed set
        {**HOME_ADDRESS, "type": ""},
        {key: value for key, value in HOME_ADDRESS.items() if key != "type"},  # missing
        {**HOME_ADDRESS, "street": ""},
        {**HOME_ADDRESS, "street": "   "},  # blank once trimmed
        {**HOME_ADDRESS, "street": "x" * 301},  # over max_length
        {**HOME_ADDRESS, "postal_code": "x" * 21},
    ],
)
def test_address_rejects_invalid_input(client, payload, address):
    assert client.post(BASE, json={**payload, "addresses": [address]}).status_code == 422


def test_put_replaces_the_whole_address_set(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME_ADDRESS, WORK_ADDRESS]}).json()["id"]

    replaced = client.put(f"{BASE}/{contact_id}", json={**payload, "addresses": [WORK_ADDRESS]})
    assert replaced.status_code == 200
    assert [address["type"] for address in replaced.json()["addresses"]] == ["Work"]
    assert _stored_address_count() == 1  # the two originals are gone, not orphaned

    cleared = client.put(f"{BASE}/{contact_id}", json={**payload, "addresses": []})
    assert cleared.json()["addresses"] == []
    assert _stored_address_count() == 0


def test_patch_leaves_addresses_alone_unless_sent(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME_ADDRESS]}).json()["id"]

    untouched = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert len(untouched.json()["addresses"]) == 1

    rewritten = client.patch(f"{BASE}/{contact_id}", json={"addresses": [WORK_ADDRESS]})
    assert [address["type"] for address in rewritten.json()["addresses"]] == ["Work"]
    assert _stored_address_count() == 1


def test_deleting_a_contact_deletes_its_addresses(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME_ADDRESS, WORK_ADDRESS]}).json()["id"]
    kept_id = client.post(
        BASE, json={**payload, "email": "grace@example.com", "addresses": [WORK_ADDRESS]}
    ).json()["id"]
    assert _stored_address_count() == 3

    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert _stored_address_count() == 1  # only the other contact's address survives
    assert len(client.get(f"{BASE}/{kept_id}").json()["addresses"]) == 1


def test_rejects_more_addresses_than_the_cap(client, payload):
    too_many = [
        {"type": "Other", "street": f"{n} Long Road"} for n in range(MAX_ADDRESSES + 1)
    ]
    response = client.post(BASE, json={**payload, "addresses": too_many})
    assert response.status_code == 422
