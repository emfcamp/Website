from ..event_date import edt

def day(d):
    return {
        "first": edt(d, "07:30:00"),
        "final": edt(d, "22:30:00"),
        "min": 6,
        "max": 8,
        "base_duration": 180,
        "changeover": 30
    }

def lunch(d):
    return {
        "first": edt(d, "12:00:00"),
        "final": edt(d, "15:00:00"),
        "min": 2,
        "max": 2,
        "base_duration": 180,
        "changeover": 0
    }

def dinner(d):
    return {
        "first": edt(d, "17:30:00"),
        "final": edt(d, "20:30:00"),
        "min": 2,
        "max": 2,
        "base_duration": 180,
        "changeover": 0
    }
    
days = ["wed", "thur", "fri", "sat", "sun", "mon"]

kitchen_shifts = {
    "Kitchen Assistant": {
        "Volunteer Kitchen":
        [day(d) for d in days] +
        [lunch(d) for d in days] +
        [dinner(d) for d in days]
    }
}
