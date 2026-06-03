#!/usr/bin/env python3
"""
Hourly sector statistics: count up/down/unchanged/no_trade stocks
per market per sector, with change range breakdowns.

Runs on the 16th minute of each hour (e.g. 09:16 -> records as 09:00).
Skips if:
  - Market not open (all change == 0 OR all turnover == 0)
  - Total turnover unchanged from previous snapshot (market closed/paused)
"""

import csv
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

import requests

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'market_config.json')
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'results', 'hourly')
os.makedirs(RESULTS_DIR, exist_ok=True)


def floor_hour(dt=None):
    """Round a datetime down to the current hour."""
    if dt is None:
        dt = datetime.now()
    return dt.replace(minute=0, second=0, microsecond=0)


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_change_bucket(change):
    """
    Categorise change (%) into a bucket.
    Returns (direction, bucket_label) or None if change is None.
    """
    if change is None:
        return None  # no_trade

    if change == 0:
        return ('unchanged', 'unchanged')

    if change > 0:
        if change <= 3:
            return ('up', 'up_0_3')
        elif change <= 5:
            return ('up', 'up_3_5')
        elif change <= 7:
            return ('up', 'up_5_7')
        else:
            return ('up', 'up_7_plus')
    else:  # change < 0
        if change >= -3:
            return ('down', 'down_0_3')
        elif change >= -5:
            return ('down', 'down_3_5')
        elif change >= -7:
            return ('down', 'down_5_7')
        else:
            return ('down', 'down_7_plus')


def fetch_market_data(market_info):
    """Fetch raw stock data for a single market. Returns list of dicts with raw data."""
    name = market_info.get('name')
    market_code = market_info.get('market')
    url = market_info.get('url')
    payload = market_info.get('payload')

    columns = payload.get('columns', [])
    try:
        idx_change = columns.index('change')
        idx_value = columns.index('Value.Traded')
        idx_sector = columns.index('sector')
    except ValueError as e:
        print(f"  Missing required columns for {name}: {e}")
        return None, market_code, name

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"  Error fetching {name}: {e}")
        return None, market_code, name

    if 'data' not in data:
        print(f"  No data field in response for {name}")
        return None, market_code, name

    rows = []
    for item in data['data']:
        d = item.get('d', [])
        change_val = d[idx_change] if idx_change < len(d) and d[idx_change] is not None else None
        value_traded = d[idx_value] if idx_value < len(d) and d[idx_value] is not None else 0
        sector = d[idx_sector] if idx_sector < len(d) and d[idx_sector] else 'Unknown'

        try:
            change_val = float(change_val) if change_val is not None else None
        except (ValueError, TypeError):
            change_val = None

        try:
            value_traded = float(value_traded)
        except (ValueError, TypeError):
            value_traded = 0.0

        rows.append({
            'sector': sector,
            'change': change_val,
            'value_traded': value_traded,
        })

    return rows, market_code, name


def compute_sector_stats(stocks):
    """
    Given list of stock dicts, group by sector and compute counts.
    Returns dict: sector -> { bucket: count, total_turnover: float }
    """
    sector_data = defaultdict(lambda: defaultdict(int))
    sector_turnover = defaultdict(float)

    for s in stocks:
        sector = s['sector']
        change = s['change']
        value = s['value_traded']

        bucket = get_change_bucket(change)
        if bucket is None:
            # change is None -> no_trade
            sector_data[sector]['no_trade'] += 1
        elif bucket[0] == 'unchanged':
            sector_data[sector]['unchanged'] += 1
        else:
            sector_data[sector][bucket[1]] += 1

        sector_turnover[sector] += value

    result = {}
    for sector in sector_data:
        entry = dict(sector_data[sector])
        entry['total_turnover'] = round(sector_turnover[sector], 2)

        # Ensure all buckets exist
        for b in ['up_0_3', 'up_3_5', 'up_5_7', 'up_7_plus',
                  'down_0_3', 'down_3_5', 'down_5_7', 'down_7_plus',
                  'unchanged', 'no_trade']:
            if b not in entry:
                entry[b] = 0

        result[sector] = entry

    return result


def total_turnover_for_market(sector_stats):
    """Compute the total turnover across all sectors for a market."""
    return sum(s['total_turnover'] for s in sector_stats.values())


def should_skip(stocks):
    """
    Check if market should be skipped:
    - If all stock change values are 0 or None -> market not open
    - If all stock value_traded == 0 -> market not open
    Returns True if should skip.
    """
    all_change_zero = all(
        s['change'] is None or s['change'] == 0
        for s in stocks
    )
    all_turnover_zero = all(s['value_traded'] == 0 for s in stocks)
    return all_change_zero or all_turnover_zero


def get_previous_snapshot(market_code, name):
    """Find the most recent hourly CSV and return its total_turnover per sector
    for the same market/name combination. Returns dict {sector: total_turnover} or None."""
    pattern = os.path.join(RESULTS_DIR, 'turnover_*.csv')
    files = sorted(glob.glob(pattern))

    if not files:
        return None

    latest_file = files[-1]

    with open(latest_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('Market', '').strip() == market_code and \
               row.get('MarketName', '').strip() == name:
                # We found the previous snapshot — return all sectors from it
                result = {}
                # Re-read to collect all sectors for this market/name
                f.seek(0)
                reader2 = csv.DictReader(f)
                for r2 in reader2:
                    if r2['Market'].strip() == market_code and \
                       r2['MarketName'].strip() == name:
                        sector = r2['Sector'].strip()
                        result[sector] = float(r2.get('total_turnover', 0))
                return result

    return None


def save_snapshot(all_sector_data, fetch_time_str):
    """Write the hourly data to CSV. all_sector_data is a list of dicts."""
    if not all_sector_data:
        print("No data to save.")
        return

    filename = f"turnover_{fetch_time_str.replace(':', '-').replace(' ', '_')}.csv"
    filepath = os.path.join(RESULTS_DIR, filename)

    fieldnames = [
        'Market', 'MarketName', 'Sector', 'Fetch_Time',
        'up_0_3', 'up_3_5', 'up_5_7', 'up_7_plus',
        'down_0_3', 'down_3_5', 'down_5_7', 'down_7_plus',
        'unchanged', 'no_trade', 'total_turnover',
    ]

    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_sector_data)

    print(f"  Saved {filepath} ({len(all_sector_data)} rows)")


def main():
    config_path = CONFIG_FILE
    markets = load_config(config_path)

    # Round current time to the hour
    now = datetime.now()
    fetch_time = floor_hour(now)
    fetch_time_str = fetch_time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"Hourly fetch at {now.strftime('%Y-%m-%d %H:%M:%S')}, recording as {fetch_time_str}")

    all_rows = []

    for market_info in markets:
        name = market_info.get('name')
        market_code = market_info.get('market')
        print(f"\nProcessing {name} ({market_code})...")

        stocks, code, mkt_name = fetch_market_data(market_info)
        if stocks is None:
            continue

        # Check skip condition 1: market not open (all change=0 or all turnover=0)
        if should_skip(stocks):
            print(f"  Market not open (all change=0 or all traded=0), skipping.")
            continue

        # Compute per-sector stats
        sector_stats = compute_sector_stats(stocks)
        current_total = total_turnover_for_market(sector_stats)

        # Check skip condition 2: total turnover unchanged from previous snapshot
        prev = get_previous_snapshot(market_code, name)
        if prev is not None:
            prev_total = sum(prev.values())
            if abs(prev_total - current_total) < 1:  # within 1 unit tolerance
                print(f"  Total turnover unchanged from previous snapshot ({prev_total:.2f} vs {current_total:.2f}), skipping.")
                continue
            else:
                print(f"  Total turnover changed: {prev_total:.2f} -> {current_total:.2f}")
        else:
            print(f"  No previous snapshot found, recording first entry.")

        # Build rows for CSV
        for sector in sorted(sector_stats.keys()):
            stats = sector_stats[sector]
            row = {
                'Market': market_code,
                'MarketName': name,
                'Sector': sector,
                'Fetch_Time': fetch_time_str,
            }
            row.update(stats)
            all_rows.append(row)

        print(f"  Recorded {len(sector_stats)} sectors.")

    if all_rows:
        save_snapshot(all_rows, fetch_time_str)
    else:
        print("\nNo data recorded this run.")


if __name__ == '__main__':
    main()