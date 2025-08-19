"""Stuff to generate Apple pkpass tickets."""

from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable
import zipfile
from flask import current_app as app
import pytz

from apps.common.receipt import get_purchase_metadata
from models.user import User

# https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/PassKit_PG/Creating.html
MAX_PASS_LOCATIONS = 10


class PkPassException(Exception):
    """Base pkpass generator exception."""


class TooManyPassLocations(PkPassException):
    """Too many pass locations specified in config."""

    def __init__(self, count) -> None:
        self.count = count

    def __str__(self) -> str:
        return f"{self.__doc__} Got {self.count}, max is {MAX_PASS_LOCATIONS}"


class InvalidPassConfig(PkPassException):
    """Pass config does not match expected schema"""

    missing: set[str]
    extra: set[str]

    def __init__(self, *, missing, extra) -> None:
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
    things: Iterable[dict[str, Any]], expected_keys: set[str], optional_keys: set[str] = set()
):
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


def generate_pass_data(user) -> dict[str, Any]:
    meta = get_purchase_metadata(user)
    expire_dt = datetime.strptime(app.config["EVENT_END"], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=pytz.timezone("Europe/London")
    )
    return {
        "passTypeIdentifier": app.config["PKPASS_IDENTIFIER"],
        "teamIdentifier": app.config["PKPASS_TEAM_ID"],
        "formatVersion": 1,
        # Use the checkin code as a unique serial.
        "serialNumber": user.checkin_code,
        "organizationName": "Electromagnetic Field",
        "logoText": "Electromagnetic Field",
        "description": "Electromagnetic Field Entry Pass",
        "locations": _get_and_validate_locations(),
        "beacons": _get_beacons(),
        "maxDistance": app.config.get("PKPASS_MAX_DISTANCE", 50),
        "barcodes": [
            {
                "format": "PKBarcodeFormatQR",
                "message": app.config["CHECKIN_BASE"] + user.checkin_code,
                "messageEncoding": "iso-8859-1",
            }
        ],
        "foregroundColor": "rgb(255, 255, 255)",
        "labelColor": "rgb(255, 255, 255)",
        # Allow users to share passes, since they could just send the PDF anyway...
        "sharingProhibited": False,
        "expirationDate": expire_dt.strftime("%Y-%m-%dT%H:%M:%S%:z"),
        # "expirationDate": expire_dt.isoformat(),
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
        "accessibilityURL": "https://emfcamp.orgabout/accessibility",
    }


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
    assets = Path(app.config.get("PKPASS_ASSETS_DIR", "images/pkpass"))
    files |= {p.name: open(p, "rb").read() for p in assets.iterdir() if p.is_file()}
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
