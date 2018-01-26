from main import db
from sqlalchemy.orm import column_property
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy import and_, func, FetchedValue
from .purchase import bought_states
from .exc import CapacityException


class CapacityMixin(object):
    """ Defines a database object which has an optional maximum capacity and an optional parent
        (which must also inherit CapacityMixin). Objects also have an expiry date.

        An object's capacity is the lower of its own capacity (if set) and its parent's
        capacity.

        Objects which inherit this mixin must have a "parent" relationship.
    """

    # A max capacity of None implies no max (or use parent's if set)

    capacity_max = db.Column(db.Integer, default=None)
    capacity_used = db.Column(db.Integer, default=0, server_onupdate=FetchedValue())

    expires = db.Column(db.DateTime)

    @declared_attr
    def __expired(self):
        return column_property(and_(~self.expires.is_(None), self.expires < func.now()))

    def has_capacity(self, count=1):
        """
        Determine whether this object, and all its ancestors, have
        available capacity.

        The count parameter (default: 1) determines whether there is capacity
        for count instances.
        """
        if count < 1:
            raise ValueError("Count cannot be less than 1.")

        return count <= self.get_total_remaining_capacity()

    def remaining_capacity(self):
        """
        Return remaining capacity or inf if
        capacity_max is not set (i.e. None).
        """
        if self.capacity_max is None:
            return float('inf')
        return self.capacity_max - self.capacity_used

    def get_total_remaining_capacity(self):
        """
        Get the capacity remaining to this object, and all its ancestors.

        Returns inf if no objects have a capacity_max set.
        """
        remaining = [self.remaining_capacity()]
        if self.parent:
            remaining.append(self.parent.get_total_remaining_capacity())

        return min(remaining)

    def has_expired(self):
        """
        Determine whether this object, and any of its ancestors, have
        expired.
        """
        if self.parent and self.parent.has_expired():
            return True

        return bool(self.expires) and self.__expired

    def issue_instances(self, count=1, token=''):
        """
        If possible (i.e. the object has not expired and has capacity)
        reduce the available capacity by count.

        This design (cascading up instead of carving out allocations)
        is liable to contention if there's a rush on reservations.
        """
        if not self.has_capacity(count):
            raise CapacityException("Out of capacity.")

        if self.has_expired():
            raise CapacityException("Expired.")

        if self.parent:
            self.parent.issue_instances(count, token)
        self.capacity_used = self.__class__.capacity_used + count

    def return_instances(self, count=1):
        " Reintroduce previously used capacity "
        if count < 1:
            raise ValueError("Count cannot be less than 1.")
        self.parent.return_instances(count)
        self.capacity_used = self.__class__.capacity_used - count

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
