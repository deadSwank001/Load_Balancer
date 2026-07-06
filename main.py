#region imports
from AlgorithmImports import *
#endregion


class SymbolData:
    """Holds per-symbol consolidator and indicator state."""

    def __init__(self, symbol: Symbol, algorithm: QCAlgorithm) -> None:
        self.symbol = symbol
        # 15-minute trade bar consolidator
        self.consolidator = TradeBarConsolidator(15)
        algorithm.subscription_manager.add_consolidator(symbol, self.consolidator)
        # Slow EMA on 15-min bars (200 periods = 50 hours) for trend filter
        self.ema = ExponentialMovingAverage(200)
        algorithm.register_indicator(symbol, self.ema, self.consolidator)
        self.prev_above_ema = False
        self.last_trade_date = None


class SimpleCryptoBot(QCAlgorithm):

    def initialize(self) -> None:
        self.set_start_date(2023, 1, 1)
        # Total starting capital: $90.90 (ETH) + $65.70 (SOL) = $156.60
        self.set_cash("USD", 156.60)
        self.set_brokerage_model(BrokerageName.KRAKEN, AccountType.CASH)

        self._eth_symbol = self.add_crypto("ETHUSD", Resolution.MINUTE).symbol
        self._sol_symbol = self.add_crypto("SOLUSD", Resolution.MINUTE).symbol

        # Max dollar amount per trade
        self._max_trade = 45.0
        self._initialized = False

        # Target initial allocations as portfolio weight fractions
        self._initial_weights = {
            self._eth_symbol: 90.90 / 156.60,
            self._sol_symbol: 65.70 / 156.60,
        }

        # Minimum days between trades per symbol
        self._cooldown_days = 7

        # Build per-symbol data objects
        self._symbol_data = {}
        for symbol in [self._eth_symbol, self._sol_symbol]:
            self._symbol_data[symbol] = SymbolData(symbol, self)

        # Keep a 5% cash buffer so fees don't block orders
        self.settings.free_portfolio_value_percentage = 0.05

        # Single daily check at 6:00 AM during the 5-9 AM window
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(6, 0),
            self._trade,
        )

    def _set_initial_positions(self) -> None:
        """Set target portfolio weights on first available prices."""
        targets = [
            PortfolioTarget(symbol, weight)
            for symbol, weight in self._initial_weights.items()
        ]
        self.set_holdings(targets)
        self._initialized = True
        self.log("Initial positions set: ~$90.90 ETH, ~$65.70 SOL")

    def _trade(self) -> None:
        """Entry point for scheduled daily trading check at 6 AM."""
        if not self._initialized:
            eth_price = self.securities[self._eth_symbol].price
            sol_price = self.securities[self._sol_symbol].price
            if eth_price > 0 and sol_price > 0:
                self._set_initial_positions()
            return

        today = self.time.date()

        for symbol, sd in self._symbol_data.items():
            if not sd.ema.is_ready:
                continue

            # Cooldown check — skip if we traded this symbol recently
            if sd.last_trade_date is not None:
                days_since = (today - sd.last_trade_date).days
                if days_since < self._cooldown_days:
                    continue

            price = self.securities[symbol].price
            if price <= 0:
                continue

            ema_val = sd.ema.current.value
            currently_above = price > ema_val

            # Only act on actual crossover: price crossing above EMA
            if currently_above and not sd.prev_above_ema:
                cash = self.portfolio.cash
                if cash > 1.0:
                    qty = min(self._max_trade, cash) / price
                    if qty > 0:
                        self.market_order(symbol, qty)
                        sd.last_trade_date = today
                        self.log(f"BUY {symbol.value}: {qty:.6f} @ ${price:.2f}")

            # Only act on actual crossover: price crossing below EMA
            elif not currently_above and sd.prev_above_ema:
                holdings = self.portfolio[symbol].quantity
                if holdings > 0:
                    qty = min(holdings, self._max_trade / price)
                    self.market_order(symbol, -qty)
                    sd.last_trade_date = today
                    self.log(f"SELL {symbol.value}: {qty:.6f} @ ${price:.2f}")

            sd.prev_above_ema = currently_above

    def on_data(self, data: Slice) -> None:
        """Initialize positions as soon as price data is available."""
        if not self._initialized:
            eth_price = self.securities[self._eth_symbol].price
            sol_price = self.securities[self._sol_symbol].price
            if eth_price > 0 and sol_price > 0:
                self._set_initial_positions()
