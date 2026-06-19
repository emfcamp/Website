"""Stuff to generate Apple pkpass tickets."""

import hashlib
import io
import json
import subprocess
import zipfile
from collections.abc import Iterable
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytz
from flask import current_app as app
from PIL import Image

from apps.common.receipt import get_purchase_metadata
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


def generate_pass_data(user: User) -> dict[str, Any]:
    meta = get_purchase_metadata(user)
    # Use localize() rather than replace(tzinfo=...): pytz zones carry historical
    # offsets, so replace() yields a bogus LMT offset (e.g. -00:01) instead of BST.
    expire_dt = pytz.timezone("Europe/London").localize(
        datetime.strptime(app.config["EVENT_END"], "%Y-%m-%d %H:%M:%S")
    )
    barcode = {
        "format": "PKBarcodeFormatQR",
        "message": app.config["CHECKIN_BASE"] + user.checkin_code,
        "messageEncoding": "iso-8859-1",
    }
    return {
        "passTypeIdentifier": app.config["PKPASS_IDENTIFIER"],
        "teamIdentifier": app.config["PKPASS_TEAM_ID"],
        "formatVersion": 1,
        # Use the checkin code as a unique serial.
        "serialNumber": user.checkin_code,
        "organizationName": "Electromagnetic Field",
        "description": "Electromagnetic Field Entry Pass",
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
        "eventTicket": {
            "primaryFields": [
                {"key": "admissions", "value": len(meta.admissions), "label": "Admission"},
                {"key": "parking", "value": len(meta.parking_tickets), "label": "Parking"},
                {"key": "caravan", "value": len(meta.campervan_tickets), "label": "Campervan"},
            ],
            "secondaryFields": [],
            "backFields": [
                {
                    "key": "gen",
                    "value": f"{datetime.now().isoformat()}",
                    "label": "Generated at ",
                }
            ],
        },
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
_ICON_SIZE = 29
# eventTicket strip (the band shown behind the primary fields). Unlike
# background.png, the strip is drawn consistently by Apple Wallet, Android pkpass
# readers and the various online viewers.
_STRIP_SIZE = (375, 123)
# Card colour, shown where the strip doesn't reach and behind the white fields.
_BACKGROUND_COLOR = "rgb(13, 14, 14)"
_LANCZOS = Image.Resampling.LANCZOS


def _render_strip(width: int, height: int) -> bytes:
    """Crop a wide band of the hero graphic for the pass strip (sits behind the fields)."""
    with Image.open(_HERO_IMAGE) as src:
        img = src.convert("RGB")
        # Full width, horizontal slice through the comet arc and dish.
        crop_h = min(img.height, round(img.width * height / width))
        top = round((img.height - crop_h) * 0.3)
        box = (0, top, img.width, top + crop_h)
        out = io.BytesIO()
        img.resize((width, height), _LANCZOS, box=box).save(out, "PNG")
    return out.getvalue()


def _render_logo(height: int) -> bytes:
    """Resize the white EMF symbol for the pass logo (width scales with aspect)."""
    with Image.open(_LOGO_IMAGE) as src:
        img = src.convert("RGBA")
        width = round(img.width * height / img.height)
        out = io.BytesIO()
        img.resize((width, height), _LANCZOS).save(out, "PNG")
    return out.getvalue()


def _render_icon(size: int) -> bytes:
    """White EMF glyph centred on a brand-orange tile."""
    inner = round(size * 0.66)
    with Image.open(_GLYPH_IMAGE) as img:
        glyph_alpha = img.convert("RGBA").resize((inner, inner), _LANCZOS).split()[3]
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
        assets[f"strip{suffix}.png"] = _render_strip(
            _STRIP_SIZE[0] * scale, _STRIP_SIZE[1] * scale
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
    """Call openssl smime to sign some data."""
    cmd = [
        "openssl",
        "smime",
        "-binary",
        "-sign",
        "-signer",
        str(signer_cert_file),
        "-inkey",
        str(key_file),
        "-certfile",
        str(cert_chain_file),
        "-outform",
        "der",
    ]
    try:
        p = subprocess.run(args=cmd, input=data, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        app.logger.error("Error signing pkpass: %s", e.stderr)
        raise
    return p.stdout


def generate_pkpass(user: User) -> io.BytesIO:
    """Generates a signed Apple Wallet pass for a user."""
    zip_buffer = io.BytesIO()
    files = {
        "pass.json": json.dumps(generate_pass_data(user)).encode(),
    }
    files |= get_pass_assets()
    manifest = json.dumps(generate_manifest(files)).encode()
    signature = smime_sign(
        manifest,
        app.config["PKPASS_SIGNER_CERT_FILE"],
        app.config["PKPASS_KEY_FILE"],
        app.config["PKPASS_CHAIN_FILE"],
    )
    files["manifest.json"] = manifest
    files["signature"] = signature
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for name, contents in files.items():
            zf.writestr(name, contents)
    zip_buffer.seek(0)
    return zip_buffer
