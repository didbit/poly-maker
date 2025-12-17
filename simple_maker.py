import time
import traceback
from poly_data.polymarket_client import PolymarketClient
from poly_data.sheets import get_market_configs
from poly_data.strategy import Strategy

def main():
    print("Starting PolyMaker Passive Maker...")
    try:
        client = PolymarketClient()
    except Exception as e:
        print(f"Failed to initialize Polymarket Client: {e}")
        traceback.print_exc()
        return

    strategies = []

    # Load configs
    try:
        df = get_market_configs()
        print(f"Loaded {len(df)} market configurations.")

        for _, row in df.iterrows():
            try:
                # Convert row to dict
                config = row.to_dict()
                strategy = Strategy(client, config)
                strategies.append(strategy)
            except Exception as e:
                print(f"Failed to init strategy for {row.get('token_id', 'unknown')}: {e}")

        print(f"Initialized {len(strategies)} strategies.")
    except Exception as e:
        print(f"Error loading configs: {e}")
        traceback.print_exc()
        return

    # Main Loop
    while True:
        cycle_start = time.time()

        for strategy in strategies:
            try:
                # Check cycle delay
                if time.time() - strategy.last_tick_time >= strategy.cycle_delay:
                    strategy.run_tick()
                    # Small sleep to yield CPU if needed, but not blocking others significantly
                    # Actually TSe says "Sequential processing ... potential delays".
                    # If we don't sleep here, we might hit rate limits if many strategies run instantly.
                    # But cycle_delay handles per-market delay.
                    pass
            except Exception as e:
                print(f"Error in strategy {strategy.token_id}: {e}")
                traceback.print_exc()

        # Avoid tight loop if all strategies are waiting
        time.sleep(0.1)

if __name__ == "__main__":
    main()
