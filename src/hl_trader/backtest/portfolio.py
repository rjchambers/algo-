"""Single-asset account state: cash, position, average entry, realized PnL."""

from dataclasses import dataclass, field


@dataclass
class Trade:
    ts: object
    requested_units: float
    filled_units: float  # partial-fill aware interface; market fills are full in v1
    fill_price: float
    fee: float
    realized_pnl: float
    reason: str  # "rebalance" | "stop" | "kill_switch"


@dataclass
class Account:
    cash: float
    units: float = 0.0
    avg_entry: float = 0.0
    fees_paid: float = 0.0
    realized_pnl: float = 0.0
    trades: list[Trade] = field(default_factory=list)

    def equity(self, mark_price: float) -> float:
        return self.cash + self.units * mark_price

    def apply_fill(self, ts, trade_units: float, price: float, fee: float, reason: str) -> Trade:
        """Apply a fill, updating cash, position, average entry and realized PnL."""
        realized = 0.0
        new_units = self.units + trade_units

        if self.units != 0 and (trade_units * self.units) < 0:
            # Reducing or flipping: realize PnL on the closed portion.
            closed = min(abs(trade_units), abs(self.units))
            direction = 1.0 if self.units > 0 else -1.0
            realized = closed * (price - self.avg_entry) * direction
            if abs(trade_units) > abs(self.units):  # flipped through zero
                self.avg_entry = price
        elif trade_units != 0:
            # Adding to (or opening) a position: update weighted average entry.
            total = abs(self.units) + abs(trade_units)
            self.avg_entry = (abs(self.units) * self.avg_entry + abs(trade_units) * price) / total

        self.cash -= trade_units * price
        self.cash -= fee
        self.units = new_units
        if abs(self.units) < 1e-12:
            self.units = 0.0
            self.avg_entry = 0.0
        self.fees_paid += fee
        self.realized_pnl += realized

        trade = Trade(ts, trade_units, trade_units, price, fee, realized, reason)
        self.trades.append(trade)
        return trade
