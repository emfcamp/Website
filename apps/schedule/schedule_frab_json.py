from datetime import timedelta
from math import ceil

from main import external_url
from models import event_end, event_start, event_year

from . import event_tz
from .schedule_frab_xml import get_day_start_end, get_duration


def events_per_day_and_room(schedule):
    days = {
        current_date.date(): {
            "index": index + 1,
            "start": get_day_start_end(event_start() + timedelta(days=index))[0],
            "end": get_day_start_end(event_start() + timedelta(days=index))[1],
            "rooms": {},
        }
        for index, current_date in enumerate(
            event_start() + timedelta(days=i) for i in range((event_end() - event_start()).days + 1)
        )
    }

    for proposal in schedule:
        talk_date = proposal.start_date.date()
        if proposal.start_date.hour < 4 and talk_date != event_start().date():
            talk_date -= timedelta(days=1)
        if talk_date not in days:
            # Event is outside the scheduled event duration.
            continue
        if proposal.scheduled_venue.name not in days[talk_date]:
            days[talk_date]["rooms"][proposal.scheduled_venue.name] = [proposal]
        else:
            days[talk_date]["rooms"][proposal.scheduled_venue.name].append(proposal)

    return days.values()


def export_frab_json(schedule):
    duration_days = ceil((event_end() - event_start()).total_seconds() / 86400)

    rooms = set([proposal.scheduled_venue.name for proposal in schedule])

    schedule_json = {
        "version": "1.0-public",
        "conference": {
            "acronym": "emf{}".format(event_year()),
            "days": [],
            "daysCount": duration_days,
            "end": event_end().strftime("%Y-%m-%d"),
            "rooms": [
                {
                    "name": room,
                }
                for room in sorted(rooms)
            ],
            "start": event_start().strftime("%Y-%m-%d"),
            "time_zone_name": str(event_tz),
            "timeslot_duration": "00:10",
            "title": "Electromagnetic Field {}".format(event_year()),
            "url": external_url(".main"),
        },
    }

    for day in events_per_day_and_room(schedule):
        day_schedule = {
            "date": day["start"].strftime("%Y-%m-%d"),
            "day_end": day["start"].isoformat(),
            "day_start": day["end"].isoformat(),
            "index": day["index"],
            "rooms": {},
        }
        for room, events in sorted(day["rooms"].items()):
            day_schedule["rooms"][room] = []
            for proposal in events:
                links = {
                    proposal.c3voc_url,
                    proposal.youtube_url,
                    proposal.thumbnail_url,
                    proposal.map_link,
                }
                links.discard(None)
                links.discard("")
                day_schedule["rooms"][room].append(
                    {
                        "abstract": None,  # The proposal model does not implement abstracts
                        "attachments": [],
                        "date": event_tz.localize(proposal.start_date).isoformat(),
                        "description": proposal.description,
                        "do_not_record": proposal.video_privacy != "public",
                        "duration": get_duration(proposal.start_date, proposal.end_date),
                        "guid": None,
                        "id": proposal.id,
                        # This assumes there will never be a non-english talk,
                        # which is probably fine for a conference in the UK.
                        "language": "en",
                        "links": sorted(links),
                        "persons": [
                            {
                                "name": name.strip(),
                                "public_name": name.strip(),
                            }
                            for name in (proposal.published_names or proposal.user.name).split(",")
                        ],
                        "recording_license": "CC BY-SA 3.0",
                        "room": room,
                        "slug": "emf{}-{}-{}".format(
                            event_year(),
                            proposal.id,
                            proposal.slug,
                        ),
                        "start": event_tz.localize(proposal.start_date).strftime("%H:%M"),
                        "subtitle": None,
                        "title": proposal.display_title,
                        # Contrary to the infobeamer frab module, the json module does not allow users to set colours
                        # for tracks themselves. It instead relies on the schedule itself to provide those colours.
                        "track": None,
                        "type": proposal.type,
                        "url": external_url(
                            ".item",
                            year=event_year(),
                            proposal_id=proposal.id,
                            slug=proposal.slug,
                        ),
                    }
                )
        schedule_json["conference"]["days"].append(day_schedule)
    return schedule_json
