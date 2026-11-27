"""
Share prices from Yahoo Finance via yfinance.

Replaces the Massive (formerly polygon.io) client, which does not cover ASX listings.
- ASX tickers need the ".AX" suffix, e.g. "BHP.AX", "VHY.AX". US tickers are used as-is ("SPY").
- Yahoo quotes each listing in its own currency (".AX" prices are in AUD). The app adds
  positions together, so every price is converted to BASE_CURRENCY (default AUD) before
  it is returned. Set BASE_CURRENCY=USD in .env to value everything in USD instead.
- No API key is needed, but Yahoo rate-limits, so prices are fetched in one batched call.
"""

import logging
import os
from functools import lru_cache
from typing import Iterable

import yfinance as yf

logger = logging.getLogger()

BASE_CURRENCY = os.getenv("BASE_CURRENCY", "AUD").strip().upper()

# Yahoo quotes some listings in minor units (pence, cents); value is (currency, divisor)
_MINOR_UNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}


def _guess_currency(ticker: str) -> str:
    """Fallback when Yahoo doesn't report a currency."""
    return "AUD" if ticker.endswith(".AX") else "USD"


@lru_cache(maxsize=None)
def _listing_currency(ticker: str) -> tuple[str, int]:
    """(ISO currency, divisor) that Yahoo quotes this ticker in."""
    try:
        currency = yf.Ticker(ticker).fast_info["currency"]
    except Exception as e:
        logger.warning(f"Prices: no currency from Yahoo for {ticker}, guessing: {e}")
        currency = None
    if not currency:
        return _guess_currency(ticker), 1
    return _MINOR_UNITS.get(currency, (currency.upper(), 1))


def _fx_rate(from_currency: str, to_currency: str) -> float:
    """Latest rate to multiply a from_currency amount by. 0.0 if Yahoo has none."""
    if from_currency == to_currency:
        return 1.0
    pair = f"{from_currency}{to_currency}=X"
    try:
        closes = yf.Ticker(pair).history(period="5d")["Close"].dropna()
        if not closes.empty:
            return float(closes.iloc[-1])
    except Exception as e:
        logger.warning(f"Prices: FX lookup failed for {pair}: {e}")
    return 0.0


def _to_base_currency(prices: dict[str, float]) -> dict[str, float]:
    """Convert {ticker: price in listing currency} to BASE_CURRENCY. Drops tickers with no FX rate."""
    rates: dict[str, float] = {}
    converted = {}
    for ticker, price in prices.items():
        currency, divisor = _listing_currency(ticker)
        if currency not in rates:
            rates[currency] = _fx_rate(currency, BASE_CURRENCY)
        rate = rates[currency]
        if rate <= 0:
            logger.warning(f"Prices: no {currency}->{BASE_CURRENCY} rate, skipping {ticker}")
            continue
        converted[ticker] = price / divisor * rate
        if currency != BASE_CURRENCY:
            logger.info(
                f"Prices: {ticker} {price / divisor:.2f} {currency} = "
                f"{converted[ticker]:.2f} {BASE_CURRENCY} (rate {rate:.4f})"
            )
    return converted

def _fast_info_price(ticker: str) -> float:
    """Single-ticker fallback. Uses fast_info['lastPrice'], which ETFs have (unlike info['currentPrice'])."""
    try:
        price = yf.Ticker(ticker).fast_info["lastPrice"]
        return float(price) if price and price == price else 0.0  # price == price filters NaN
    except Exception as e:
        logger.warning(f"Prices: fast_info lookup failed for {ticker}: {e}")
        return 0.0


def get_share_prices(symbols: Iterable[str]) -> dict[str, float]:
    """
    Fetch the latest price for each symbol in one batched yf.download call.

    Returns {symbol: price} using the symbols exactly as passed in. Symbols with no
    price available are left out, so callers can keep the existing stored price.
    """
    # Yahoo tickers are upper case; remember the caller's spelling to map back.
    wanted = {}
    for symbol in symbols:
        if symbol and symbol.strip():
            wanted.setdefault(symbol.strip().upper(), []).append(symbol)
    if not wanted:
        return {}

    tickers = sorted(wanted)
    latest: dict[str, float] = {}

    try:
        data = yf.download(
            tickers,
            period="5d",  # a few days back covers weekends and public holidays
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
        if data is not None and not data.empty:
            closes = data["Close"]
            if not hasattr(closes, "columns"):  # older yfinance returns a Series for one ticker
                closes = closes.to_frame(tickers[0])
            for ticker in tickers:
                if ticker in closes.columns:
                    series = closes[ticker].dropna()
                    if not series.empty:
                        latest[ticker] = float(series.iloc[-1])
    except Exception as e:
        logger.warning(f"Prices: batched yf.download failed, falling back per ticker: {e}")

    for ticker in tickers:
        if ticker not in latest:
            price = _fast_info_price(ticker)
            if price > 0:
                latest[ticker] = price

    latest = _to_base_currency(latest)

    return {
        original: price
        for ticker, price in latest.items()
        for original in wanted[ticker]
    }


def get_share_price(symbol: str) -> float:
    """Latest price for one symbol in BASE_CURRENCY, or 0.0 if Yahoo has none."""
    return get_share_prices([symbol]).get(symbol, 0.0)
