import pytest

from hl_trader.backtest.costs import CostParams, fill_price, funding_payment, taker_fee

PARAMS = CostParams(taker_fee_bps=4.5, maker_fee_bps=1.5, slippage_bps=2.0)


def test_buy_fills_above_reference_sell_below():
    assert fill_price(100.0, +1.0, PARAMS) == pytest.approx(100.02)
    assert fill_price(100.0, -1.0, PARAMS) == pytest.approx(99.98)
    assert fill_price(100.0, 0.0, PARAMS) == 100.0


def test_taker_fee_on_absolute_notional():
    assert taker_fee(10_000.0, PARAMS) == pytest.approx(4.5)
    assert taker_fee(-10_000.0, PARAMS) == pytest.approx(4.5)


def test_funding_long_pays_positive_rate():
    # 1 unit long at $100, +1bp hourly funding -> pays $0.01
    assert funding_payment(1.0, 100.0, 1e-4) == pytest.approx(-0.01)
    # short receives
    assert funding_payment(-1.0, 100.0, 1e-4) == pytest.approx(0.01)
    # negative funding: long receives
    assert funding_payment(1.0, 100.0, -1e-4) == pytest.approx(0.01)
