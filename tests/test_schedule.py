from datetime import datetime

import pytest

from apps.schedule import schedule_frab_xml


@pytest.mark.parametrize('start_time, end_time, expected', [
    ('2024-01-01 00:00:00', '2024-01-01 00:01:00', '0:01'),
    ('2024-01-01 00:00:00', '2024-01-01 00:01:45', '0:01'),
    ('2024-01-01 00:00:00', '2024-01-01 01:00:00', '1:00'),
    ('2024-01-01 00:00:00', '2024-01-01 12:00:00', '12:00'),
    ('2024-01-01 00:00:00', '2024-01-02 00:00:00', '1:00:00'),
    ('2024-01-01 00:00:00', '2024-01-02 12:34:00', '1:12:34'),
])
def test_get_duration(start_time, end_time, expected):
    fmt = '%Y-%m-%d %H:%M:%S'
    start_time = datetime.strptime(start_time, fmt)
    end_time = datetime.strptime(end_time, fmt)
    assert schedule_frab_xml.get_duration(start_time, end_time) == expected
