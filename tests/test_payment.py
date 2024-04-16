import pytest

from models.payment import BankTransaction


@pytest.mark.parametrize(
    "payee, bankref",
    [
        ("M87X CJ3Q", "M87XCJ3Q"),
        ("m87x Cj3q", "M87XCJ3Q"),
        ("prefix*M87X CJ3Q*suffix", "M87XCJ3Q"),
        ("RF91 M87X CJ3Q", "M87XCJ3Q"),
        ("RF91M87XCJ3Q", "M87XCJ3Q"),
        ("name value RF52RF23MHBY type value", "RF23MHBY"),
        ("prefix*RF52RF23MHBY*suffix", "RF23MHBY"),
        ("RF52RF23MHBY/20250102090807GB33BUKB20201555555555", "RF23MHBY"),
        ("RF52RF23MHBY", "RF23MHBY"),
        ("RF33*RF52RF23MHBY*RF33", "RF23MHBY"),
        ("RF23MHBY", "RF23MHBY"),
        ("RF33*RF23MHBY*RF33", "RF23MHBY"),
    ],
)
def test_bankref_recognition(payee, bankref):
    transaction = BankTransaction(
        account_id=None,
        amount=0,
        payee=payee,
        posted=None,
        type=None,
    )
    assert bankref in transaction._recognized_bankrefs
