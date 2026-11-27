"""
Portfolio allocation maths shared by the charter and reporter agents.

Values are in BASE_CURRENCY: the planner stores every price already converted
(see backend/planner/prices.py). Percentages are worked out here in Python so the
agents copy them instead of estimating them.
"""

from typing import Any, Dict, List

# The dashboard sets targets for North America and Australia (stored as "oceania"),
# so those are the two regions shown. Anything else (global, europe, asia, ...) is "Other".
REGION_GROUPS = {"north_america": "North America", "oceania": "Australia"}
OTHER_REGIONS = "Other"


def region_group(region: str) -> str:
    return REGION_GROUPS.get(region, OTHER_REGIONS)


def display_name(key: str) -> str:
    return key.replace("_", " ").title()


def _price(instrument: Dict[str, Any]) -> float:
    price = instrument.get("current_price")
    return float(price) if price not in (None, "") else 0.0


def compute_allocations(portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Aggregate a portfolio ({"accounts": [{"cash_balance", "positions": [{"symbol", "quantity",
    "instrument"}]}]}) into values and percentages.

    Asset classes and regions include cash (regions as a "Cash" row), so both add up to
    the total value shown on the dashboard. Sectors cover invested positions only.
    Positions with no price or no allocation data are listed in "unpriced" or
    "unclassified" instead of being guessed.
    """
    cash = 0.0
    positions: Dict[str, float] = {}
    accounts: Dict[str, float] = {}
    asset_classes: Dict[str, float] = {}
    regions: Dict[str, float] = {}
    sectors: Dict[str, float] = {}
    unpriced: List[str] = []
    unclassified: List[str] = []

    for account in portfolio_data.get("accounts", []):
        account_cash = float(account.get("cash_balance") or 0)
        cash += account_cash
        account_value = account_cash

        for position in account.get("positions", []):
            symbol = position.get("symbol")
            instrument = position.get("instrument") or {}
            price = _price(instrument)
            if price <= 0:
                unpriced.append(symbol)
                continue
            value = float(position.get("quantity") or 0) * price
            positions[symbol] = positions.get(symbol, 0.0) + value
            account_value += value

            allocations = (
                instrument.get("allocation_asset_class") or {},
                instrument.get("allocation_regions") or {},
                instrument.get("allocation_sectors") or {},
            )
            if not all(allocations):
                unclassified.append(symbol)
            asset_alloc, region_alloc, sector_alloc = allocations
            for key, pct in asset_alloc.items():
                asset_classes[key] = asset_classes.get(key, 0.0) + value * float(pct) / 100
            for key, pct in region_alloc.items():
                group = region_group(key)
                regions[group] = regions.get(group, 0.0) + value * float(pct) / 100
            for key, pct in sector_alloc.items():
                sectors[key] = sectors.get(key, 0.0) + value * float(pct) / 100

        name = account.get("name") or account.get("account_name") or "Unknown"
        accounts[name] = accounts.get(name, 0.0) + account_value

    if cash > 0:
        asset_classes["cash"] = asset_classes.get("cash", 0.0) + cash
        regions["Cash"] = regions.get("Cash", 0.0) + cash

    invested = sum(positions.values())
    total = invested + cash

    def table(values: Dict[str, float], whole: float, names: bool = True) -> List[Dict[str, Any]]:
        rows = [
            {
                "name": display_name(k) if names else k,
                "value": round(v, 2),
                "percent": round(v / whole * 100, 1) if whole > 0 else 0.0,
            }
            for k, v in values.items()
            if v > 0
        ]
        return sorted(rows, key=lambda r: r["value"], reverse=True)

    return {
        "total_value": round(total, 2),
        "invested_value": round(invested, 2),
        "cash": round(cash, 2),
        "asset_classes": table(asset_classes, total),
        "regions": table(regions, total, names=False),
        "sectors": table(sectors, invested),
        "accounts": table(accounts, total, names=False),
        "positions": table(positions, total, names=False),
        "unpriced": sorted(set(unpriced)),
        "unclassified": sorted(set(unclassified)),
    }


def format_allocations(alloc: Dict[str, Any], currency: str = "USD") -> str:
    """Plain-text summary for an agent prompt. All numbers are exact; agents should copy them."""

    money = f"{currency}$"

    def rows(items: List[Dict[str, Any]], limit: int = 0) -> List[str]:
        items = items[:limit] if limit else items
        return [f"  {r['name']}: {money}{r['value']:,.2f} ({r['percent']:.1f}%)" for r in items]

    lines = [
        f"All values are in {currency}, written as {money}1,234.56.",
        f"Total Value: {money}{alloc['total_value']:,.2f}",
        f"Invested (excluding cash): {money}{alloc['invested_value']:,.2f}",
        f"Cash: {money}{alloc['cash']:,.2f}",
        "",
        "Accounts (% of total value):",
        *rows(alloc["accounts"]),
        "",
        "Top Holdings (% of total value):",
        *rows(alloc["positions"], 10),
        "",
        "Asset Classes (% of total value, including cash):",
        *rows(alloc["asset_classes"]),
        "",
        "Geographic Regions (% of total value; North America, Australia and Cash):",
        *rows(alloc["regions"]),
        "",
        "Sectors (% of invested value):",
        *rows(alloc["sectors"]),
    ]
    if alloc["unpriced"]:
        lines += ["", f"No price available (left out): {', '.join(alloc['unpriced'])}"]
    if alloc["unclassified"]:
        lines += ["", f"Missing allocation data: {', '.join(alloc['unclassified'])}"]
    return "\n".join(lines)
