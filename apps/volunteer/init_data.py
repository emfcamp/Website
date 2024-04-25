venue_list = [
    {
        "name": "Badge Tent",
        "mapref": "https://map.emfcamp.org/#20.24/52.0405486/-2.3781891",
    },
    {
        "name": "Cybar",
        "mapref": "https://map.emfcamp.org/#19/52.0409755/-2.3786306",
    },
    {"name": "Bar", "mapref": "https://map.emfcamp.org/#19/52.0420157/-2.3770749"},
    {
        "name": "Car Park",
        "mapref": "https://map.emfcamp.org/#19.19/52.0389412/-2.3783488",
    },
    {
        "name": "Entrance Tent",
        "mapref": "https://map.emfcamp.org/#18/52.039226/-2.378184",
    },
    {
        "name": "Green Room",
        "mapref": "https://map.emfcamp.org/#20.72/52.0414959/-2.378016",
    },
    {
        "name": "Stage A",
        "mapref": "https://map.emfcamp.org/#17/52.039601/-2.377759",
    },
    {
        "name": "Stage B",
        "mapref": "https://map.emfcamp.org/#17/52.041798/-2.376412",
    },
    {
        "name": "Stage C",
        "mapref": "https://map.emfcamp.org/#17/52.040482/-2.377432",
    },
    {
        "name": "Volunteer Kitchen",
        "mapref": "https://map.emfcamp.org/#20.82/52.0397817/-2.3767928",
    },
    {
        "name": "Info/Volunteer Tent",
        "mapref": "https://map.emfcamp.org/#20.82/52.0397817/-2.3767928",
    },
    {
        "name": "Logistics Tent",
        "mapref": "https://map.emfcamp.org/#20.82/52.0397817/-2.3767928",
    },
    {
        "name": "Shop",
        "mapref": "https://map.emfcamp.org/#20.82/52.0397817/-2.3767928",
    },
    {
        "name": "Youth Workshop",
        "mapref": "https://map.emfcamp.org/#19.46/52.0420979/-2.3753702",
    },
    {
        "name": "NOC",
        "mapref": "https://map.emfcamp.org/#21.49/52.0415113/-2.3776567",
    },
    {
        "name": "Vehicle Gate Y",
        "mapref": "https://map.emfcamp.org/#21.49/52.0415113/-2.3776567",
    },
    {"name": "N/A", "mapref": "https://map.emfcamp.org/#16/52.0411/-2.3784"},
]

role_list = [
    # Stage stuff
    {
        "name": "Herald",
        "description": "Introduce talks and manage speakers at stage.",
        "full_description_md": """
Introducing talks, and making any announcements that are needed between talks.

You'll be helping speakers get ready, introducing them on stage and checking to make sure any announcements that need to happen are made between talks. If you have any talks you'd particularly like to see you can volunteer for a shift on the appropriate stage.

If you've never walked on stage before then don't be put off; we'll be running some training to walk through the role and make sure everyone is comfortable. In fact many of us would identify as introverts.
            """,
    },
    {
        "name": "Content Team",
        "description": "Member of Content at the Green Room",
        "role_notes": "Content Team only",
        "requires_training": True,
        "full_description_md": """
This is an internal role for the Content Team to schedule the folks who will be in the Green Room helping manage the schedule.

It requires access to the backend of the CfP, and training on how to use it. 

If you're interested in helping us out next year, please shoot us an email at content@emfcamp.org!
            """,
    },
    {
        "name": "Stage: Audio/Visual",
        "description": "Run the audio for a stage. Make sure mics are working and that presentations work.",
        "full_description_md": """
Run the audio for a stage. Make sure mics are working and that presentations work.

# What's involved

* Testing sound levels for the next speaker
* Managing sound levels during talks
* Recalling lighting presets
* Helping speakers set up any presentations/audio they require

No experience is required, although it might be helpful to have used an audio mixer
before.
        """,
    },
    {
        "name": "Stage: Camera Operator",
        "description": "Point, focus and expose the camera, then lock off shot and monitor it.",
        "full_description_md": """
Set up the camera to record talks, then monitor it during recording.

There will be training sessions for how to operate the equipment run throughout the event - ask at volunteer desk for when these will be.
        """,
    },
    {
        "name": "Stage: Vision Mixer",
        "description": "Vision mix the output to screen and to stream.",
        "full_description_md": """
Control the video and presentations going to the screens and video recording.

There will be training sessions for how to operate the equipment run throughout the event - ask at volunteer desk for when these will be.
        """,
    },
    {
        "name": "Badge Helper",
        "description": "Fix, replace and troubleshoot badges and their software.",
        "full_description_md": """
Fix, replace and troubleshoot badges and their software.

Some experience of soldering and/or embedded software would like be useful, but if you're willing to learn we can teach you the basics so you can help people out.
        """,
    },
    {
        "name": "Car Parking",
        "description": "Help park cars and get people on/off site.",
        "full_description_md": """
Help park cars, and get people on/off site.

This role can involve quite a lot of walking, and standing in the sun and/or rain, but it is also super useful, and can be picked up very quickly.

You need to make sure that the Accessible Parking is kept clear for those that need it; similarly the EV area.

We do not require any proof that someone needs to use accessible parking; if they say they do - they do. They can get a permit at the entrance tent.
        """,
    },
    {
        "name": "Kitchen Helper",
        "description": "Help our excellent catering team provide food for all the volunteers.",
        "full_description_md": """
Help our excellent catering team provide food for all the volunteers.

Mostly you’ll be chopping vegetables, washing up, and serving food, the catering team will handle the actual cooking.
        """,
    },
    {
        "name": "Entrance Steward",
        "description": "Greet people, check their tickets and help them get on site.",
        "full_description_md": """
Greet people, check their tickets and help them get on site.

On the first day this role involves checking tickets and welcoming people to the site, after that it's mostly just checking that people have wristbands on when they walk in.
        """,
    },
    #  {
    #             "name": "Games Master",
    #             "description": "Running Indie Games on the big screen in Stage A, and optionally Board Games.",
    #             "fulle_description": """
    # Running Indie Games on the big screen in Stage A, and optionally Board Games.
    # # What you'll be doing
    # The Games Master will set up a hangout place for people to watch and play games,
    # both computer and boardgames. We'll provide a laptop, controllers, and games to
    # run on the big screen, and there are people bringing board games.
    # ## Setup
    # * Ambient music played over the PA
    # * Laptop projecting onto the big presentation screen
    # * Conference style chair seating near the front and centre of the stage moved
    # away to form an open space for people to come and sit in an organic arrangement
    # * Optionally, move any available tables into the area for board games
    # ## Running
    # * Attempting to fix any game/tech issues
    # * Moving on people who've been hogging the screen if a queue is forming
    # * If you happen to know about board games, maybe recommending ones that people
    # would enjoy.
    # ## Close
    # * Restore seating
    # * Pack away and secure laptop/controllers etc
    # * Power down AV equipment
    # """,
    #         },
    {
        "name": "Green Room Runner",
        "description": "Make sure speakers get where they need to be with what they need.",
        "full_description_md": """
Make sure speakers get where they need to be with what they need.

You’ll be based in the Green Room where you’ll greet speakers and get them ready to go on stage. You'll also help out the Content Team with any adhoc tasks that come up. 
            """,
    },
    {
        "name": "Info Desk",
        "description": "Be a point of contact for attendees. Either helping with finding things or just getting an idea for what's on.",
        "full_description_md": """
Be a point of contact for attendees. Either helping with finding things or just getting an idea for what's on.

The information desk is generally the first place people come to with questions, you’ll have a set of answers to commonly asked questions, and phone numbers for people who can help you get answers to the ones we haven’t thought of.
        """,
    },
    {
        "name": "Youth Workshop Helper",
        "description": "Help support our youth workshop leaders and participants.",
        "full_description_md": """
Help support our youth workshop leaders and participants.

You’ll be assisting workshop leaders in running sessions for young people. You don’t need any experience of the workshop content yourself, but you will need to have some patience, and enjoy helping young people.
""",
    },
    {
        "name": "NOC Helper",
        "description": "Plug/Unplug DKs",
        # "role_notes": "Requires training & the DK Key.",
        # "requires_training": True,
        "full_description_md": """

""",
    },
    {
        "name": "Bar",
        "description": "Help run the bar. Serve drinks, take payment, keep it clean.",
        "role_notes": "Requires training, over 18s only.",
        "over_18_only": True,
        "requires_training": True,
        "full_description_md": """
You will not be able to sign up for this shift unless:

* You are over 18
* You have completed [this short online course](https://www.emfcamp.org/volunteer/bar-training)

## What you'll be doing

The bar team will be running two bars at EMF 2018, the main bar will be to the north of the site near Stage B, the 2nd bar will be in the Null Sector.

There are loads of benefits to volunteering on the EMF bar:

1. Serving your fellow festival-goers and working with a team of volunteers in the fast paced environment behind the bar is a great way to meet new people and socialise, it doesn’t really feel like work at all.
2. It’s a great way to learn how to work on a bar and get experience if you ever fancy a career change! We’ll teach you everything you need to know on the job, it’s really easy once you get started.
3. Usually the bar shifts are pretty short so they’re easy to fit in with other things you might want to do, you can even pop back later and help out if there’s a big queue, and help get your friends served quicker.

Working behind the bar is loads of fun, its not hard work, and without lovely people like you we'd have no bar, so volunteer for a shift or two, or event three!
""",
    },
    {
        "name": "Cybar",
        "description": "Help run the Cybar. Serve drinks, take payment, keep it clean.",
        "role_notes": "Requires training, over 18s only.",
        "over_18_only": True,
        "requires_training": True,
        "full_description_md": """
You will not be able to sign up for this shift unless:

* You are over 18
* You have completed [this short online course](https://www.emfcamp.org/volunteer/bar-training)

## What you'll be doing

The bar team will be running two bars at EMF 2018, the main bar will be to the north of the site near Stage B, the 2nd bar will be in the Null Sector.

There are loads of benefits to volunteering on the EMF bar:

1. Serving your fellow festival-goers and working with a team of volunteers in the fast paced environment behind the bar is a great way to meet new people and socialise, it doesn’t really feel like work at all.
2. It’s a great way to learn how to work on a bar and get experience if you ever fancy a career change! We’ll teach you everything you need to know on the job, it’s really easy once you get started.
3. Usually the bar shifts are pretty short so they’re easy to fit in with other things you might want to do, you can even pop back later and help out if there’s a big queue, and help get your friends served quicker.

Working behind the bar is loads of fun, its not hard work, and without lovely people like you we'd have no bar, so volunteer for a shift or two, or event three!
""",
    },
    {
        "name": "Volunteer Manager",
        "description": "Run the volunteer system.",
        "full_description_md": """
Help people sign up for volunteering. Make sure they know where to go. Run admin on the volunteer system.

Youwill need training on the various systems we ahve for managing and communicating with volunteers for this role. Please email volunteer@emfcamp.org to arrange a time we can do that (or drop by volunteer desk at the event)."
        """,
        "role_notes": "Must be trained.",
        "over_18_only": True,
        "requires_training": True,
    },
    {
        "name": "Music: Sound Engineer",
        "description": "Run the sound for live music",
        "full_description_md": """
EMF’s Music Stage is looking for Volunteers to help run our Live Music stage!

Music stage is open 7:30-2am Friday and Saturday and closing 11pm Sunday. There will be a training session before the music starts each evening.

All range of skills considered but for Live mixing a solid foundation of live sound is required.
""",
    },
    {
        "name": "Music: Lighting Operator",
        "description": "Control the lighting for live music",
        "full_description_md": """
EMF’s Music Stage is looking for Volunteers to help run our Live Music stage!

Music stage is open 7:30-2am Friday and Saturday and closing 11pm Sunday. There will be a training session before the music starts each evening.

We are looking for people with experience of being a lighting OP or and LD. Can you program a desk or just jam with us live?

All range of skills considered.
""",
    },
    {
        "name": "Music: Stage Hand",
        "description": "Mosing stuff around for live music",
        "full_description_md": """
EMF’s Music Stage is looking for Volunteers to help run our Live Music stage!

We are looking for people to help get acts to the stage, help during changeovers and move the odd bit of kit.

Music stage is open 7:30-2am Friday and Saturday and closing 11pm Sunday.

All range of skills considered.
""",
    },
    {
        "name": "Shop Helper",
        "description": "Look after the camp shop",
        "full_description_md": """
Look after the camp shop, taking payment for anything that people buy, flagging to the team when items are going out of stock, and keeping the place clean and tidy.
""",
    },
    {
        "name": "Tent Team Helper",
        "description": "Help others put up their tent and get settled in.",
        "full_description_md": """
Tent team is looking for people to help others put up their tents and get settled in.

They'll be primarily on call via DECT and roaming the site helping get folks set up.
""",
    },
    {
        "name": "Logistics Support",
        "description": "Help manage stuff moving onto and around site.",
        "full_description_md": """
As logistics support you'll join the team ensuring that equipment gets where it needs to be on time, receiving any deliveries to site, handling collections from the logistics tent, access to our secure storage, and keeping track of where our equipment is.
""",
    },
    {
        "name": "Support Team",
        "description": "Assisting the Accessibility and Conduct team.",
        "full_description_md": """
Helping ensure EMF remains a great place for everyone. We're looking for  volunteers to assist in:

* Attending talks and workshops to ensure everyone remembers about the code of conduct
* Dealing impartially with potential violations of the code of conduct
* Being visible during the event to support people
* Mediation and de-escalation when necessary
* Helping people get around site safely
* Checking in on people who need/want assistance

Apart from being in talks/workshops, this is a roving role.

Contact us via HQ, or on the DECTs!

Training is available before shifts, or 'around lunch time'. We ask that people on-shift are able to work with challenging situations, aware of their own limits/comfort zones, able to tap-out, recuse where conflicts of interest may be present. Volunteers for this role should not be intoxicated, or otherwise have their judgements clouded.
""",
    },
    {
        "name": "Runner",
        "description": "Picking up whatever tasks need done.",
        "full_description_md": """
Picking up whatever tasks don't need someone covering them all the time.

Will include:

* Fetching/moving stuff
* Marshalling vehicles moving around site
* Periodic checks of the arcade, lounge etc.
""",
    },
]
from datetime import datetime, timedelta
event_days = {
    "wed": 0, "weds":0,
    "thur": 1, "thurs": 1,
    "fri": 2,
    "sat": 3,
    "sun": 4,
    "mon": 5
    }
def edt(day, time):
    fmt = "%Y-%m-%d"
    if isinstance(day, str):
        day = event_days[day.lower()]
    day0 = datetime.strptime("2024-05-29", fmt)
    #TODO: get date from config for that ^^
    delta = timedelta(days=day)
    return f"{(day0+delta).strftime(fmt)} {time}"
shift_list = {
    "Badge Helper": {
        "Badge Tent": [
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "16:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "16:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "16:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Car Parking": {
        "Car Park": [
            {
                "first": edt("thur", "08:00:00"),
                "final": edt("thur", "20:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("fri", "08:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "16:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "16:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "08:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 1,
                "max": 1,
            },
        ]
    },
    "Entrance Steward": {
        "Entrance Tent": [
            {
                "first": edt("thur", "11:00:00"),
                "final": edt("thur", "23:00:00"),
                "min": 2,
                "max": 4,
            },
            {
                "first": edt("fri", "07:00:00"),
                "final": edt("fri", "23:00:00"),
                "min": 2,
                "max": 4,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "08:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 1,
                "max": 2,
            },
        ],
        "Vehicle Gate Y": [
            {
                "first": edt("thur", "11:00:00"),
                "final": edt("thur", "23:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "15:00:00"),
                "final": edt("sun", "23:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("mon", "08:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
    },
    "Green Room Runner": {
        "Green Room": [
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri",  "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "18:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Content Team": {
      "Green Room": [
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "21:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "21:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "18:00:00"),
                "min": 1,
                "max": 1,
            },
        ]
    },
    "Info Desk": {
        "Info/Volunteer Tent": [
            {
                "first": edt("thur", "10:00:00"),
                "final": edt("thur", "20:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("mon", "10:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Volunteer Manager": {
        "Info/Volunteer Tent": [
            {
                "first": edt("thur", "09:00:00"),
                "final": edt("thur", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("mon", "10:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Youth Workshop Helper": {
        "Youth Workshop": [
            {
                "first": edt("fri", "11:00:00"),
                "final": edt("fri", "17:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "17:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 2,
                "base_duration": 90,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "15:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "15:00:00"),
                "final": edt("sat", "19:30:00"),
                "min": 1,
                "max": 2,
                "base_duration": 90,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "19:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Bar": {
        "Bar": [
            {
                "first": edt("thur", "11:00:00"),
                "final": edt("fri", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("thur", "12:00:00"),
                "final": edt("fri", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("fri", "11:00:00"),
                "final": edt("sat", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("sat", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("sat", "11:00:00"),
                "final": edt("sun", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("sat", "12:00:00"),
                "final": edt("sun", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("sun", "11:00:00"),
                "final": edt("mon", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("sun", "12:00:00"),
                "final": edt("mon", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
        ]
    },
    "Cybar": {
        "Cybar": [
            {
                "first": edt("fri", "20:00:00"),
                "final": edt("fri", "22:00:00"),
                "min": 1,
                "max": 2,
                "changeover": 0,
            },
            {
                "first": edt("fri", "22:00:00"),
                "final": edt("sat", "01:00:00"),
                "min": 1,
                "max": 2,
                "base_duration": 90,
            },
            {
                "first": edt("sat", "13:00:00"),
                "final": edt("sun", "01:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "13:00:00"),
                "final": edt("mon", "01:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "NOC Helper": {
        "NOC": [
            {
                "first": edt("thur", "10:00:00"),
                "final": edt("thur", "20:00:00"),
                "min": 1,
                "max": 2,
                # "base_duration": 90,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 2,
                # "base_duration": 90,
            },
            {
                "first": edt("sun", "12:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 2,
                # "base_duration": 90,
            },
            {
                "first": edt("mon", "08:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 1,
                "max": 2,
                # "base_duration": 90,
            },
        ]
    },
    "Herald": {
        "Stage A": [
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "21:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "21:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "18:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage B": [
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "21:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "21:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "18:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage C": [
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "21:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "21:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "18:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
    },
    "Stage: Audio/Visual": {
        "Stage A": [
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage B": [
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage C": [
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
    },
    "Stage: Camera Operator": {
        "Stage A": [
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage B": [
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage C": [
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
    },
    "Stage: Vision Mixer": {
        "Stage A": [
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage B": [
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage C": [
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
    },
    "Kitchen Helper": {
        "Volunteer Kitchen": [
            {
                "first": edt("thur", "06:00:00"),
                "final": edt("thur", "22:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("fri", "06:00:00"),
                "final": edt("fri", "22:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("sat", "06:00:00"),
                "final": edt("sat", "22:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("sun", "06:00:00"),
                "final": edt("sun", "22:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("mon", "06:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("thur", "09:00:00"),
                "final": edt("thur", "11:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("thur", "13:00:00"),
                "final": edt("thur", "15:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("thur", "19:30:00"),
                "final": edt("thur", "21:30:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "11:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("fri", "13:00:00"),
                "final": edt("fri", "15:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("fri", "19:30:00"),
                "final": edt("fri", "21:30:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "11:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("sat", "13:00:00"),
                "final": edt("sat", "15:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("sat", "19:30:00"),
                "final": edt("sat", "21:30:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "11:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("sun", "13:00:00"),
                "final": edt("sun", "15:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("sun", "19:30:00"),
                "final": edt("sun", "21:30:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("mon", "09:00:00"),
                "final": edt("mon", "11:00:00"),
                "min": 2,
                "max": 2,
            },
        ]
    },
    "Runner": {
        "Info/Volunteer Tent": [
            {
                "first": edt("thur", "09:30:00"),
                "final": edt("thur", "23:30:00"),
                "min": 3,
                "max": 6,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "20:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("mon", "08:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 3,
                "max": 6,
            },
        ]
    },
    "Logistics Support": {
        "Logistics Tent": [
            {
                "first": edt("thur", "11:00:00"),
                "final": edt("thur", "17:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "17:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "17:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "17:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("mon", "09:00:00"),
                "final": edt("mon", "11:00:00"),
                "min": 1,
                "max": 3,
                # "base_duration": 90,
            },
            {
                "first": edt("mon", "11:00:00"),
                "final": edt("mon", "12:30:00"),
                "min": 1,
                "max": 3,
                "base_duration": 90,
            },
        ]
    },
    "Tent Team Helper": {
        "N/A": [
            {
                "first": edt("thur", "17:00:00"),
                "final": edt("thur", "19:00:00"),
                "min": 1,
                "max": 4,
            },
            {
                "first": edt("fri", "17:00:00"),
                "final": edt("fri", "19:00:00"),
                "min": 1,
                "max": 4,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "12:30:00"),
                "min": 1,
                "max": 4,
            },
        ]
    },
    "Shop Helper": {
        "Shop": [
            {
                "first": edt("thur", "10:00:00"),
                "final": edt("thur", "18:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "18:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "18:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "18:00:00"),
                "min": 2,
                "max": 3,
            },
        ]
    },
    "Music: Stage Hand": {
        "Stage B": [
            {
                "first": edt("thur", "19:00:00"),
                "final": edt("thur", "21:00:00"),
                "min": 2,
                "max": 4,
            },
            {
                "first": edt("thur", "21:00:00"),
                "final": edt("thur", "22:30:00"),
                "min": 2,
                "max": 4,
                "base_duration": 90,
            },
            {
                "first": edt("fri", "18:00:00"),
                "final": edt("sat", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "18:00:00"),
                "final": edt("sun", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "18:00:00"),
                "final": edt("mon", "00:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Music: Lighting Operator": {
        "Stage B": [
            {
                "first": edt("thur", "19:00:00"),
                "final": edt("thur", "21:00:00"),
                "min": 2,
                "max": 4,
            },
            {
                "first": edt("thur", "21:00:00"),
                "final": edt("thur", "22:30:00"),
                "min": 2,
                "max": 4,
                "base_duration": 90,
            },
            {
                "first": edt("fri", "18:00:00"),
                "final": edt("sat", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "18:00:00"),
                "final": edt("sun", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "18:00:00"),
                "final": edt("mon", "00:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Music: Sound Engineer": {
        "Stage B": [
            {
                "first": edt("thur", "19:00:00"),
                "final": edt("thur", "21:00:00"),
                "min": 2,
                "max": 4,
            },
            {
                "first": edt("thur", "21:00:00"),
                "final": edt("thur", "22:30:00"),
                "min": 2,
                "max": 4,
                "base_duration": 90,
            },
            {
                "first": edt("fri", "18:00:00"),
                "final": edt("sat", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "18:00:00"),
                "final": edt("sun", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "18:00:00"),
                "final": edt("mon", "00:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Support Team": {
        "N/A": [
            {
                "first": edt("thur", "10:00:00"),
                "final": edt("thur", "22:00:00"),
                "min": 2,
                "max": 6,
            },
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "19:00:00"),
                "min": 2,
                "max": 6,
            },
            {
                "first": edt("fri", "19:00:00"),
                "final": edt("fri", "22:00:00"),
                "min": 2,
                "max": 6,
                "base_duration": 90,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "19:00:00"),
                "min": 2,
                "max": 6,
            },
            {
                "first": edt("sat", "19:00:00"),
                "final": edt("sat", "22:00:00"),
                "min": 2,
                "max": 6,
                "base_duration": 90,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "19:00:00"),
                "min": 2,
                "max": 6,
            },
            {
                "first": edt("sun", "19:00:00"),
                "final": edt("sun", "22:00:00"),
                "min": 2,
                "max": 6,
                "base_duration": 90,
            },
            {
                "first": edt("mon", "09:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 2,
                "max": 6,
                "base_duration": 90,
            },
        ]
    },
}

if __name__=="__main__":
    import pprint
    pprint.pp(shift_list)
