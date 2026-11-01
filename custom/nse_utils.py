import calendar
import requests
import pandas as pd
from datetime import date, timedelta
import pandas_market_calendars as mcal

# weekday: Tuesday=1, Thursday=3
# weekly: whether weekly contracts exist (post-SEBI Nov 2024 rules)
INDEX_CONFIG = {
    "nifty":     {"weekday": 1, "calendar": "XNSE", "weekly": True},
    "sensex":    {"weekday": 3, "calendar": "XBOM", "weekly": True},
    "banknifty": {"weekday": 1, "calendar": "XNSE", "weekly": False},
    "finnifty":  {"weekday": 1, "calendar": "XNSE", "weekly": False},
}


def get_expiry(when: str = "current", kind: str = "weekly",
               index: str = "nifty", today: date | None = None) -> date:
    """
    F&O expiry date for Indian index derivatives.

    when  : "current" (nearest upcoming) | "next"
    kind  : "weekly" | "monthly"
    index : "nifty" | "sensex" | "banknifty" | "finnifty"
    """
    cfg = INDEX_CONFIG[index.lower()]

    if kind == "weekly" and not cfg["weekly"]:
        raise ValueError(
            f"{index} has no weekly contracts (discontinued by SEBI, Nov 2024). "
            f"Use kind='monthly'."
        )

    wd  = cfg["weekday"]
    cal = mcal.get_calendar(cfg["calendar"])

    today = today or date.today()
    valid = set(cal.valid_days(f"{today.year}-01-01",
                               f"{today.year + 1}-12-31").date)

    def adjust(d):
        while d not in valid:
            d -= timedelta(days=1)
        return d

    def last_target_day(y, m):
        last = date(y, m, calendar.monthrange(y, m)[1])
        return last - timedelta(days=(last.weekday() - wd) % 7)

    skip = {"current": 0, "next": 1, "far": 2}[when]

    if kind == "weekly":
        d = today + timedelta(days=(wd - today.weekday()) % 7)
        return adjust(d + timedelta(weeks=skip))

    if kind == "monthly":
        y, m, found = today.year, today.month, []
        while len(found) < skip + 1:
            exp = adjust(last_target_day(y, m))
            if exp >= today:
                found.append(exp)
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return found[skip]

    raise ValueError(f"kind must be 'weekly' or 'monthly', got {kind!r}")

def get_nse_holidays(year: int | None = None,
                     calendar_name: str = "XNSE") -> list[date]:
    """
    NSE trading holidays for a given calendar year (excluding weekends).

    Returns full-day market closures only — does not include Muhurat
    trading sessions (e.g. Diwali Laxmi Pujan) which fall on weekends.
    """
    year = year or date.today().year
    cal = mcal.get_calendar(calendar_name)
    holidays = cal.holidays().holidays
    return sorted(
        date.fromisoformat(str(h)[:10])
        for h in holidays
        if str(h).startswith(str(year))
    )

def is_nse_holiday(d: date, calendar_name: str = "XNSE") -> bool:
    """True if d is a weekday NSE holiday (weekends return False)."""
    if d.weekday() >= 5:
        return False
    return d in get_nse_holidays(d.year, calendar_name)

def is_last_trading_day_of_week(d: date, calendar_name: str = "XNSE") -> int:
    """1 if d is the final trading day of its ISO week (Mon–Sun), else 0."""
    cal = mcal.get_calendar(calendar_name)
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    valid = cal.valid_days(monday.isoformat(), sunday.isoformat()).date
    return int(len(valid) > 0 and d == max(valid))


def is_last_trading_day_of_month(d: date, calendar_name: str = "XNSE") -> int:
    """1 if d is the final trading day of its calendar month, else 0."""
    cal = mcal.get_calendar(calendar_name)
    month_start = d.replace(day=1)
    month_end   = d.replace(day=calendar.monthrange(d.year, d.month)[1])
    valid = cal.valid_days(month_start.isoformat(), month_end.isoformat()).date
    return int(len(valid) > 0 and d == max(valid))

def nse_market_status(headers: dict) -> str:
    url = "https://api.upstox.com/v2/market/status/NSE"
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP error: {response.status_code} - {response.text}")
    return response.json()["data"]["status"]

def is_market_open_today(calendar_name: str = "XNSE",
                         today: date | None = None) -> bool:
    """True if the market has a scheduled trading session today."""
    today = today or date.today()
    cal = mcal.get_calendar(calendar_name)

    valid_days = cal.valid_days(
        start_date=today,
        end_date=today
    )

    return not valid_days.empty

if __name__ == "__main__":
    print("expiry",get_expiry())
    today = date.today()
    print(is_last_trading_day_of_week(today))
    if not is_last_trading_day_of_week(today):
        print("Not last trading day — skipping weekly signals")
    else:
        print("last trading day — No skipping weekly signals")
    print(is_last_trading_day_of_month(today))
    if not is_last_trading_day_of_month(today):
        print("Not last trading day — skipping monthly signals")
    else:
        print("last trading day — No skipping monthly signals")

        

    # for h in get_nse_holidays(2026):
    #     print(f"{h}  {h:%A}")
    # for idx in INDEX_CONFIG:
    #     print(f"\n{idx.upper()}")
    #     for when in ("current", "next"):
    #         for kind in ("weekly", "monthly"):
    #             try:
    #                 d = get_expiry(when, kind, idx)
    #                 print(f"  {when:7} {kind:7}: {d}  {d:%a}")
    #             except ValueError:
    #                 print(f"  {when:7} {kind:7}: —  (no weeklies)")



