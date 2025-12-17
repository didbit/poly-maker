import time
import math
import traceback
import pandas as pd
from py_clob_client.constants import POLYGON

class Strategy:
    def __init__(self, client, config):
        self.client = client
        self.config = config
        self.token_id = str(config['token_id'])
        self.outcome_direction = config.get('outcome_direction', 'YES')

        # Trading params
        self.min_spread = float(config.get('min_spread', 0.02))
        self.max_capital = float(config.get('max_capital_per_market', 100))
        self.min_order_size = float(config.get('min_order_size', 5))
        self.max_buy_steps = int(config.get('max_buy_steps', 5))
        self.cycle_delay = float(config.get('cycle_delay', 1))
        self.risk_threshold = float(config.get('risk_threshold', 5)) / 100.0 # Convert cents to dollars

        # State
        self.tick_size = 0.001 # Default, will try to fetch
        self.avg_entry = 0.0
        self.position = 0.0
        self.buy_steps_count = 0
        self.risk_pause = False
        self.last_tick_time = 0
        self.last_position_size = 0.0 # For tracking executions

        # Initialize
        self.initialize()

    def initialize(self):
        # 4.1 Initialization
        # 1. Get tick_size
        self.fetch_tick_size()

        # 2. Sync position
        self.sync_position()
        self.last_position_size = self.position # Init tracking

    def fetch_tick_size(self):
        try:
            # Attempt to fetch market details
            # Note: client.get_market expects condition_id/market_id.
            # If self.token_id is an asset ID, this might fail or return 404.
            # We attempt it, and if it fails, we use default.

            market_info = self.client.get_market(self.token_id)
            if market_info and 'minimum_tick_size' in market_info:
                self.tick_size = float(market_info['minimum_tick_size'])
                print(f"[{self.token_id}] Fetched tick size: {self.tick_size}")
            else:
                 print(f"[{self.token_id}] Could not fetch tick size from API (likely need Condition ID). Using default: {self.tick_size}")

        except Exception as e:
            # Catch 404 or other API errors gracefully
            print(f"[{self.token_id}] Error fetching tick size (using default {self.tick_size}): {e}")

    def sync_position(self):
        try:
            # Use PolymarketClient.get_position(tokenId)
            # Returns (raw, shares)
            raw, shares = self.client.get_position(int(self.token_id))
            self.position = shares

            # To get avg_entry, we need get_all_positions() as get_position only returns balance
            all_pos = self.client.get_all_positions()
            if not all_pos.empty:
                # asset_id in all_pos is string
                row = all_pos[all_pos['asset'] == self.token_id]
                if not row.empty:
                    self.avg_entry = float(row.iloc[0]['avgPrice'])
                else:
                    self.avg_entry = 0.0
            else:
                 if self.position == 0:
                     self.avg_entry = 0.0

            print(f"[{self.token_id}] Synced position: {self.position}, Avg Entry: {self.avg_entry}")

        except Exception as e:
            print(f"[{self.token_id}] Error syncing position: {e}")

    def run_tick(self):
        try:
            # Sync at start of tick
            self.sync_position()

            # Check for executions (Buy Fill)
            if self.position > self.last_position_size:
                print(f"[{self.token_id}] Buy Execution Detected. Position increased from {self.last_position_size} to {self.position}")
                self.buy_steps_count += 1
            elif self.position < self.last_position_size:
                 print(f"[{self.token_id}] Sell Execution Detected. Position decreased from {self.last_position_size} to {self.position}")
                 if self.position <= 0.0001:
                     print(f"[{self.token_id}] Position closed. Resetting steps.")
                     self.buy_steps_count = 0
                     self.avg_entry = 0.0

            self.last_position_size = self.position
            self.last_tick_time = time.time()
            print(f"[{self.token_id}] Running tick...")

            # 4.2.1 Update Data
            bids_df, asks_df = self.client.get_order_book(self.token_id)

            best_bid = 0.0
            best_ask = 0.0

            if not bids_df.empty:
                best_bid = float(bids_df.iloc[0]['price'])
            if not asks_df.empty:
                best_ask = float(asks_df.iloc[0]['price'])

            spread = 0.0
            if best_bid > 0 and best_ask > 0:
                spread = best_ask - best_bid

            print(f"[{self.token_id}] Bid: {best_bid}, Ask: {best_ask}, Spread: {spread}")

            # Get Active Orders
            all_orders = self.client.get_all_orders()
            my_buys = pd.DataFrame()
            my_sells = pd.DataFrame()

            if not all_orders.empty:
                my_buys = all_orders[(all_orders['asset_id'] == self.token_id) & (all_orders['side'] == 'BUY')]
                my_sells = all_orders[(all_orders['asset_id'] == self.token_id) & (all_orders['side'] == 'SELL')]

            # 4.2.2 Check Risks
            delta = 0.0
            if self.avg_entry > 0:
                delta = best_bid - self.avg_entry

            # Risk Pause
            if delta < 0 and abs(delta) > self.risk_threshold:
                if not self.risk_pause:
                    print(f"[{self.token_id}] RISK PAUSE ACTIVATED. Delta: {delta}, Threshold: {self.risk_threshold}")
                    self.risk_pause = True
                    # Cancel Buy Orders ONLY
                    # If we use cancel_all_asset, we kill sells too. We should cancel only buys.
                    if not my_buys.empty:
                         for _, order in my_buys.iterrows():
                             self.client.cancel_order(order['id'])
            else:
                if self.risk_pause:
                    print(f"[{self.token_id}] Risk Pause Deactivated.")
                    self.risk_pause = False

            # 4.2.3 Sell Logic
            if self.position > 0:
                if best_ask >= self.avg_entry:
                    target_sell_price = best_ask

                    needs_sell_update = True
                    if not my_sells.empty:
                        # Assuming one sell order
                        current_sell_price = float(my_sells.iloc[0]['price'])
                        if abs(current_sell_price - target_sell_price) < 1e-6:
                             needs_sell_update = False
                        else:
                             # Cancel existing sell
                             for _, order in my_sells.iterrows():
                                 self.client.cancel_order(order['id'])

                    if needs_sell_update:
                        print(f"[{self.token_id}] Placing Sell Order at {target_sell_price}, Size: {self.position}")
                        self.client.create_order(self.token_id, 'SELL', target_sell_price, self.position)

            # 4.2.4 Buy Logic
            if not self.risk_pause:
                 if spread >= self.min_spread:
                     if self.buy_steps_count < self.max_buy_steps:
                         current_position_val = self.position * self.avg_entry
                         open_buys_val = 0.0
                         if not my_buys.empty:
                             open_buys_val = (my_buys['price'] * my_buys['size']).sum()

                         current_capital_usage = current_position_val + open_buys_val

                         if current_capital_usage < self.max_capital:
                             target_price = best_bid + self.tick_size

                             if (best_ask - target_price) < self.min_spread:
                                 target_price = best_bid

                             if (best_ask - target_price) >= self.min_spread:
                                 if target_price > 0:
                                     order_size = self.min_order_size / target_price

                                     remaining_capital = self.max_capital - current_capital_usage
                                     max_size_by_capital = remaining_capital / target_price

                                     if order_size > max_size_by_capital:
                                         order_size = max_size_by_capital

                                     if order_size > 0:
                                         needs_buy_update = True
                                         if not my_buys.empty:
                                             # Check if existing buy is good
                                             # If multiple buys, cancel all and replace with one?
                                             if len(my_buys) > 1:
                                                 for _, order in my_buys.iterrows():
                                                     self.client.cancel_order(order['id'])
                                             else:
                                                 current_buy_price = float(my_buys.iloc[0]['price'])
                                                 if abs(current_buy_price - target_price) < 1e-6:
                                                     needs_buy_update = False
                                                 else:
                                                      for _, order in my_buys.iterrows():
                                                          self.client.cancel_order(order['id'])

                                         if needs_buy_update:
                                             print(f"[{self.token_id}] Placing Buy Order at {target_price}, Size: {order_size}")
                                             self.client.create_order(self.token_id, 'BUY', target_price, order_size)

        except Exception as e:
            print(f"[{self.token_id}] Error in run_tick: {e}")
            traceback.print_exc()

    def update_execution_state(self):
        pass
