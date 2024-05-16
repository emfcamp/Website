from ..event_date import edt

def morning(d):
    return {
        "first": edt(d, "07:30:00"),
        "final": edt(d, "12:30:00"),
        "min": 6,
        "max": 8,
        "base_duration": 150,
        "changeover": 30
    }
def afternoon(d):
    return {
        "first": edt(d, "15:00:00"),
        "final": edt(d, "22:30:00"),
        "min": 6,
        "max": 8,
        "base_duration": 150,
        "changeover": 30
    }
def lunch(d):
    return {
        "first": edt(d, "12:00:00"),
        "final": edt(d, "15:00:00"),
        "min": 8,
        "max": 10,
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
        [morning(d) for d in days] +
        [afternoon(d) for d in days] +
        [lunch(d) for d in days] +
        [dinner(d) for d in days]
    }
}
