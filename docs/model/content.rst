Content system
==============

Proposals
---------

Proposals deal exclusively with content which is submitted via the CfP
for inclusion in the official schedule.

Some proposals are handled through an anonymous review system, where
they are anonymised and sent to a review panel to vote on.

.. autoclass:: models.cfp.Proposal
    :members:

.. autodata:: models.cfp.ProposalState

.. autodata:: models.cfp.ProposalType

Schedule
--------

The schedule deals with the entire schedule for the event, including accepted
CfP content, manually-added/booked official content, and attendee content.

.. autoclass:: models.cfp.ScheduleItem
    :members:

.. autoclass:: models.cfp.Occurrence
    :members:


Venues
------

.. autoclass:: models.cfp.Venue
    :members:
