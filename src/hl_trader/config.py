"""Typed settings loaded from environment / .env.

Safety model:
- Defaults to testnet. Mainnet must be selected explicitly.
- Only an AGENT wallet key is ever accepted (agent wallets cannot withdraw).
  We cannot cryptographically prove a key is an agent key from the key alone,
  so the variable is named to make intent unambiguous and the README documents
  the rule: the master/withdrawal key must never leave the Hyperliquid UI.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"
MAINNET_API_URL = "https://api.hyperliquid.xyz"
TESTNET_WS_URL = "wss://api.hyperliquid-testnet.xyz/ws"
MAINNET_WS_URL = "wss://api.hyperliquid.xyz/ws"


class Network(StrEnum):
    TESTNET = "testnet"
    MAINNET = "mainnet"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HL_TRADER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    network: Network = Network.TESTNET
    agent_private_key: str = ""
    account_address: str = ""
    data_cache_dir: Path = Path("data_cache")
    log_level: str = "INFO"
    log_dir: Path = Path("logs")

    @field_validator("agent_private_key")
    @classmethod
    def _validate_key_shape(cls, v: str) -> str:
        if v and not (v.startswith("0x") and len(v) == 66):
            raise ValueError(
                "HL_TRADER_AGENT_PRIVATE_KEY must be a 0x-prefixed 32-byte hex key "
                "(an agent wallet key — never your master key)."
            )
        return v

    @property
    def api_url(self) -> str:
        return MAINNET_API_URL if self.network is Network.MAINNET else TESTNET_API_URL

    @property
    def ws_url(self) -> str:
        return MAINNET_WS_URL if self.network is Network.MAINNET else TESTNET_WS_URL

    def require_trading_credentials(self) -> None:
        """Fail loudly if trading (Phase 3+) is attempted without credentials."""
        missing = []
        if not self.agent_private_key:
            missing.append("HL_TRADER_AGENT_PRIVATE_KEY")
        if not self.account_address:
            missing.append("HL_TRADER_ACCOUNT_ADDRESS")
        if missing:
            raise RuntimeError(
                f"Trading requires {', '.join(missing)} to be set. "
                "Create an AGENT wallet on Hyperliquid (cannot withdraw) and put its "
                "key in .env. Never use your master/withdrawal key."
            )


def load_settings(**overrides) -> Settings:
    return Settings(**overrides)
