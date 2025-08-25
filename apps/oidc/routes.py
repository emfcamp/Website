import logging

import click
from authlib.oauth2 import OAuth2Error
from authlib.oauth2.rfc6749.util import scope_to_list
from authlib.oidc.discovery import OpenIDProviderMetadata
from flask import Blueprint, jsonify, render_template, request, url_for
from flask.typing import ResponseValue
from flask_login import current_user, login_required
from werkzeug.security import gen_salt

from main import db
from models.oidc import OAuth2Client

from .oauth import SCOPES, authorization, get_issuer

logger = logging.getLogger(__name__)
oidc = Blueprint("oidc", "oidc")


@oidc.cli.command("create_client")
@click.option("--name", type=str)
@click.option("--redirecturi", type=str)
@click.option("--official/--unofficial")
@click.option("--scope", default=["openid"], multiple=True)
def create_client(name: str, redirecturi: str, official: bool, scope: list[str]):
    if invalid := [s for s in scope if s not in SCOPES]:
        logger.error("Invalid scopes: %s", ", ".join(invalid))
        raise click.exceptions.Exit(1)

    client = OAuth2Client(
        client_id=gen_salt(24),
        official=official,
    )
    client.set_client_metadata(
        {
            "client_name": name,
            "redirect_uris": [redirecturi],
            "grant_types": ["code"],
            "response_types": ["code id_token"],
            "scope": " ".join(scope),
        }
    )
    db.session.add(client)
    db.session.commit()
    logger.info("New OIDC client created. Client id: %s", client.client_id)


@oidc.get("/.well-known/openid-configuration")
def discovery() -> ResponseValue:
    """Implements the OpenID Connect Discovery protocol.

    https://openid.net/specs/openid-connect-discovery-1_0.html
    """
    m = OpenIDProviderMetadata(
        issuer=get_issuer(),
        authorization_endpoint=url_for("oidc.authorize", _external=True),
        token_endpoint=url_for("oidc.token", _external=True),
        jwks_uri=url_for("oidc.jwks", _external=True),
        response_types_supported=["code", "id_token", "code id_token"],
        subject_types_supported=["public"],
        id_token_signing_alg_values_supported=["RS256"],
    )
    m.validate()
    return m


@oidc.route("/oidc/authorize", methods=["GET", "POST"])
@login_required
def authorize() -> ResponseValue:
    if request.method == "GET":
        try:
            grant = authorization.get_consent_grant(end_user=current_user)
            scope = grant.client.get_allowed_scope(grant.request.payload.scope)
        except OAuth2Error as e:
            return jsonify(dict(e.get_body()))

        scopes = {s: SCOPES[s] for s in scope_to_list(scope)}
        scopents = {scope: desc for scope, desc in SCOPES.items() if scope not in scopes}
        return render_template("oidc/authorize.html", grant=grant, scopes=scopes, scopents=scopents)
    res = authorization.create_authorization_response(
        grant_user=current_user if "authorize" in request.form else None
    )
    return res


@oidc.post("/oidc/token")
def token():
    return authorization.create_token_response()


@oidc.get("/.well-known/jwks.json")
def jwks(): ...
