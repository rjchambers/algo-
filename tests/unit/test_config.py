import pytest

from hl_trader.config import MAINNET_API_URL, TESTNET_API_URL, Network, load_settings


def test_defaults_to_testnet(monkeypatch):
    monkeypatch.delenv("HL_TRADER_NETWORK", raising=False)
    s = load_settings(_env_file=None)
    assert s.network is Network.TESTNET
    assert s.api_url == TESTNET_API_URL
    assert "testnet" in s.ws_url


def test_mainnet_must_be_explicit():
    s = load_settings(network="mainnet", _env_file=None)
    assert s.api_url == MAINNET_API_URL


def test_bad_key_shape_rejected():
    with pytest.raises(ValueError, match="agent wallet key"):
        load_settings(agent_private_key="not-a-key", _env_file=None)


def test_valid_key_shape_accepted():
    key = "0x" + "ab" * 32
    s = load_settings(agent_private_key=key, _env_file=None)
    assert s.agent_private_key == key


def test_trading_credentials_fail_loudly():
    s = load_settings(_env_file=None)
    with pytest.raises(RuntimeError, match="HL_TRADER_AGENT_PRIVATE_KEY"):
        s.require_trading_credentials()
