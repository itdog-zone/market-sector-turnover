import json
import requests
import pandas as pd
import os
from datetime import datetime

def fetch_market_data(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        markets = json.load(f)
    
    all_results = []
    
    for market_info in markets:
        name = market_info.get('name')
        market_code = market_info.get('market')
        url = market_info.get('url')
        payload = market_info.get('payload')
        
        print(f"Fetching data for {name} ({market_code})...")
        
        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if 'data' not in data:
                print(f"No data found for {name}")
                continue
                
            rows = []
            columns = payload.get('columns', [])
            
            # Find indices for the columns we need
            try:
                idx_sector = columns.index('sector')
                idx_value = columns.index('Value.Traded')
                idx_value_1w = columns.index('Value.Traded|1W')
                idx_value_1m = columns.index('Value.Traded|1M')
            except ValueError as e:
                print(f"Missing required columns in payload for {name}: {e}")
                continue
            
            fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for item in data['data']:
                d = item.get('d', [])
                rows.append({
                    'Market': market_code,
                    'MarketName': name,
                    'Sector': d[idx_sector] if d[idx_sector] else 'Unknown',
                    'Value.Traded': d[idx_value] if d[idx_value] is not None else 0,
                    'Value.Traded|1W': d[idx_value_1w] if d[idx_value_1w] is not None else 0,
                    'Value.Traded|1M': d[idx_value_1m] if d[idx_value_1m] is not None else 0,
                    'Fetch_Time': fetch_time
                })
            
            if not rows:
                print(f"No valid rows for {name}")
                continue
                
            df = pd.DataFrame(rows)
            
            # Group by Sector and sum values
            sector_summary = df.groupby(['Market', 'MarketName', 'Sector', 'Fetch_Time']).agg({
                'Value.Traded': 'sum',
                'Value.Traded|1W': 'sum',
                'Value.Traded|1M': 'sum'
            }).reset_index()
            
            all_results.append(sector_summary)
            
        except Exception as e:
            print(f"Error fetching {name}: {e}")
            
    if not all_results:
        print("No results collected.")
        return None
        
    final_df = pd.concat(all_results, ignore_index=True)
    return final_df

def save_results(df):
    if df is None:
        return
    
    # Create results directory if it doesn't exist
    os.makedirs('results', exist_ok=True)
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Save as CSV
    csv_filename = f"results/turnover_{today}.csv"
    df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
    print(f"Results saved to {csv_filename}")
    
    # Also save a 'latest' version for easy access
    latest_csv = "results/latest_turnover.csv"
    df.to_csv(latest_csv, index=False, encoding='utf-8-sig')
    print(f"Latest results updated at {latest_csv}")

if __name__ == "__main__":
    CONFIG_FILE = 'market_config.json'
    results_df = fetch_market_data(CONFIG_FILE)
    save_results(results_df)
