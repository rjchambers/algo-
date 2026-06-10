from hl_trader.logging_setup import REDACTED, redact_secrets


def test_secret_named_fields_redacted():
    event = {"event": "order", "api_key": "supersecret", "signature": "deadbeef"}
    out = redact_secrets(None, "info", event)
    assert out["api_key"] == REDACTED
    assert out["signature"] == REDACTED
    assert out["event"] == "order"


def test_key_shaped_strings_redacted_in_values():
    key = "0x" + "ab" * 32
    event = {"event": f"loaded wallet {key} ok"}
    out = redact_secrets(None, "info", event)
    assert key not in out["event"]
    assert REDACTED in out["event"]


def test_nested_structures_redacted():
    key = "0x" + "cd" * 32
    event = {"payload": {"secret": "x", "data": [key, "fine"]}}
    out = redact_secrets(None, "info", event)
    assert out["payload"]["secret"] == REDACTED
    assert out["payload"]["data"][0] == REDACTED
    assert out["payload"]["data"][1] == "fine"
