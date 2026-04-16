Content system
==============

Proposals
---------

Proposals deal exclusively with content which is submitted via the Call for Participation
for inclusion in the official schedule.

Some proposals are handled through an anonymous review system, where
they are anonymised and sent to a review panel to vote on.

.. autoclass:: models.content.cfp.Proposal
    :members:

.. autodata:: models.content.cfp.ProposalState

.. autodata:: models.content.cfp.ProposalType

Schedule
--------

The schedule deals with the entire schedule for the event, including accepted
CfP content, manually-added/booked official content, and attendee content.

.. autoclass:: models.content.schedule.ScheduleItem
    :members:

.. autoclass:: models.content.schedule.Occurrence
    :members:


Venues
------

.. autoclass:: models.content.venue.Venue
    :members:
