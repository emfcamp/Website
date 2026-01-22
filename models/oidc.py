from authlib.integrations.sqla_oauth2 import OAuth2AuthorizationCodeMixin, OAuth2ClientMixin, OAuth2TokenMixin

from main import db

from . import BaseModel


class OAuth2Client(BaseModel, OAuth2ClientMixin):
    __tablename__ = "oauth2_client"

    id = db.Column(db.Integer, primary_key=True)
    official = db.Column(db.Boolean)


class OAuth2Token(BaseModel, OAuth2TokenMixin):
    __tablename__ = "oauth2_token"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"))
    user = db.relationship("User")


class OAuth2AuthorizationCode(BaseModel, OAuth2AuthorizationCodeMixin):
    __tablename__ = "oauth2_authcode"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"))
    user = db.relationship("User")
