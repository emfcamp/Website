import pytest

from models.payment import BankTransaction


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("M87X CJ3Q", "M87X CJ3Q"),
        ("prefix*M87X CJ3Q*suffix", "prefix*M87X CJ3Q*suffix"),
        ("RF91 M87X CJ3Q", "M87X CJ3Q"),
        ("RF91M87XCJ3Q", "M87XCJ3Q"),
        ("name value RF52RF23MHBY type value", "name value RF23MHBY type value"),
        ("prefix*RF52RF23MHBY*suffix", "prefix*RF23MHBY*suffix"),
        (
            "RF52RF23MHBY/20250102090807GB33BUKB20201555555555",
            "RF23MHBY/20250102090807GB33BUKB20201555555555",
        ),
        ("RF52RF23MHBY", "RF23MHBY"),
        ("RF33*RF52RF23MHBY*RF33", "RF33*RF23MHBY*RF33"),
        ("RF23MHBY", "RF23MHBY"),
        ("RF33*RF23MHBY*RF33", "RF33*RF23MHBY*RF33"),
    ],
)
def test_trim_iso11649_header(ref, expected):
    assert BankTransaction._trim_iso11649_header(ref) == expected
