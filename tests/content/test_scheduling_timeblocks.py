from dateutil.parser import parse

from models.content.schedule import Occurrence, ScheduleItem, ScheduleItemAvailability
from models.content.venue import TimeBlock, Venue

venue1 = Venue(
    name="Test venue 1",
    time_blocks=[
        TimeBlock(
            start=parse("2026-07-16 10:00:00"),
            end=parse("2026-07-16 18:00:00"),
            type="talk",
            automatic=True,
        ),
        TimeBlock(
            start=parse("2026-07-17 10:00:00"),
            end=parse("2026-07-17 18:00:00"),
            type="talk",
            automatic=True,
        ),
    ],
)

venue2 = Venue(
    name="Test venue 2",
    time_blocks=[
        TimeBlock(
            start=parse("2026-07-16 10:00:00"),
            end=parse("2026-07-16 18:00:00"),
            type="workshop",
            automatic=True,
        )
    ],
)

venue3 = Venue(
    name="Test venue 3",
    time_blocks=[
        TimeBlock(
            start=parse("2026-07-16 10:00:00"),
            end=parse("2026-07-16 18:00:00"),
            type="talk",
            automatic=False,
            default=False,
        ),
        TimeBlock(
            start=parse("2026-07-17 10:00:00"),
            end=parse("2026-07-17 18:00:00"),
            type="talk",
            automatic=False,
            default=False,
        ),
    ],
)


def test_occurrence_time_blocks(user, db):
    db.session.add(venue1)
    db.session.add(venue2)
    db.session.add(venue3)

    si = ScheduleItem(user=user, type="talk", title="Test schedule item", official_content=True)
    occurrence = Occurrence(occurrence_num=1, schedule_item=si, scheduled_duration=30)
    si.occurrences = [occurrence]

    db.session.add(si)
    db.session.commit()

    # By default, an occurrence will be automatically scheduled,
    # and so the only valid timeblocks are the automatic ones
    time_blocks = list(occurrence.time_blocks())
    assert len(time_blocks) == 2
    assert time_blocks[0].venue == venue1
    assert all(block.automatic is True for block in time_blocks)

    # Now we set the scheduled venue to one without any automatic timeblocks.
    # This doesn't change things, as it's still eligible to be automatically
    # scheduled, so the scheduler will send it back to venue 1
    occurrence.scheduled_venue = venue3
    db.session.commit()

    time_blocks = list(occurrence.time_blocks())
    assert len(time_blocks) == 2
    assert time_blocks[0].venue == venue1
    assert all(block.automatic is True for block in time_blocks)

    # Now we set the allowed venues to venue2 and venue3 - this prevents this talk
    # from being scheduled in automatic timeblocks. Venue2 still has no relevant timeblocks,
    # so it must be scheduled in venue3
    occurrence.allowed_venues = [venue2, venue3]
    db.session.commit()

    time_blocks = list(occurrence.time_blocks())
    assert len(time_blocks) == 2
    assert time_blocks[0].venue == venue3
    assert all(block.automatic is False for block in time_blocks)

    # Set the time and the "manually_scheduled" flag. Now this occurrence is pinned
    # to occur in the manual timeblock.
    occurrence.allowed_venues = [venue3]
    occurrence.scheduled_time = parse("2026-07-17 15:00:00")
    occurrence.manually_scheduled = True
    db.session.commit()

    time_blocks = list(occurrence.time_blocks())
    assert len(time_blocks) == 1
    assert time_blocks[0].venue == venue3
    assert time_blocks[0].automatic is False


def test_occurrence_allowed_times(user, db):
    db.session.add(venue1)
    db.session.add(venue2)
    db.session.add(venue3)

    si = ScheduleItem(user=user, type="talk", title="Test schedule item", official_content=True)
    occurrence = Occurrence(occurrence_num=1, schedule_item=si, scheduled_duration=30)
    si.occurrences = [occurrence]

    db.session.add(si)
    db.session.commit()

    # The ScheduleItem has empty availability, so this will return all automatic talk timeblocks,
    # which is just venue1's
    allowed_times = occurrence.allowed_times(True)

    assert len(allowed_times) == 1
    assert venue1 in allowed_times

    # Speaker now sets their availability to a range within one of venue1's timeblocks
    si.availability = [
        ScheduleItemAvailability(
            schedule_item=si, start=parse("2026-07-17 11:00:00"), end=parse("2026-07-17 13:00:00")
        )
    ]
    db.session.commit()

    allowed_times = occurrence.allowed_times(True)
    assert len(allowed_times) == 1
    assert venue1 in allowed_times
    assert len(allowed_times[venue1]) == 1
    assert allowed_times[venue1][0] == (parse("2026-07-17 11:00:00"), parse("2026-07-17 13:00:00"))

    # Wider availability window which overlaps multiple timeblocks
    db.session.delete(si.availability[0])
    si.availability = [
        ScheduleItemAvailability(
            schedule_item=si, start=parse("2026-07-16 15:00:00"), end=parse("2026-07-17 19:00:00")
        )
    ]
    db.session.commit()

    allowed_times = occurrence.allowed_times(True)
    assert len(allowed_times) == 1
    assert venue1 in allowed_times
    assert len(allowed_times[venue1]) == 2
    assert allowed_times[venue1][0] == (parse("2026-07-16 15:00:00"), parse("2026-07-16 18:00:00"))
    assert allowed_times[venue1][1] == (parse("2026-07-17 10:00:00"), parse("2026-07-17 18:00:00"))

    # Now we manually schedule this occurrence.
    # This is scheduled outside the speaker's availability, but the manually-scheduled time takes priority.
    occurrence.manually_scheduled = True
    occurrence.allowed_venues = [venue3]
    occurrence.scheduled_venue = venue3
    occurrence.scheduled_time = parse("2026-07-16 11:00:00")
    db.session.commit()

    allowed_times = occurrence.allowed_times(True)
    assert len(allowed_times) == 1
    assert venue3 in allowed_times
    assert len(allowed_times[venue3]) == 1
    assert allowed_times[venue3][0] == (occurrence.scheduled_time, occurrence.scheduled_end_time)
