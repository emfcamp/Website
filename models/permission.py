# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from main import db


class Permission(db.Model):
    __tablename__ = 'permission'
    __export_data__ = False
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, index=True)

    def __init__(self, name):
        self.name = name


UserPermission = db.Table('user_permission', db.Model.metadata,
    db.Column('id', db.Integer, primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), nullable=False, index=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permission.id'), nullable=False))
