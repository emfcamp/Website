import pytest

from apps.payments.wise import wise_business_profile, wise_retrieve_accounts
from models.payment import BankTransaction


@pytest.fixture(scope="module")
def vcr_config():
    return {
        # Replace the Authorization request header with "DUMMY" in cassettes
        "filter_headers": [("authorization", "DUMMY")],
    }


@pytest.mark.vcr()
def test_wise_account_retrieval(app):
    profile_id = wise_business_profile()
    accounts = list(wise_retrieve_accounts(profile_id=profile_id))

    # we merge Wise's local and international details for our GBP account into a single record
    assert len(accounts) == 2

    account = accounts[1]
    assert account.currency == "GBP"
    assert account.institution == "TransferWise"
    assert account.sort_code.startswith("231")
    assert account.acct_id.startswith("1000")
    assert account.iban.startswith("GB77 TRWI")
    assert account.swift.startswith("TRWI")

    account = accounts[0]
    assert account.currency == "EUR"
    assert account.institution == "TransferWise Europe SA"
    assert account.sort_code is None
    assert account.acct_id is None
    assert account.iban.startswith("BE29 9670")
    assert account.swift.startswith("TRWI")


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
