import pytest

from apps.payments.wise import wise_business_profile, wise_retrieve_accounts
from models.payment import BankTransaction


def vcr_response_scrubber(response):
    """Removes excessively-uniquely-identifying response headers"""
    SCRUB_HEADERS = {"set-cookie", "server", "alt-svc"}
    for header_name in tuple(response["headers"].keys()):
        header_name_lower, scrub = header_name.lower(), False
        if "cf" in header_name_lower.split("-"):
            scrub = True
        if header_name_lower.startswith("x-"):
            scrub = True
        if header_name_lower in SCRUB_HEADERS:
            scrub = True
        if scrub:
            del response["headers"][header_name]
    return response


@pytest.fixture(scope="module")
def vcr_config():
    return {
        # Replace the Authorization request header with "DUMMY" in cassettes
        "filter_headers": [("authorization", "DUMMY")],
        "before_record_response": vcr_response_scrubber,
    }


@pytest.mark.vcr()
def test_wise_account_retrieval(app):
    profile_id = wise_business_profile()
    accounts = list(wise_retrieve_accounts(profile_id=profile_id))

    # we merge Wise's local and international details for our GBP account into a single record
    assert len(accounts) == 2

    found = set()
    for account in accounts:
        if account.currency == "GBP":
            found.add(account.currency)
            assert account.institution == "TransferWise"
            assert account.sort_code.startswith("231")
            assert account.acct_id.startswith("1000")
            assert account.iban.startswith("GB77 TRWI")
            assert account.swift.startswith("TRWI")

        if account.currency == "EUR":
            found.add(account.currency)
            assert account.institution == "TransferWise Europe SA"
            assert account.sort_code is None
            assert account.acct_id is None
            assert account.iban.startswith("BE29 9670")
            assert account.swift.startswith("TRWI")

    assert found == {"GBP", "EUR"}


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
