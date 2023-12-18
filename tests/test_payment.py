import pytest

from models.payment import BankTransaction


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("M87X CJ3Q", "M87X CJ3Q"),
        ("RF91 M87X CJ3Q", "M87X CJ3Q"),
        ("RF52RF23MHBY", "RF23MHBY"),
        ("RF23MHBY", "RF23MHBY"),
    ],
)
def test_trim_iso11649_header(ref, expected):
    assert BankTransaction._trim_iso11649_header(ref) == expected
