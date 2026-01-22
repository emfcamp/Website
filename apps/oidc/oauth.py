from typing import TypedDict

import authlib.oauth2.rfc6749.grants as rfc6749_grants
import authlib.oidc.core.grants as oidc_core_grants
from authlib.integrations.flask_oauth2 import AuthorizationServer
from authlib.integrations.sqla_oauth2 import create_query_client_func, create_save_token_func
from authlib.oauth2.rfc6749 import OAuth2Request
from authlib.oauth2.rfc6749.util import scope_to_list
from authlib.oidc.core.claims import UserInfo
from flask import request

from main import db
from models.oidc import OAuth2AuthorizationCode, OAuth2Client, OAuth2Token
from models.user import User

SCOPES: dict[str, str] = {
    "openid": "Your anonymous account identifier",
    "email": "The email address associated with your account",
    "permissions": "Your EMF website permissions",
}


def get_issuer():
    return f"https://{request.host}"


def save_authorization_code(code: str, request: OAuth2Request) -> OAuth2AuthorizationCode:
    client = request.client
    item = OAuth2AuthorizationCode(
        code=code,
        client_id=client.client_id,
        redirect_uri=request.payload.redirect_uri,
        scope=request.payload.scope,
        user_id=request.user.id,
    )
    db.session.add(item)
    db.session.commit()
    return item


def exists_nonce(nonce, request) -> bool:
    # TODO: implement me!
    return False


class JWTConfig(TypedDict):
    key: str
    alg: str
    iss: str
    exp: int


def get_jwt_config(grant) -> JWTConfig:
    return JWTConfig(key="foo", alg="HS256", iss=get_issuer(), exp=999999999999)


def generate_user_info(user: User, scope) -> UserInfo:
    info = {
        "sub": user.id,
    }
    scopes = scope_to_list(scope)
    if "email" in scopes:
        info["email"] = user.email
    if "permissions" in scopes:
        info["permissions"] = [p.name for p in user.permissions]

    return UserInfo(info)


class AuthorizationCodeGrant(rfc6749_grants.AuthorizationCodeGrant):
    def save_authorization_code(self, code, request):
        return save_authorization_code(code, request)

    def parse_authorization_code(self, code, client) -> OAuth2AuthorizationCode | None:
        authcode = OAuth2AuthorizationCode.query.filter_by(code=code, client_id=client.client_id).first()
        if authcode and not authcode.is_expired():
            return authcode
        return None

    def delete_authorization_code(self, authorization_code):
        db.session.delete(authorization_code)
        db.session.commit()

    def authenticate_user(self, authorization_code):
        return User.query.get(authorization_code.user_id)


class OpenIDCode(oidc_core_grants.OpenIDCode):
    def exists_nonce(self, nonce, request):
        return exists_nonce(nonce, request)

    def get_jwt_config(self, grant) -> JWTConfig:
        return get_jwt_config(grant)

    def generate_user_info(self, user, scope) -> UserInfo:
        return generate_user_info(user, scope)


class ImplicitGrant(oidc_core_grants.OpenIDImplicitGrant):
    def exists_nonce(self, nonce, request) -> bool:
        return exists_nonce(nonce, request)

    def get_jwt_config(self) -> JWTConfig:
        return get_jwt_config(grant=None)

    def generate_user_info(self, user, scope) -> UserInfo:
        return generate_user_info(user, scope)


class HybridGrant(oidc_core_grants.OpenIDHybridGrant):
    def save_authorization_code(self, code, request):
        return save_authorization_code(code, request)

    def exists_nonce(self, nonce, request) -> bool:
        return exists_nonce(nonce, request)

    def get_jwt_config(self) -> JWTConfig:
        return get_jwt_config(grant=None)

    def generate_user_info(self, user, scope) -> UserInfo:
        return generate_user_info(user, scope)


authorization = AuthorizationServer()


def init_oauth(app):
    query_client = create_query_client_func(db.session, OAuth2Client)
    save_token = create_save_token_func(db.session, OAuth2Token)

    authorization.init_app(app, query_client=query_client, save_token=save_token)
    authorization.register_grant(AuthorizationCodeGrant, [OpenIDCode(require_nonce=True)])
    authorization.register_grant(ImplicitGrant)
    authorization.register_grant(HybridGrant)
