
import pandas as pd
import requests
from io import StringIO
from pathlib import Path
from pprint import pformat

BASE_URL = "https://nsearchives.nseindia.com/content/indices/"

BASE_DIR = Path(
    "/Users/keerthirajamani/Downloads/sourceCode/openalgo"
)

OUTPUT_FILE = BASE_DIR / "utils" / "index_constituent.py"

INDEX_FILES = {
    "NIFTY_50": "ind_nifty50list.csv",
    "NIFTY_100": "ind_nifty100list.csv",
    "NIFTY_MIDCAP_150": "ind_niftymidcap150list.csv",
    "NIFTY_NEXT_50": "ind_niftynext50list.csv",
    "NIFTY_BANK": "ind_niftybanklist.csv",
    "NIFTY_IT": "ind_niftyitlist.csv",
    "NIFTY_200": "ind_nifty200list.csv",
    "NIFTY_500": "ind_nifty500list.csv",
}


def run_index_constituent():
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    nifty_stocks = {}

    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/csv,*/*",
            "Referer": "https://www.niftyindices.com/"
        })

        for index_name, filename in INDEX_FILES.items():
            url = BASE_URL + filename

            try:
                response = session.get(url, timeout=20)
                response.raise_for_status()

                df = pd.read_csv(StringIO(response.text))
                df.columns = df.columns.str.strip()

                if "Symbol" not in df.columns:
                    raise ValueError("Symbol column missing")

                stocks = (
                    df["Symbol"]
                    .dropna()
                    .astype(str)
                    .str.strip()
                )

                stocks = sorted(
                    set(stocks[stocks.ne("")].tolist())
                )

                if not stocks:
                    raise ValueError("Empty stock list")

                nifty_stocks[index_name] = stocks

                print(
                    f"{index_name}: {len(stocks)} stocks"
                )

            except Exception as e:
                print(f"Failed {index_name}: {e}")

    # Do not overwrite the existing file if any
    # index failed to download.
    missing = set(INDEX_FILES) - set(nifty_stocks)

    if missing:
        print(f"Update cancelled. Missing: {sorted(missing)}")
        return nifty_stocks

    # Combine all unique stocks
    all_stocks = sorted(set(
        stock
        for stocks in nifty_stocks.values()
        for stock in stocks
    ))

    nifty_stocks["ALL_STOCKS"] = all_stocks

    # Generate Python file content
    lines = [
        '"""Auto-generated NSE index constituent lists."""',
        "",
    ]

    for index_name, stocks in nifty_stocks.items():
        lines.append(
            f"{index_name} = {pformat(stocks, width=88)}"
        )
        lines.append("")

    # Write all lists to one Python file
    temp_file = OUTPUT_FILE.with_suffix(".tmp")
    temp_file.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )
    temp_file.replace(OUTPUT_FILE)

    print("-" * 40)
    print(f"Total unique stocks: {len(all_stocks)}")
    print(f"Saved to: {OUTPUT_FILE}")

    return nifty_stocks


if __name__ == "__main__":
    run_index_constituent()
