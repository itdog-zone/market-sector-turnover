#!/usr/bin/env python3
"""
Read all hourly turnover CSV files from results/hourly/ and generate
docs/hourly_data.json for the hourly-view UI.
"""

import csv
import json
import os
import glob
import re
from collections import defaultdict

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'results', 'hourly')
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'docs', 'hourly_data.json')


def extract_timestamp(filename):
    """Extract datetime from filename like turnover_2026-06-03_09-00-00.csv -> 2026-06-03 09:00:00"""
    basename = os.path.basename(filename)
    m = re.search(r'_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})\.csv$', basename)
    if m:
        return f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}"
    return None


def parse_float(val):
    if not val:
        return 0.0
    val = val.strip().strip('"').strip("'")
    try:
        return float(val)
    except ValueError:
        return 0.0


def main():
    csv_files = sorted(glob.glob(os.path.join(RESULTS_DIR, "turnover_*.csv")))

    if not csv_files:
        print("No hourly CSV files found.")
        # Still write an empty file to ensure the UI doesn't break
        output = {'snapshots': [], 'markets': []}
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"Generated empty {OUTPUT_FILE}")
        return

    # Structure: data[market_code][market_name][timestamp][sector] = { stats... }
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    all_timestamps = set()
    bucket_fields = [
        'up_0_3', 'up_3_5', 'up_5_7', 'up_7_plus',
        'down_0_3', 'down_3_5', 'down_5_7', 'down_7_plus',
        'unchanged', 'no_trade', 'total_turnover',
    ]

    for filepath in csv_files:
        ts = extract_timestamp(filepath)
        if not ts:
            continue
        all_timestamps.add(ts)

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                market = row.get('Market', '').strip()
                market_name = row.get('MarketName', '').strip()
                sector = row.get('Sector', '').strip()

                entry = {}
                for b in bucket_fields:
                    entry[b] = parse_float(row.get(b, '0'))
                # total_turnover should stay float
                entry['total_turnover'] = parse_float(row.get('total_turnover', '0'))

                data[market][market_name][ts][sector] = entry

    sorted_timestamps = sorted(all_timestamps)

    output = {
        'snapshots': sorted_timestamps,
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

            # Collect all sectors
            sectors_set = set()
            for ts in sorted_timestamps:
                if ts in data[market_code][market_name]:
                    for sector in data[market_code][market_name][ts]:
                        sectors_set.add(sector)
            market_entry['sectors'] = sorted(sectors_set)

            # Build series
            for ts in sorted_timestamps:
                if ts in data[market_code][market_name]:
                    date_entry = {}
                    for sector in market_entry['sectors']:
                        if sector in data[market_code][market_name][ts]:
                            date_entry[sector] = data[market_code][market_name][ts][sector]
                    if date_entry:
                        market_entry['series'][ts] = date_entry

            output['markets'].append(market_entry)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ Generated {OUTPUT_FILE}")
    print(f"   Snapshots: {len(output['snapshots'])}")
    print(f"   Markets: {len(output['markets'])}")


if __name__ == '__main__':
    main()