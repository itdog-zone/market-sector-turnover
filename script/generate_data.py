#!/usr/bin/env python3
"""
Read all turnover CSV files from results/ and generate a single data.json
for the visualization UI.
"""

import csv
import json
import os
import glob
import re
from collections import defaultdict

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "data.json")


def extract_date(filename):
    """Extract date from filename like turnover_2026-05-07.csv"""
    basename = os.path.basename(filename)
    m = re.search(r'_(\d{4}-\d{2}-\d{2})\.csv$', basename)
    if m:
        return m.group(1)
    return None


def main():
    csv_files = sorted(glob.glob(os.path.join(RESULTS_DIR, "turnover_*.csv")))

    # Structure: data[market_code][market_name][date][sector] = {value_traded, value_traded_1w, value_traded_1m}
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))

    all_dates = set()

    for filepath in csv_files:
        date = extract_date(filepath)
        if not date:
            continue
        all_dates.add(date)

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                market = row.get('Market', '').strip()
                market_name = row.get('MarketName', '').strip()
                sector = row.get('Sector', '').strip()
                # Normalize value: remove quotes, parse float
                value_traded = parse_float(row.get('Value.Traded', '0'))
                value_traded_1w = parse_float(row.get('Value.Traded|1W', '0'))
                value_traded_1m = parse_float(row.get('Value.Traded|1M', '0'))

                data[market][market_name][date][sector] = {
                    'v': value_traded,
                    'w': value_traded_1w,
                    'm': value_traded_1m,
                }

    # Convert to serializable format
    # We want: { markets: [...], series: { date: { market_marketname_sector: {v, w, m} } } }
    # But simpler: a list per market for charting
    output = {
        'dates': sorted(all_dates),
        'markets': [],
    }

    for market_code in sorted(data.keys()):
        for market_name in sorted(data[market_code].keys()):
            market_entry = {
                'code': market_code,
                'name': market_name,
                'sectors': [],
                'series': {},
            }
            # Collect all sectors for this market
            sectors_set = set()
            for date in sorted(all_dates):
                if date in data[market_code][market_name]:
                    for sector in data[market_code][market_name][date]:
                        sectors_set.add(sector)
            market_entry['sectors'] = sorted(sectors_set)

            # Build series: for each date, store sector values
            for date in sorted(all_dates):
                if date in data[market_code][market_name]:
                    date_entry = {}
                    for sector in market_entry['sectors']:
                        if sector in data[market_code][market_name][date]:
                            date_entry[sector] = data[market_code][market_name][date][sector]
                    if date_entry:
                        market_entry['series'][date] = date_entry

            output['markets'].append(market_entry)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ Generated {OUTPUT_FILE}")
    print(f"   Dates: {len(output['dates'])}")
    print(f"   Markets: {len(output['markets'])}")


def parse_float(val):
    if not val:
        return 0.0
    val = val.strip().strip('"').strip("'")
    try:
        return float(val)
    except ValueError:
        return 0.0


if __name__ == '__main__':
    main()