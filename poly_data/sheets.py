import pandas as pd
from poly_utils.google_utils import get_spreadsheet

def get_market_configs():
    """
    Fetches market configurations from the 'Selected Markets' sheet.

    Returns:
        pd.DataFrame: DataFrame containing market configurations.
    """
    try:
        spreadsheet = get_spreadsheet()
        wk = spreadsheet.worksheet('Selected Markets')
        records = wk.get_all_records()
        df = pd.DataFrame(records)

        # Filter out empty rows if any
        # Assuming token_id must be present
        if 'token_id' in df.columns:
             df = df[df['token_id'] != ''].copy()

        # Ensure numeric types
        numeric_cols = ['min_spread', 'max_capital_per_market', 'min_order_size', 'max_buy_steps', 'cycle_delay', 'risk_threshold']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        return df
    except Exception as e:
        print(f"Error fetching market configs: {e}")
        return pd.DataFrame()
