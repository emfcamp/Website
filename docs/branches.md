master
======

Whats on the live site, or is about to be put on the live site. Also quick bugfixes.

ticket-types-fixtures
=====================

For the new buying different types of tickets stuff, issue #68, all of [this](https://github.com/emfcamp/Website/issues?labels=Ordering+work&state=open)

currently:

* can buy different types of tickets
* payment amount is right (will need to be checked)
* everywhere on the website that displays tickets copes with multiple ticket types, apart from /tickets

needs:

* removal of old prepay form from /tickets
* reworking of /buy/tickets form and moving it to /tickets
* removal of 'count' in session (replaced by 'basket')
* re-addition and genericification of ticket limit business logic.
* business logic for ticket that get a discount if you've got a prepay (issue #62 )
* * new can_have_prepay flag in TicketType table?
* email sending & email templates updateing to cope with multiple ticket types
* copy checking to make sure we're not mentioning prepay where we shouldn't be.
* get and store additional info about people attending:
* * issue #29
* * issue #26
* * issue #44


fun-with-bootstrap
==================

For playing with bootstrap away from master, useful for sharing changes so they can be checked before going live.

manual-euro-admin
=================

closed.

prepay
======

closed

ticket-expirey
==============

closed
