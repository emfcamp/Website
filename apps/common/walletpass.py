"""Stuff to generate Apple pkpass/Google Wallet tickets."""

import hashlib
import io
import json
import zipfile
from collections.abc import Iterable
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

import google.auth.crypt
import google.auth.jwt
import google.oauth2.service_account
import googleapiclient.discovery
import pytz
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import Encoding, load_pem_private_key
from cryptography.hazmat.primitives.serialization.pkcs7 import PKCS7Options, PKCS7SignatureBuilder
from cryptography.x509 import load_pem_x509_certificate, load_pem_x509_certificates
from PIL import Image
from PIL.Image import Palette, Resampling

from apps.common.receipt import get_purchase_metadata
from apps.config import config
from main import static_digest
from models.user import User

if TYPE_CHECKING:
    pass

# https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/PassKit_PG/Creating.html
MAX_PASS_LOCATIONS = 10


class PassException(Exception):
    """Base pkpass generator exception."""


class TooManyPassLocations(PassException):
    """Too many pass locations specified in config."""

    def __init__(self, count: int) -> None:
        self.count = count

    def __str__(self) -> str:
        return f"{self.__doc__} Got {self.count}, max is {MAX_PASS_LOCATIONS}"


class InvalidPassConfig(PassException):
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
    locs = config.get("PKPASS_LOCATIONS", [])
    if len(locs) > MAX_PASS_LOCATIONS:
        raise TooManyPassLocations(count=len(locs))
    _validate_keys(locs, {"latitude", "longitude"}, {"altitude", "relevantText"})
    return locs


def _get_beacons():
    """Get and validate pkpass beacons from config."""
    beacons = config.get("PKPASS_BEACONS", [])
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


def _build_pkpass_event_fields(user: User) -> dict[str, list[dict[str, Any]]]:
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


def _generate_pkpass_data(user: User) -> dict[str, Any]:
    _, expire_dt = _event_datetimes()
    barcode = {
        "format": "PKBarcodeFormatQR",
        "message": config.get("CHECKIN_BASE") + user.checkin_code,
        "messageEncoding": "iso-8859-1",
        # Shown as readable text under the QR.
        "altText": user.checkin_code,
    }
    return {
        "passTypeIdentifier": config.get("PKPASS_IDENTIFIER"),
        "teamIdentifier": config.get("PKPASS_TEAM_ID"),
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
        "maxDistance": config.get("PKPASS_MAX_DISTANCE", 50),
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
        "eventTicket": _build_pkpass_event_fields(user),
    }


# PKPass artwork is derived at runtime from the site's existing brand assets, so we
# don't carry a set of event-specific images just for this feature. Set
# PKPASS_ASSETS_DIR to override with a directory of ready-made pkpass images.
# Google Wallet imagery needs to be pre-baked, since we have to be able to cook up
# a URL for it at any time, and generating it on the fly seems unwise.
_BRAND_DIR = Path("images/brand/2026")
_HERO_IMAGE = _BRAND_DIR / "hero-black.jpg"
_GWALLET_HERO_IMAGE = _BRAND_DIR / "gwallet-hero.jpg"  # should be 1032x336px
# Symbol-only mark (ringed planet + stars, no wordmark) for the pass logo.
_LOGO_IMAGE = _BRAND_DIR / "emf2026-logo-white.png"
_GWALLET_LOGO_IMAGE = _BRAND_DIR / "gwallet-logo.png"  # should be 660x660px
# Full logo (including wordmark)
_GWALLET_WIDE_LOGO_IMAGE = _BRAND_DIR / "gwallet-logo-wide.png"  # should be 1280x400px
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
    override = config.get("PKPASS_ASSETS_DIR", None)
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
    files = {"pass.json": json.dumps(_generate_pkpass_data(user)).encode()}
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
        Path(config.get("PKPASS_SIGNER_CERT_FILE")),
        Path(config.get("PKPASS_KEY_FILE")),
        Path(config.get("PKPASS_CHAIN_FILE")),
    )
    files["manifest.json"] = manifest
    files["signature"] = signature
    return _zip_files(files)


def _gwallet_class_id() -> str:
    return f"{config.get('GOOGLE_WALLET_ISSUER_ID')}.{config.get('GOOGLE_WALLET_CLASS_ID')}"


def _gwallet_localised_str(s: str) -> googleapiclient._apis.walletobjects.v1.LocalizedString:
    return {
        "defaultValue": {
            "language": "en-GB",
            "value": s,
        },
    }


def _gwallet_image_url(static_filename: str) -> googleapiclient._apis.walletobjects.v1.Image:
    url = static_digest.static_url_for("static", filename=static_filename, _external=True)
    return {
        "sourceUri": {
            "uri": url,
        },
    }


def generate_gwallet_class() -> googleapiclient._apis.walletobjects.v1.EventTicketClass:
    """Generates the base class from which tickets will be derived."""
    start, end = _event_datetimes()
    pkpass_locations = _get_and_validate_locations()
    locations: list[googleapiclient._apis.walletobjects.v1.MerchantLocation] = [
        {"latitude": loc["latitude"], "longitude": loc["longitude"]} for loc in pkpass_locations
    ]

    return {
        "id": _gwallet_class_id(),
        "eventName": _gwallet_localised_str(_EVENT_NAME),
        "eventId": _gwallet_class_id(),
        "issuerName": "Electromagnetic Field",
        "logo": _gwallet_image_url(str(_GWALLET_LOGO_IMAGE)),
        "wideLogo": _gwallet_image_url(str(_GWALLET_WIDE_LOGO_IMAGE)),
        "venue": {
            "name": _gwallet_localised_str(_VENUE_SHORT),
            "address": _gwallet_localised_str(_VENUE_FULL),
        },
        "dateTime": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "reviewStatus": "UNDER_REVIEW",  # automatically flipped to active
        "countryCode": "GB",
        "heroImage": _gwallet_image_url(str(_GWALLET_HERO_IMAGE)),
        "hexBackgroundColor": "#050706",
        "multipleDevicesAndHoldersAllowedStatus": "MULTIPLE_HOLDERS",
        "linksModuleData": {
            "uris": [
                {
                    "uri": "https://www.emfcamp.org",
                    "description": "Main EMF Website",
                },
                {
                    "uri": "https://map.emfcamp.org",
                    "description": "Site Map",
                },
                {
                    "uri": "https://www.emfcamp.org/about/travel",
                    "description": "Travelling to EMF",
                },
            ],
        },
        "textModulesData": [
            {
                "id": "dates",
                "header": "Dates",
                "body": _format_date_range(start, end),
            },
        ],
        "merchantLocations": locations,
        "classTemplateInfo": {
            "cardTemplateOverride": {
                # Overrides what we display on the main 'card' view, when you click on the pass
                "cardRowTemplateInfos": [
                    # First row: Start date - End date
                    {
                        "oneItem": {
                            "item": {
                                "firstValue": {
                                    "fields": [
                                        {
                                            "fieldPath": "class.textModulesData['dates']",
                                        }
                                    ],
                                },
                            },
                        },
                    },
                    # Second row: Admission / Parking / Live-in vehicle
                    {
                        "threeItems": {
                            "startItem": {
                                "firstValue": {
                                    "fields": [
                                        {
                                            "fieldPath": "object.textModulesData['n_admission']",
                                        }
                                    ],
                                },
                            },
                            "middleItem": {
                                "firstValue": {
                                    "fields": [
                                        {
                                            "fieldPath": "object.textModulesData['n_parking']",
                                        }
                                    ],
                                },
                            },
                            "endItem": {
                                "firstValue": {
                                    "fields": [
                                        {
                                            "fieldPath": "object.textModulesData['n_campervan']",
                                        }
                                    ],
                                },
                            },
                        },
                    },
                    # Third row (if necessary): merchandise items
                    {
                        "oneItem": {
                            "item": {
                                "firstValue": {
                                    "fields": [
                                        {
                                            "fieldPath": "object.textModulesData['n_merch']",
                                        }
                                    ],
                                },
                            },
                        },
                    },
                ],
            },
            "listTemplateOverride": {
                # Overrides what we show on the list-of-all-passes view
                # First row: the event name
                "firstRowOption": {
                    "fieldOption": {
                        "fields": [
                            {
                                "fieldPath": "class.eventName",
                            }
                        ],
                    },
                },
                # Second row: the dates
                "secondRowOption": {
                    "fields": [
                        {
                            "fieldPath": "class.textModulesData['dates']",
                        }
                    ],
                },
            },
            "detailsTemplateOverride": {
                # Overrides the 'back of pass' list
                "detailsItemInfos": [
                    # Dates
                    {"item": {"firstValue": {"fields": [{"fieldPath": "class.textModulesData['dates']"}]}}},
                    # Address
                    {"item": {"firstValue": {"fields": [{"fieldPath": "class.venue"}]}}},
                    # Checkin code
                    {"item": {"firstValue": {"fields": [{"fieldPath": "object.ticketNumber"}]}}},
                    # Admission tickets
                    {
                        "item": {
                            "firstValue": {"fields": [{"fieldPath": "object.textModulesData['n_admission']"}]}
                        }
                    },
                    {
                        "item": {
                            "firstValue": {"fields": [{"fieldPath": "object.textModulesData['n_parking']"}]}
                        }
                    },
                    {
                        "item": {
                            "firstValue": {"fields": [{"fieldPath": "object.textModulesData['n_campervan']"}]}
                        }
                    },
                    {
                        "item": {
                            "firstValue": {"fields": [{"fieldPath": "object.textModulesData['n_merch']"}]}
                        }
                    },
                    # URLs
                    {"item": {"firstValue": {"fields": [{"fieldPath": "class.linksModuleData"}]}}},
                ],
            },
        },
    }


def generate_gwallet_pass(user: User) -> googleapiclient._apis.walletobjects.v1.EventTicketObject:
    start, end = _event_datetimes()
    meta = get_purchase_metadata(user)
    n_admission = len(meta.admissions)
    n_parking = len(meta.parking_tickets)
    n_campervan = len(meta.campervan_tickets)
    n_merch = len(meta.merch)
    pass_valid_start = start
    if user.buildup_volunteer is not None:
        pass_valid_start = pytz.timezone("Europe/London").localize(user.buildup_volunteer.arrival_date)
    text_modules: list[googleapiclient._apis.walletobjects.v1.TextModuleData] = [
        {
            "id": "n_admission",
            "header": "Admission",
            "body": str(n_admission),
        }
    ]
    if n_parking:
        text_modules.append(
            {
                "id": "n_parking",
                "header": "Parking",
                "body": str(n_parking),
            }
        )
    if n_campervan:
        text_modules.append(
            {
                "id": "n_campervan",
                "header": "Live-in vehicles",
                "body": str(n_campervan),
            }
        )
    if n_merch:
        text_modules.append(
            {
                "id": "n_merch",
                "header": "Merchandise items",
                "body": str(n_merch),
            }
        )

    return {
        "id": f"{config.get('GOOGLE_WALLET_ISSUER_ID')}.{user.checkin_code}",
        "classId": _gwallet_class_id(),
        "state": "ACTIVE",
        "barcode": {
            "type": "QR_CODE",
            "value": config.get("CHECKIN_BASE") + user.checkin_code,
            "alternateText": user.checkin_code,
        },
        "ticketNumber": user.checkin_code,
        "textModulesData": text_modules,
        "validTimeInterval": {
            "start": {"date": pass_valid_start.isoformat()},
            "end": {"date": end.isoformat()},
        },
    }


class WalletJWT(TypedDict):
    iss: str
    aud: str
    origins: list[str]
    typ: str
    payload: WalletJWTPayload


class WalletJWTPayload(TypedDict):
    eventTicketObjects: list[googleapiclient._apis.walletobjects.v1.EventTicketObject]


def _sign_gwallet_jwt_to_url(claims: Any) -> str:
    signer = google.auth.crypt.RSASigner.from_service_account_file(
        config.get("GOOGLE_WALLET_SERVICE_ACCOUNT_KEY")
    )
    token = google.auth.jwt.encode(signer, claims).decode("utf-8")
    return f"https://pay.google.com/gp/v/save/{token}"


def generate_gwallet_pass_url(user: User) -> str:
    new_pass = generate_gwallet_pass(user)
    claims = {
        "iss": config.get("GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL"),
        "aud": "google",
        "origins": ["www.emfcamp.org"],
        "typ": "savetowallet",
        "payload": {
            "eventTicketObjects": [new_pass],
        },
    }
    return _sign_gwallet_jwt_to_url(claims)


def gwallet_api_client() -> googleapiclient._apis.walletobjects.v1.resources.WalletobjectsResource:
    credentials = google.oauth2.service_account.Credentials.from_service_account_file(
        config.get("GOOGLE_WALLET_SERVICE_ACCOUNT_KEY"),
        scopes=["https://www.googleapis.com/auth/wallet_object.issuer"],
    )
    client: googleapiclient._apis.walletobjects.v1.resources.WalletobjectsResource = (
        googleapiclient.discovery.build("walletobjects", "v1", credentials=credentials)
    )
    return client
