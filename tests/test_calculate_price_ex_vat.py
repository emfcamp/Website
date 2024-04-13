# import pytest

from decimal import Decimal
from models.product import Price, PriceTier

def test_calculating_price_ex_vat():
    tier = PriceTier(name="Tier 1", vat_rate="0.2")
    price = Price(currency="EUR", price_int=1000, price_tier = tier)
    assert round(price.value_ex_vat,2) == Decimal("8.33")
    price.value_ex_vat = Decimal("8.33")
    assert price.value == Decimal("9.99")

    tier.vat_rate = "0"
    price.value = Decimal("10")
    assert price.value_ex_vat == Decimal("10")
    price.value_ex_vat = Decimal("5")
    assert price.value == Decimal("5")
