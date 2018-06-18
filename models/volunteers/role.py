# coding=utf-8
from main import db


RoleTrainers = db.Table('role_trainers', db.Model.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True))


RoleManagers = db.Table('role_managers', db.Model.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True))


class Role(db.Model):
    __tablename__ = 'volunteer_role'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False, unique=True, index=True)
    description = db.Column(db.String)
    # Things to know for the shift
    role_notes = db.Column(db.String)

    trainers = db.relationship('User', secondary=RoleTrainers,
                               backref='training_roles')

    managers = db.relationship('User', secondary=RoleManagers,
                               backref='managing_roles')


class RoleVolunteers(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), primary_key=True)
    approving_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))


class Shift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), primary_key=True)
    start = db.Column(db.DateTime)
    end = db.Column(db.DateTime)

class NeededRoles(db.Model):
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), primary_key=True)
    count = db.Column(db.Integer, nullable=False, default=0)

class ShiftEntry(db.Model):
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    # comment?



