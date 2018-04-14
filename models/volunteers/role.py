# coding=utf-8
from main import db


RoleTrainers = db.Table('role_trainers', db.Model.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True))


RoleManagers = db.Table('role_managers', db.Model.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True))


class Role(db.Model):
    __tablename__ = 'volunteer-role'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    # Short intro
    description = db.Column(db.String)
    # Things to know for the shift
    role_notes = db.Column(db.String)

    trainers = db.relationship('User',
                               backref='training_roles',
                               secondary=RoleTrainers)

    managers = db.relationship('User',
                               backref='managing_roles',
                               secondary=RoleManagers)
