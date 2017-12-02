import sys
from main import db
from datetime import datetime
from sqlalchemy.orm import column_property
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy import and_, func
from .purchase import bought_states
from .exc import CapacityException


# These need to be used in migrations
CAPACITY_CONSTRAINT_SQL = "capacity_used <= capacity_max"
CAPACITY_CONSTRAINT_NAME = "within_capacity"

class CapacityMixin(object):
    """ Defines a database object which has an optional maximum capacity and an optional parent
        (which must also inherit CapacityMixin). Objects also have an expiry date.

        An object's capacity is the lower of its own capacity (if set) and its parent's
        capacity.

        Objects which inherit this mixin must have a "parent" relationship.
    """

    # A max capacity of None implies no max (or use parent's if set)

    capacity_max = db.Column(db.Integer, default=None)
    capacity_used = db.Column(db.Integer, default=0)

    expires = db.Column(db.DateTime)

    @declared_attr
    def __expired(self):
        return column_property(and_(~self.expires.is_(None), self.expires < func.now()))

    # This doesn't really do anything here as flask-migrate/alembic doesn't
    # seem to for CHECK-constraints but it's here for completeness
    db.CheckConstraint(CAPACITY_CONSTRAINT_SQL, name=CAPACITY_CONSTRAINT_NAME)

    def has_capacity(self, count=1, session=None):
        """
        Determine whether this object, and all its ancestors, have
        available capacity.

        The count parameter (default: 1) determines whether there is capacity
        for count instances.
        """
        if count < 1:
            raise ValueError("Count cannot be less than 1.")

        return count <= self.get_total_remaining_capacity(session)

    def remaining_capacity(self, session=None):
        """
        Return remaining capacity or sys.maxsize (a very big integer) if
        capacity_max is not set (i.e. None).

        If a session is provided this check is performed with 'FOR UPDATE'
        row locking.
        """
        if session is None:
            item = self
        else:
            item = session.query(self.__class__)\
                          .with_for_update()\
                          .filter_by(id=self.id)\
                          .first()

        if item.capacity_max is None:
            return sys.maxsize
        return item.capacity_max - item.capacity_used

    def get_total_remaining_capacity(self, session=None):
        """
        Get the capacity remaining to this object, and all its ancestors.

        Returns sys.maxsize if no object have a capacity_max set.
        """
        remaining = [self.remaining_capacity(session)]
        if self.parent:
            remaining.append(self.parent.get_total_remaining_capacity(session))

        return min(remaining)

    def has_expired(self):
        """
        Determine whether this object, and any of its ancestors, have
        expired.
        """
        if self.parent and self.parent.has_expired():
            return True

        return self.expires and self.expires < datetime.utcnow()

    def issue_instances(self, session, count=1, token=''):
        """
        If possible (i.e. the object has not expired and has capacity)
        reduce the available capacity by count.
        """
        if not self.has_capacity(count, session):
            raise CapacityException("Out of capacity.")

        if self.has_expired():
            raise CapacityException("Expired.")

        if self.parent:
            self.parent.issue_instances(session, count, token)
        self.capacity_used += count

    def return_instances(self, count=1):
        " Reintroduce previously used capacity "
        if count < 1:
            raise ValueError("Count cannot be less than 1.")
        self.parent.return_instances(count)
        self.capacity_used -= count

    def get_purchase_count(self, states=None):
        """ Get the count of purchases, optionally filtered by purchase state.
            If no states are specified then it will count purchased tickets.
        """
        if states is None:
            states = bought_states
        counts = self.get_purchase_count_by_state(states)
        return sum(counts.values())


class InheritedAttributesMixin(object):
    """ Create a JSON column to store arbitrary attributes. When fetching attributes, cascade up to the parent (which
        must also inherit this mixin).

        Objects which inherit this mixin must have a "parent" relationship.
    """

    attributes = db.Column(db.JSON, default={})

    def get_attribute(self, name):
        if name in self.attributes:
            return self.attributes[name]
        if self.parent:
            return self.parent.get_attribute(name)
        return None

    def set_attribute(self, name, value):
        self.attributes[name] = value
