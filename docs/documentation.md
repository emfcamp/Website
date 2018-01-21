Links to Documentation
======================

N.B. the version might be wrong for some of these, check against requirements.txt

## Flask

* [Flask](http://flask.pocoo.org/docs/)
* [Flask-Script](http://packages.python.org/Flask-Script/)

## Templates

* [Jinja2](http://jinja.pocoo.org/docs/)
* [Bootstrap](http://twitter.github.com/bootstrap/)

## Forms

* [Flask-WTF](http://packages.python.org/Flask-WTF/)
* [WTForms](http://wtforms.readthedocs.org/en/latest/)

## Database

* [Flask-SQLAlchemy](http://packages.python.org/Flask-SQLAlchemy/)

Note that Flask creates its own declarative base.


## Ticket object model

This is more of a brain dump than documentation, but as there's nothing else yet:

```
                                                  +----------+
                                                  |          |
                         ...........      +-------v-------+  |
                         .         .      |               |  |
         ................>  Type   <......| ProductGroup  +--+
         .               .         .      | CapacityMixin |
         .               .....^.....      +-------+-------+
         .                    .                   |
         .                    .           +-------v-------+   +---------------+
         .                    .           |               |   |               |
         .                    .           |    Product    <---+  ProductView  |
         .                    .           | CapacityMixin |   |               |
         .                    .           +-------+-------+   +---------------+
         .                    .                   |
         .                    .           +-------v-------+
         .                    .           |               |
         .                    .           |   PriceTier   |
         .                    .           | CapacityMixin |
         .                    .           +-------+-------+
         .                    .                   |
         .                    .           +-------v-------+
         .                    .           |               |
         .                    .           |     Price     |
         .                    .           | ReadOnlyMixin |
         .                    .           +---------------+
         .                    .                   |
+-----------------+     +-----------+      +------v------+
|                 |     |           |      |             |
| AdmissionTicket <=====|  Ticket   <======|  Purchase   |
|                 |     |           |      |             |
+-----------------+     +-----------+      +-------------+
```

Type is just a column on ProductGroup, but it determines the subclass of Purchase to use.

All classes with CapacityMixin also have InheritedAttributesMixin except for PriceTier. These allow attributes like "has badge" and "is transferable" to cascade down the hierarchy.

The hierarchy from the leaf-level ProductGroup down to Purchase is all a parent relationship (this is necessitated by the CapacityMixin). This means it's always possible to identify the Type of a Purchase by joining directly up to ProductGroup. It should not be necessary to recurse through ProductGroup except when updating capacity usage.

Price is immutable, so a Purchase can switch currency by referring to other prices within a PriceTier. A Product can only change prices by expiring the relevant PriceTier and adding another.

Only one PriceTier is active at once, and we don't expose what tier was used except to show the price. We use separate products for the "Supporter" tickets, not PriceTiers.

