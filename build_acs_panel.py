"""Build data/acs_medicaid_state_year.csv from the Census Bureau's ACS 1-year tables.

One row per state and year, 2011-2024 (no 2020: the Census Bureau did not release standard
1-year estimates for 2020). Counts only; rates are computed in the notebook.

Two quirks this script handles:
  * The Census API (api.census.gov) now refuses data requests without a key, so the data
    come from the data.census.gov table service, which needs none. Variable labels still
    come from api.census.gov's metadata pages, which also need no key.
  * Table C27016 changes layout in 2017: 2011-2016 have adults 18-64 and one "Under 1.38"
    bracket; 2017 on have adults 19-64 and the bracket split into "Under 1.00" and
    "1.00 to 1.37". The same variable codes mean different things across the break, so
    variables are picked by label, never by code. (2010 has no 1.38 cut at all.)

Usage: python build_acs_panel.py
"""
import re
import time

import pandas as pd
import requests

YEARS = [2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024]
TABLE_URL = "https://data.census.gov/api/access/data/table?id=ACSDT1Y{y}.{t}&g=010XX00US$0400000"
LABELS_URL = "https://api.census.gov/data/{y}/acs/acs1/groups/C27016.json"
OTHER = {"B23025": {"labor_force": "B23025_003E", "unemployed": "B23025_005E"},
         "B19013": {"median_hh_income": "B19013_001E"},
         "B05001": {"pop_citizenship": "B05001_001E", "noncitizens": "B05001_006E"}}
STATES = pd.read_csv("data/expansion_dates.csv", dtype={"fips": str})[["fips", "state"]]


def get_json(url):
    for attempt in range(3):
        r = requests.get(url, timeout=60)
        if r.ok:
            return r.json()
        time.sleep(2 * (attempt + 1))
    r.raise_for_status()


def table(year, name):
    rows = get_json(TABLE_URL.format(y=year, t=name))["response"]["data"]
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["fips"] = df["GEO_ID"].str[-2:]
    return df[df["fips"] != "72"].set_index("fips")          # drop Puerto Rico


def c27016_map(year):
    """Variable codes for each quantity in this year's layout, found by label."""
    labels = {k: re.sub(r"^Estimate!!Total:?!?!?", "", v["label"]).replace(":", "")
              for k, v in get_json(LABELS_URL.format(y=year))["variables"].items() if re.search(r"_\d{3}E$", k)}
    find = lambda pattern: [k for k, l in labels.items() if re.fullmatch(pattern, l)]
    age = "19 to 64" if any("19 to 64" in l for l in labels.values()) else "18 to 64"
    low = ["Under 1.38"] if find(r"Under 1\.38 of poverty threshold") else ["Under 1.00", "1.00 to 1.37"]
    esc = re.escape
    m = {"pop_total": ["C27016_001E"],
         "pop_u138": sum((find(esc(b) + " of poverty threshold") for b in low), []),
         "adults_u138": sum((find(f"{esc(b)} of poverty threshold!!{age} years") for b in low), []),
         "adults_u138_unins": sum((find(f"{esc(b)} of poverty threshold!!{age} years!!No health insurance coverage")
                                   for b in low), []),
         "adults_200_399": find(rf"2\.00 to 3\.99 of poverty threshold!!{age} years"),
         "adults_200_399_unins": find(rf"2\.00 to 3\.99 of poverty threshold!!{age} years!!No health insurance coverage")}
    assert all(m.values()), f"{year}: a C27016 quantity was not found"
    assert len(m["adults_u138"]) == len(low), f"{year}: unexpected bracket layout"
    return m


def build():
    out = []
    for y in YEARS:
        c = table(y, "C27016")
        df = pd.DataFrame(index=c.index)
        for name, codes in c27016_map(y).items():
            df[name] = c[codes].astype(int).sum(axis=1)
        for t, cols in OTHER.items():
            o = table(y, t)
            for name, code in cols.items():
                df[name] = o[code].astype(int)
        df.insert(0, "year", y)
        out.append(df.reset_index())
        print(y, len(df), "states")
    panel = pd.concat(out).merge(STATES, on="fips")
    cols = ["year", "fips", "state", "pop_total", "pop_u138", "adults_u138", "adults_u138_unins",
            "adults_200_399", "adults_200_399_unins", "labor_force", "unemployed", "median_hh_income",
            "pop_citizenship", "noncitizens"]
    panel = panel[cols].sort_values(["year", "fips"])
    panel.to_csv("data/acs_medicaid_state_year.csv", index=False)
    print(panel.shape)


if __name__ == "__main__":
    build()
