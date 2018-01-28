Development hints
=================

We have just upgraded to python3, so there may be bits of code or stylistic choices that only make sense in python2.7

We've also recently changed Ticket to Purchase, and TicketType to Product.
There may still be bits of old code that refer to these classes or use confusing names. Please fix them if you see them!

Development processes
=====================

Once tickets are on sale, new development should be done on feature branches. We try to merge to master frequently, so hide anything accessible to visitors behind config. Bugfixes will usually be done on master.

We test all branches with Travis - you can run `make test` locally to run these tests during development.


Links to Documentation
======================
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
* [SQLAlchemy-Continuum](https://sqlalchemy-continuum.readthedocs.io/en/latest/)

If you're familiar with SQLAlchemy, note that Flask creates its own declarative base. This is the db.Model used in our models.


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

