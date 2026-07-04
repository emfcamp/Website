"""Stuff to generate Apple pkpass tickets."""

import hashlib
import io
import json
import zipfile
from collections.abc import Iterable
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytz
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import Encoding, load_pem_private_key
from cryptography.hazmat.primitives.serialization.pkcs7 import PKCS7Options, PKCS7SignatureBuilder
from cryptography.x509 import load_pem_x509_certificate, load_pem_x509_certificates
from flask import current_app as app
from PIL import Image
from PIL.Image import Palette, Resampling

from apps.common.receipt import get_purchase_metadata
from apps.config import config
from models.user import User

# https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/PassKit_PG/Creating.html
MAX_PASS_LOCATIONS = 10


class PkPassException(Exception):
    """Base pkpass generator exception."""


class TooManyPassLocations(PkPassException):
    """Too many pass locations specified in config."""

    def __init__(self, count: int) -> None:
        self.count = count

    def __str__(self) -> str:
        return f"{self.__doc__} Got {self.count}, max is {MAX_PASS_LOCATIONS}"


class InvalidPassConfig(PkPassException):
    """Pass config does not match expected schema"""

    missing: set[str]
    extra: set[str]

    def __init__(self, *, missing: set[str], extra: set[str]) -> None:
        self.missing = missing
        self.extra = extra

    def __str__(self) -> str:
        out = "Invalid pass config: "
        if self.missing:
            out += f", missing: {self.missing}"
        if self.extra:
            out += f", extra: {self.extra}"
        return out


def generate_manifest(files: dict[str, bytes]) -> dict[str, str]:
    """Given a dict of filename -> contents, generate the pkpass manifest."""
    return {name: hashlib.sha1(contents).hexdigest() for name, contents in files.items()}


def _validate_keys(
    things: Iterable[dict[str, Any]],
    expected_keys: set[str],
    optional_keys: set[str] | None = None,
) -> None:
    optional_keys = optional_keys or set()
    for thing in things:
        got_keys = set(thing.keys())
        missing = expected_keys - got_keys
        extra = got_keys - (expected_keys | optional_keys)
        if missing or extra:
            raise InvalidPassConfig(missing=missing, extra=extra)


def _get_and_validate_locations():
    """Get and validate pkpass locations from config."""
    locs = app.config.get("PKPASS_LOCATIONS", [])
    if len(locs) > MAX_PASS_LOCATIONS:
        raise TooManyPassLocations(count=len(locs))
    _validate_keys(locs, {"latitude", "longitude"}, {"altitude", "relevantText"})
    return locs


def _get_beacons():
    """Get and validate pkpass beacons from config."""
    beacons = app.config.get("PKPASS_BEACONS", [])
    _validate_keys(beacons, {"proximityUUID"}, {"relevantText", "major", "minor"})
    return beacons


_EVENT_NAME = "Electromagnetic Field 2026"
_VENUE_SHORT = "Eastnor Deer Park"
_VENUE_FULL = "Eastnor Castle Deer Park, Eastnor, Herefordshire"


def _event_datetimes() -> tuple[datetime, datetime]:
    """Event start/end as timezone-aware datetimes.

    Use localize() rather than replace(tzinfo=...): pytz zones carry historical
    offsets, so replace() yields a bogus LMT offset (e.g. -00:01) instead of BST.
    """
    tz = pytz.timezone("Europe/London")
    start = tz.localize(config.event_start)
    end = tz.localize(config.event_end)
    return start, end


def _format_date_range(start: datetime, end: datetime) -> str:
    """e.g. '16-19 Jul 2026', or '30 Jul - 2 Aug 2026' across a month boundary."""
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}-{end.day} {start:%b %Y}"
    return f"{start.day} {start:%b} - {end.day} {end:%b %Y}"


def _build_event_fields(user: User) -> dict[str, list[dict[str, Any]]]:
    """Assemble the eventTicket field groups, including only the fields the user
    actually has tickets for so we never show 'Parking 0'."""
    meta = get_purchase_metadata(user)
    start, end = _event_datetimes()
    n_admission = len(meta.admissions)
    n_parking = len(meta.parking_tickets)
    n_campervan = len(meta.campervan_tickets)

    # No header field: the logo text ("Electromagnetic Field") needs the full
    # width of the top row, and a header field on the right truncates it to
    # "Electromagneti…". The dates still show in the auxiliary row and the back.
    header: list[dict[str, Any]] = []

    # Field values are strings, not ints: Apple renders either, but Google
    # Wallet's pkpass import (localizedBody.value) requires strings and rejects
    # bare numbers, so str() everything for cross-wallet compatibility.
    # Large, overlaid on the hero — the headline of an entry pass.
    primary = [{"key": "admission", "label": "Admission", "value": str(n_admission)}]

    secondary = [
        {"key": "location", "label": "Location", "value": _VENUE_SHORT},
    ]

    auxiliary = [
        {"key": "gates", "label": "Gates open", "value": f"{start:%a} {start.day} {start:%b}, {start:%H:%M}"},
    ]
    if n_parking:
        auxiliary.append({"key": "parking", "label": "Parking", "value": str(n_parking)})
    if n_campervan:
        auxiliary.append({"key": "campervan", "label": "Campervan", "value": str(n_campervan)})

    back = [
        {"key": "b_checkin", "label": "Check-in code", "value": user.checkin_code},
        {"key": "b_event", "label": "Event", "value": _EVENT_NAME},
        {"key": "b_venue", "label": "Location", "value": _VENUE_FULL},
        {"key": "b_dates", "label": "Dates", "value": _format_date_range(start, end)},
        {"key": "b_admission", "label": "Admission tickets", "value": str(n_admission)},
    ]
    if n_parking:
        back.append({"key": "b_parking", "label": "Parking tickets", "value": str(n_parking)})
    if n_campervan:
        back.append({"key": "b_campervan", "label": "Campervan tickets", "value": str(n_campervan)})
    back.append({"key": "gen", "label": "Generated at", "value": datetime.now().isoformat()})

    return {
        "headerFields": header,
        "primaryFields": primary,
        "secondaryFields": secondary,
        "auxiliaryFields": auxiliary,
        "backFields": back,
    }


def generate_pass_data(user: User) -> dict[str, Any]:
    _, expire_dt = _event_datetimes()
    barcode = {
        "format": "PKBarcodeFormatQR",
        "message": app.config["CHECKIN_BASE"] + user.checkin_code,
        "messageEncoding": "iso-8859-1",
        # Shown as readable text under the QR.
        "altText": user.checkin_code,
    }
    return {
        "passTypeIdentifier": app.config["PKPASS_IDENTIFIER"],
        "teamIdentifier": app.config["PKPASS_TEAM_ID"],
        "formatVersion": 1,
        # Use the checkin code as a unique serial.
        "serialNumber": user.checkin_code,
        "organizationName": "Electromagnetic Field",
        "description": "EMF Entry Pass",
        # Shown as the ticket title at the top, next to the logo mark. Kept to
        # the bare event name so it fills the top row without truncating; the
        # dates live in the auxiliary row and on the back.
        "logoText": "Electromagnetic Field",
        "locations": _get_and_validate_locations(),
        "beacons": _get_beacons(),
        "maxDistance": app.config.get("PKPASS_MAX_DISTANCE", 50),
        "barcodes": [barcode],
        # Deprecated singular form, kept for older Wallet readers (notably some
        # Android pkpass apps) that don't understand the "barcodes" array.
        "barcode": barcode,
        "foregroundColor": "rgb(255, 255, 255)",
        "labelColor": "rgb(255, 255, 255)",
        "backgroundColor": _BACKGROUND_COLOR,
        # Allow users to share passes, since they could just send the PDF anyway...
        "sharingProhibited": False,
        # ISO 8601 with a colon in the offset, e.g. 2026-07-19T23:00:00+01:00.
        "expirationDate": expire_dt.isoformat(),
        "eventTicket": _build_event_fields(user),
    }


# Pass artwork is derived at runtime from the site's existing brand assets, so we
# don't carry a set of event-specific images just for this feature. Set
# PKPASS_ASSETS_DIR to override with a directory of ready-made pkpass images.
_BRAND_DIR = Path("images/brand/2026")
_HERO_IMAGE = _BRAND_DIR / "hero-black.jpg"
# Symbol-only mark (ringed planet + stars, no wordmark) for the pass logo.
_LOGO_IMAGE = _BRAND_DIR / "emf2026-logo-white.png"
_GLYPH_IMAGE = Path("images/pwa/icon-512.png")
# $brand-2026-orange from css/_variables.scss
_ICON_BG = (247, 127, 2)

# Target sizes in points; Apple wants @2x and @3x raster variants of each.
_SCALES = (("", 1), ("@2x", 2), ("@3x", 3))
_LOGO_HEIGHT = 50
# Wallet's icon slot is 38pt (so @3x is 114x114); anything smaller is rejected
# by Pass Designer's validator as the wrong dimensions.
_ICON_SIZE = 38
# eventTicket background.png fills the whole card (Wallet blurs and darkens it
# behind the fields). Wallet requires a 345x505pt background (@3x 1035x1515); the
# hero is a portrait crop centred on the comet arc to fill that taller frame.
_BACKGROUND_SIZE = (345, 505)
# Currently (iOS 26) backgrounds are rendered with heavy blurring, so we resize
# right down, and then scale back up to the target.
_BACKGROUND_SIZE_SMALL = (69, 101)
# Card colour, shown behind the fields where the artwork is unavailable.
_BACKGROUND_COLOR = "rgb(13, 14, 14)"


def _render_background(width: int, height: int) -> bytes:
    """Portrait crop of the hero for the full-card background.

    The comet arc, dish and its reflection sit in the left-centre of the wide
    source, so we centre a portrait crop there rather than on the image centre.
    """
    with Image.open(_HERO_IMAGE) as src:
        img = src.convert("RGB")
        target = width / height
        crop_h = img.height * 0.82  # keep a little sky above the arc and foreground below
        crop_w = crop_h * target
        cx, cy = img.width * 0.27, img.height * 0.52
        left = max(0.0, min(cx - crop_w / 2, img.width - crop_w))
        top = max(0.0, min(cy - crop_h / 2, img.height - crop_h))
        box = (left, top, left + crop_w, top + crop_h)
        out = io.BytesIO()
        img = img.resize(_BACKGROUND_SIZE_SMALL, Resampling.LANCZOS, box=box)
        img = img.resize((width, height), Resampling.NEAREST)
        img = img.convert("P", palette=Palette.ADAPTIVE, colors=256)
        img.save(out, "PNG", optimize=True, compress_level=9)
        # open("background.png", "wb").write(out.getvalue())
    return out.getvalue()


def _render_logo(height: int) -> bytes:
    """Resize the white EMF symbol for the pass logo (width scales with aspect)."""
    with Image.open(_LOGO_IMAGE) as src:
        img = src.convert("RGBA")
        width = round(img.width * height / img.height)
        out = io.BytesIO()
        img.resize((width, height), Resampling.LANCZOS).save(out, "PNG")
    return out.getvalue()


def _render_icon(size: int) -> bytes:
    """White EMF glyph centred on a brand-orange tile."""
    inner = round(size * 0.66)
    with Image.open(_GLYPH_IMAGE) as img:
        glyph_alpha = img.convert("RGBA").resize((inner, inner), Resampling.LANCZOS).split()[3]
    mask = Image.new("L", (size, size), 0)
    mask.paste(glyph_alpha, ((size - inner) // 2, (size - inner) // 2))
    tile = Image.new("RGB", (size, size), _ICON_BG)
    tile.paste(Image.new("RGB", (size, size), (255, 255, 255)), (0, 0), mask)
    out = io.BytesIO()
    tile.save(out, "PNG")
    return out.getvalue()


@lru_cache(maxsize=1)
def _generate_brand_assets() -> dict[str, bytes]:
    """Build the pkpass image set from the site brand assets, keyed by filename."""
    assets: dict[str, bytes] = {}
    for suffix, scale in _SCALES:
        assets[f"icon{suffix}.png"] = _render_icon(_ICON_SIZE * scale)
        assets[f"logo{suffix}.png"] = _render_logo(_LOGO_HEIGHT * scale)
        assets[f"background{suffix}.png"] = _render_background(
            _BACKGROUND_SIZE[0] * scale, _BACKGROUND_SIZE[1] * scale
        )
    return assets


def get_pass_assets() -> dict[str, bytes]:
    """Pass images keyed by filename, either generated from brand assets or loaded
    from PKPASS_ASSETS_DIR if that override is configured."""
    override = app.config.get("PKPASS_ASSETS_DIR")
    if override:
        return {p.name: p.read_bytes() for p in Path(override).iterdir() if p.is_file()}
    return dict(_generate_brand_assets())


def smime_sign(data: bytes, signer_cert_file: Path, key_file: Path, cert_chain_file: Path) -> bytes:
    cert = load_pem_x509_certificate(signer_cert_file.read_bytes())
    key = load_pem_private_key(key_file.read_bytes(), password=None)
    # TODO use PKCS7PrivateKeyTypes when mypy supports it
    if not isinstance(key, RSAPrivateKey | EllipticCurvePrivateKey):
        raise ValueError(f"Key {key_file} is not a suitable private key")
    cert_chain = load_pem_x509_certificates(cert_chain_file.read_bytes())

    builder = PKCS7SignatureBuilder()
    builder = builder.set_data(data)
    builder = builder.add_signer(cert, key, SHA256())
    for cert in cert_chain:
        builder = builder.add_certificate(cert)

    return builder.sign(
        encoding=Encoding.DER,
        options=[PKCS7Options.Binary, PKCS7Options.DetachedSignature],
    )


def _pass_files(user: User) -> dict[str, bytes]:
    """The pass.json plus image assets that make up a .pkpass archive."""
    files = {"pass.json": json.dumps(generate_pass_data(user)).encode()}
    files |= get_pass_assets()
    return files


def _zip_files(files: dict[str, bytes]) -> io.BytesIO:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for name, contents in files.items():
            zf.writestr(name, contents)
    zip_buffer.seek(0)
    return zip_buffer


def generate_unsigned_pkpass(user: User) -> io.BytesIO:
    """Build a .pkpass without a signature, for previewing artwork and layout
    (e.g. in Apple's Wallet Pass Designer). Not valid for installation."""
    files = _pass_files(user)
    files["manifest.json"] = json.dumps(generate_manifest(files)).encode()
    return _zip_files(files)


def generate_pkpass(user: User) -> io.BytesIO:
    """Generates a signed Apple Wallet pass for a user."""
    files = _pass_files(user)
    manifest = json.dumps(generate_manifest(files)).encode()
    signature = smime_sign(
        manifest,
        Path(app.config["PKPASS_SIGNER_CERT_FILE"]),
        Path(app.config["PKPASS_KEY_FILE"]),
        Path(app.config["PKPASS_CHAIN_FILE"]),
    )
    files["manifest.json"] = manifest
    files["signature"] = signature
    return _zip_files(files)
