import textwrap

import pytest
from dateutil.parser import parse

from models.cfp import TalkProposal, Venue
from apps.cfp_review.sense_check import not_sensible_reasons


@pytest.fixture
def override_event_time(app):
    """Override the EVENT_START and EVENT_END properties to 2024."""

    old_start, old_end = app.config['EVENT_START'], app.config['EVENT_END']
    app.config['EVENT_START'] = '2024-05-30 11:00:00 BST'  # Wednesday, May 30
    app.config['EVENT_END'] = '2024-06-02 19:00:00 BST'  # Sunday, June 2
    yield
    app.config['EVENT_START'], app.config['EVENT_END'] = old_start, old_end


VENUE_TALK = Venue(name='Talk Venue', allowed_types=['talk'])
VENUE_WORKSHOP = Venue(name='Workshop Venue', allowed_types=['workshop'])


def _talk_with_time_period(periods) -> TalkProposal:
    return TalkProposal(
        scheduled_time=parse('2024-05-30 12:00:00 BST'),
        scheduled_venue=VENUE_TALK,
        scheduled_duration=25,
        allowed_times=textwrap.dedent(periods).strip() + "\n",
    )


@pytest.mark.parametrize('inp, expected', [
    # Correctly scheduled
    pytest.param(TalkProposal(
        scheduled_time=parse('2024-05-30 12:00:00 BST'),
        scheduled_venue=VENUE_TALK,
        scheduled_duration=25,
    ), set(), id="correctly-scheduled"),
    # Not scheduled but accepted
    pytest.param(TalkProposal(), {'not_scheduled', 'no_duration'}, id="accepted-but-not-scheduled"),
    # No venue, but has scheduled time
    pytest.param(TalkProposal(
        scheduled_time=parse('2024-05-30 12:00:00 BST'),
        scheduled_duration=25,
    ), {'scheduled_without_venue'}, id="scheduled-without-venue"),
    # No proposed venue, but has proposed time
    pytest.param(TalkProposal(
        potential_time=parse('2024-05-30 12:00:00 BST'),
        scheduled_duration=25,
    ), {'proposed_without_venue'}, id="proposed-without-venue"),
    # Before event
    pytest.param(TalkProposal(
        potential_time=parse('2024-05-30 11:00:00 BST'),  # 1 hour before 12 noon
        potential_venue=VENUE_TALK,
        scheduled_time=parse('2024-05-30 10:00:00 BST'),  # 2 hours before 12 noon
        scheduled_venue=VENUE_TALK,
        scheduled_duration=180,
    ), {'proposed_start', 'scheduled_start'}, id="before-event"),
    # After event
    pytest.param(TalkProposal(
        potential_time=parse('2024-06-03 01:00:00 BST'),  # 1 hour before 2am (i.e. in bounds, but end is not)
        potential_venue=VENUE_TALK,
        scheduled_time=parse('2024-06-03 04:00:00 BST'),  # 2 hours after 2am
        scheduled_venue=VENUE_TALK,
        scheduled_duration=180,
    ), {'scheduled_start', 'scheduled_end', 'proposed_end', 'proposed_end_quiet', 'scheduled_start_quiet', 'scheduled_end_quiet'}, id="after-event"),
    # During event, but between 2am and 9am
    pytest.param(TalkProposal(
        potential_time=parse('2024-06-01 03:00:00 BST'),  # 1 hour after 2am
        potential_venue=VENUE_TALK,
        scheduled_time=parse('2024-06-01 04:00:00 BST'),  # 2 hours after 2am
        scheduled_venue=VENUE_TALK,
        scheduled_duration=25,
    ), {'proposed_start_quiet', 'proposed_end_quiet', 'scheduled_start_quiet', 'scheduled_end_quiet'}, id="in-quiet-period"),
    # Scheduled in wrong type of venue
    pytest.param(TalkProposal(
        potential_time=parse('2024-05-30 12:00:00 BST'),
        potential_venue=VENUE_WORKSHOP,
        scheduled_time=parse('2024-05-30 12:00:00 BST'),
        scheduled_venue=VENUE_WORKSHOP,
        scheduled_duration=25,
    ), {'proposed_venue_illegal', 'scheduled_venue_illegal'}, id="illegal-venue"),
    # Time period ends before it starts
    pytest.param(_talk_with_time_period('''
        2024-05-30 11:00:00 > 2024-05-30 10:00:00
    '''), {'period_0_starts_after_end'}, id="period-ends-before-it-starts"),
    # Time period spans multiple days (and therefore overlaps the quiet period)
    pytest.param(_talk_with_time_period('''
        2024-05-30 12:00:00 > 2024-06-02 12:00:00
    '''), {'period_0_too_long'}, id="period-too-long"),
    # Time period starts in 2am-9am quiet period
    pytest.param(_talk_with_time_period('''
        2024-05-30 03:00:00 > 2024-05-30 12:00:00
    '''), {'period_0_starts_in_quiet'}, id="period-starts-in-quiet"),
    # Time period ends in 2am-9am quiet period
    pytest.param(_talk_with_time_period('''
        2024-05-30 01:00:00 > 2024-05-30 03:00:00
    '''), {'period_0_ends_in_quiet'}, id="period-ends-in-quiet"),
    # Time period spans before and after quiet period
    pytest.param(_talk_with_time_period('''
        2024-05-30 01:00:00 > 2024-05-30 10:00:00
    '''), {'period_0_same_day_subsumes_quiet'}, id="period-same-day-subsumes-quiet"),
    pytest.param(_talk_with_time_period('''
        2024-05-29 22:00:00 > 2024-05-30 10:00:00
    '''), {'period_0_different_day_subsumes_quiet'}, id="period-different-day-subsumes-quiet"),
])
def test_cfp_sense_check(override_event_time, inp, expected):
    print(not_sensible_reasons(inp))
    not_sensible = set(not_sensible_reasons(inp).keys())
    assert not_sensible == expected
