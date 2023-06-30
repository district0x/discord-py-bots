import random
from datetime import datetime, timedelta


def mention(user_id):
    return f"<@{user_id}>"


def format_datetime(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def truncate_string(text, max_length):
    if len(text) <= max_length:
        return text
    else:
        return text[:max_length - 3] + "..."


format_time_remaining_units = [
    {'name': 'second', 'limit': 60, 'in_seconds': 1},
    {'name': 'minute', 'limit': 60 * 60, 'in_seconds': 60},
    {'name': 'hour', 'limit': 24 * 60 * 60, 'in_seconds': 60 * 60},
    {'name': 'day', 'limit': 7 * 24 * 60 * 60, 'in_seconds': 24 * 60 * 60},
    {'name': 'week', 'limit': 30.44 * 24 * 60 * 60, 'in_seconds': 7 * 24 * 60 * 60},
    {'name': 'month', 'limit': 365.24 * 24 * 60 * 60, 'in_seconds': 30.44 * 24 * 60 * 60},
    {'name': 'year', 'limit': None, 'in_seconds': 365.24 * 24 * 60 * 60}
]


def format_time_remaining(to_time, from_time=None):
    if from_time is None:
        from_time = datetime.now()

    diff = (to_time - from_time).total_seconds()

    if diff < 0:
        return "Time has already passed"
    elif diff < 5:
        return "in a few moments"
    else:
        for unit in format_time_remaining_units:
            if unit['limit'] is None or diff < unit['limit']:
                diff = int(diff // unit['in_seconds'])
                return f"in {diff} {unit['name']}{'s' if diff > 1 else ''}"


def with_probability(percentage):
    rand_num = random.randint(0, 1000)
    return rand_num <= percentage
