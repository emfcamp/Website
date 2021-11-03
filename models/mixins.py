from main import db
from sqlalchemy import event
from sqlalchemy.orm import column_property
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy import and_, func, FetchedValue
from .exc import CapacityException


class CapacityMixin(object):
    """Defines a database object which has an optional maximum capacity and an optional parent
    (which must also inherit CapacityMixin). Objects also have an expiry date.

    An object's capacity is the lower of its own capacity (if set) and its parent's
    capacity.

    Objects which inherit this mixin must have a "parent" relationship.
    """

    # A max capacity of None implies no max (or use parent's if set)
    capacity_max = db.Column(db.Integer, default=None)
    capacity_used = db.Column(
        db.Integer, default=0, nullable=False, server_onupdate=FetchedValue()
    )

    expires = db.Column(db.DateTime)

    @declared_attr
    def __expired(cls):
        return column_property(and_(~cls.expires.is_(None), cls.expires < func.now()))

    @declared_attr
    def __add_event_listeners(cls):
        """
        capacity_used will be touched by multiple users at once, so we lean on the
        DB to lock and update it. This requires an engine with implicit row-level
        locking, like PostgreSQL.

        This is done as late as possible to allow for speculative checking of the
        resulting capacity. A consumer must still check after the flush that this
        transaction doesn't pull any capacities below zero before committing, e.g.

        ```
        with db.session.no_autoflush:
            allocation.return_instances(1)
            allocation.issue_instances(5)
        db.session.flush()
        assert allocation.get_total_remaining_capacity() >= 0
        db.session.commit()
        ```

        SQLAlchemy locks from parent classes down. This is slightly suboptimal,
        but not worth working around. It appears to update in PK order within a
        class, so self-referencing classes shouldn't deadlock.

        hybrid_property.update_expression doesn't yet work on instances as of 1.2.2,
        so this adds a `before_event` event handler to every subclass and swaps
        out capacity_used with the appropriate expression.
        """

        @event.listens_for(cls, "before_update")
        def before_update(mapper, connection, target):
            history = get_history(target, "capacity_used")
            delta = sum(history.added) - sum(history.deleted)
            target.capacity_used = target.__class__.capacity_used + delta

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
            return float("inf")
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

    def issue_instances(self, count):
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
            self.parent.issue_instances(count)

        self.capacity_used += count

    def return_instances(self, count):
        "Reintroduce previously used capacity"
        if self.parent:
            self.parent.return_instances(count)

        self.capacity_used -= count


class InheritedAttributesMixin(object):
    """Create a JSON column to store arbitrary attributes. When fetching attributes, cascade up to the parent (which
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
        # SQLAlchemy can't recognise changes within JSON structures
        attrs = self.attributes.copy()
        attrs[name] = value
        self.attributes = attrs
