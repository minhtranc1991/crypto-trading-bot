import json
import time
import math
import pandas as pd
from env import Environment
from typing import Union
from datetime import datetime, timedelta
from okx_api import OkxAPI

LOCAL_ENV = Environment.LOCAL
EXCHANGE_ENV = Environment.TESTNET
POSITION_NOMINAL_VALUE = 100
SPOT_TAKER_FEE = 0.1 / 100
FUTURES_TAKER_FEE = 0.05 / 100
EST_TRADING_FEE = SPOT_TAKER_FEE + FUTURES_TAKER_FEE
FUNDING_RATE_ENTRY_THRESHOLD = EST_TRADING_FEE

class Trader:
    def __init__(self, api):
        self.api = api
        self.spot_order = None
        self.futures_order = None

    def get_tradable_ticker(self) -> Union[pd.DataFrame, int]:
        
        spot_tickers = self.api.get_all_tickers("SPOT")
        spot_tickers = pd.DataFrame(spot_tickers)["instId"]
        
        funding_rates = self.api.get_all_funding_rates()

        columns_to_keep = ["instId", "fundingTime", "minFundingRate", "maxFundingRate", "fundingRate"]
        funding_rates = pd.DataFrame(funding_rates)[columns_to_keep]
        funding_rates["instId"] = funding_rates["instId"].str.replace("-SWAP", "")

        numeric_columns = columns_to_keep[1:]
        funding_rates[numeric_columns] = funding_rates[numeric_columns].astype("float64")
        funding_rates = funding_rates.query("fundingRate > 0 & fundingRate == fundingRate.max()")

        tradable_ticker = pd.merge(spot_tickers, funding_rates, how="inner")
        print("----------------------------------")
        print("Ticker with best funding rate:")
        print(tradable_ticker)
        print("----------------------------------")

        return tradable_ticker

    @staticmethod
    def check_funding_time(funding_time: str) -> Union[int, int]:
        funding_time = datetime.fromtimestamp(int(funding_time / 1000)) - timedelta(seconds=60)
        current_time = datetime.fromtimestamp(int(time.time()))             
        time_to_funding = int((funding_time - current_time).total_seconds())
        if -55 <= time_to_funding <= 0: # Currently in the funding interval
            return True, 0
        elif time_to_funding < -55: # In the funding interval but too late or server funding time is not yet updated
            return False, 300
        else: # Before the funding interval
            return False, time_to_funding 

    @staticmethod
    def check_funding_rate(funding_rate, threshold, purpose) -> int:
        if funding_rate >= threshold:
            print("----------------------------------")
            print(f"Funding rate {funding_rate} >= min. requirement {threshold} for {purpose}")
            print("----------------------------------")
            return True
        else:
            print("----------------------------------")
            print(f"Funding rate {funding_rate} < min. requirement {threshold} for {purpose}")
            print("----------------------------------")
            return False
    
    def check_opening_positions(self) -> bool:
        futures_position = self.api.get_opening_position()
        if futures_position:
            spot_position = self.api.get_filled_order("SPOT")
            if spot_position:
                self.futures_order = self.api.get_filled_order("SWAP")                
                self.spot_order = spot_position

                futu_position_side = futures_position["posSide"]
                futu_size = futures_position["availPos"]
                futu_ticker = futures_position["instId"]
                futu_order_id = self.futures_order["ordId"]

                spot_side = spot_position["side"]
                spot_size = spot_position["accFillSz"]
                spot_ticker = spot_position["instId"]
                spot_order_id = spot_position["ordId"]

                print("----------------------------------")
                print("Opening positions:")
                print(f"Futures: {futu_position_side} {futu_size} {futu_ticker} -- id {futu_order_id}")
                print(f"Spot: {spot_side} {spot_size} {spot_ticker} -- id {spot_order_id}")
                print("----------------------------------")
                return True
            else:
                print("----------------------------------")
                print("Spot position does not exist")
                print("----------------------------------")
                return False
        else:
            return False

    @staticmethod
    def check_if_change_ticker(new_fr, current_fr) -> bool:
        if current_fr >= 0 and new_fr > current_fr + 2 * EST_TRADING_FEE:
            return True
        elif current_fr < 0 and new_fr >= 2 * EST_TRADING_FEE:
            return True
        else:
            return False

    def check_funding_condition(self) -> dict:
        condition = {
            "right_time": False,
            "opening_positions": False,
            "entry": False,
            "change_ticker": False,
            "exit": False
        }
        tradable_ticker = self.get_tradable_ticker()
        if not tradable_ticker.empty:
            new_ticker = tradable_ticker["instId"].values[0]
            new_ticker_fr = tradable_ticker["fundingRate"].values[0]
            new_funding_time = tradable_ticker["fundingTime"].values[0]

            condition["right_time"], time_to_funding = self.check_funding_time(new_funding_time)
            condition["opening_positions"] = self.check_opening_positions()
            condition["entry"] = self.check_funding_rate(new_ticker_fr, FUNDING_RATE_ENTRY_THRESHOLD, "entrying")

            if condition["opening_positions"]:
                current_ticker = self.futures_order["instId"]
                current_ticker_fr = float(self.api.get_ticker_funding_rate(current_ticker)["fundingRate"])
                
                condition["exit"] = not self.check_funding_rate(current_ticker_fr, 0, "maintaining positions")

                if current_ticker != new_ticker:
                    if condition["exit"]:
                        condition["change_ticker"] = True
                    else:
                        condition["change_ticker"] = self.check_if_change_ticker(new_ticker_fr, current_ticker_fr)

            return {
                "trade_condition": condition,
                "ticker": new_ticker,
                "ticker_fr": new_ticker_fr,
                "current_ticker_fr": current_ticker_fr if condition["opening_positions"] else None,
                "time_to_funding": time_to_funding
            }
        else:
            return False
    
    @staticmethod
    def round_to_greatest_number(number, decimals):
        rounded_number = round(number, decimals)
        if rounded_number >= number:
            return rounded_number
        
        increment = 10**(-decimals)
        rounded_number = rounded_number + increment
        return rounded_number

    def get_order_size(self, ticker):
        ticker_specs = {}
        ticker_market_price = {}
        for market in ["SPOT", "SWAP"]:
            if market == "SWAP":
                ticker = ticker + "-SWAP"
            specs, market_price = self.api.get_ticker_info(market, ticker)
            ticker_specs.update({market: specs})
            ticker_market_price.update({market: market_price})

        futures_min_size = float(ticker_specs["SWAP"]["minSz"])
        futures_contract_value = float(ticker_specs["SWAP"]["ctVal"])
        futures_price = float(ticker_market_price["SWAP"]["last"])
        spot_price = float(ticker_market_price["SPOT"]["last"])
        
        # Order sizes in terms of base currency
        spot_order_size = POSITION_NOMINAL_VALUE / spot_price 
        futures_order_size = POSITION_NOMINAL_VALUE / futures_price
        final_order_size = min(spot_order_size, futures_order_size)

        # Converts order sizes back to default currency (quote and contracts)
        spot_order_size = final_order_size * spot_price / (1 - SPOT_TAKER_FEE) # Quote currency
        contract_scale = abs(round(math.log10(futures_min_size)))
        futures_order_size = self.round_to_greatest_number(final_order_size / futures_contract_value, contract_scale) # Contract

        return spot_order_size, futures_order_size

    def open_positions(self, ticker) -> None:
        spot_order_size, futures_order_size = self.get_order_size(ticker)
        spot_order_params = {
            "tdMode": "cash",
            "instId": ticker,
            "side": "buy",
            "ordType": "market",
            "sz": spot_order_size
        }
        spot_order_id = self.api.place_order("market", **spot_order_params)
        self.spot_order = self.api.get_order_details(ticker, spot_order_id)
        
        account_leverage = {
            "instId": ticker + "-SWAP",
            "mgnMode": "cross"
        }
        self.api.set_account_leverage("10", **account_leverage)

        futures_order_params = {
            "tdMode": "cross",
            "instId": ticker + "-SWAP",
            "side": "sell",
            "posSide": "short",
            "ordType": "market",
            "sz": futures_order_size
        }
        futures_order_id = self.api.place_order("market", **futures_order_params)
        self.futures_order = self.api.get_order_details(ticker + "-SWAP", futures_order_id)

    def close_positions(self, ticker) -> None:
        spot_order_params = {
            "tdMode": "cash",
            "instId": ticker,
            "side": "sell",
            "ordType": "market",
            "sz": float(self.spot_order["accFillSz"]) - abs(float(self.spot_order["fee"]))
        }
        closed_spot = self.api.close_spot_position(**spot_order_params)
        closed_futures = self.api.close_futures_position(ticker + "-SWAP", int(self.futures_order["ordId"]))
        if not closed_spot or not closed_futures:
            raise Exception(f"Error while closing positions: spot {closed_spot}, futures {closed_futures}")
    
    def change_ticker(self, new_ticker, current_ticker) -> None:
        self.close_positions(current_ticker)
        time.sleep(0.5)
        self.open_positions(new_ticker)
        print("----------------------------------")
        print("Trading ticker changed: from %s to %s" % (current_ticker, new_ticker))
        print("----------------------------------")

    def trade(self):
        condition = self.check_funding_condition()
        if condition:
            time_to_funding = condition["time_to_funding"]

            if not condition["trade_condition"]["right_time"]:
                print("----------------------------------")
                print("Wait until funding time // time to funding: %s" % (timedelta(seconds=time_to_funding)))
                print("Sleep %s seconds" % (time_to_funding))
                print("----------------------------------")
                time.sleep(time_to_funding)
                return None

            right_time = condition["trade_condition"]["right_time"]
            opening_position = condition["trade_condition"]["opening_positions"]
            entry = condition["trade_condition"]["entry"]
            new_ticker = condition["ticker"]
            new_ticker_fr = condition["ticker_fr"]
            change_ticker = condition["trade_condition"]["change_ticker"]
            exit = condition["trade_condition"]["exit"]
            current_ticker = self.futures_order["instId"] if opening_position else ""
            current_ticker_fr = condition["current_ticker_fr"] if condition["current_ticker_fr"] else ""

            print("----------------------------------")
            print(f"""
            Trade condition:
            - Entry time? 
                {right_time}
            - Opening positions? 
                {opening_position}
                Ticker: {current_ticker}
            - Good funding rate to entry? 
                {entry} 
                Ticker: {new_ticker + "-SWAP"}
                Funding rate: {new_ticker_fr}
            - Change to more profitable ticker? 
                {change_ticker} 
                Current ticker: {current_ticker}
                Ticker with best funding rate: {new_ticker + "-SWAP"}
            - Negative funding rate => exit? 
                {exit}
                Current funding rate: {current_ticker_fr}
            """)
            print("----------------------------------")
            
            opening_positions = condition["trade_condition"]["opening_positions"]
            if not opening_positions:
                if condition["trade_condition"]["entry"]:
                    self.open_positions(condition["ticker"])
                    opening_positions = True
            else:
                if condition["trade_condition"]["change_ticker"]:
                    self.change_ticker(condition["ticker"], self.spot_order["instId"])
                    condition["trade_condition"]["exit"] = False
                    opening_positions = True

                if condition["trade_condition"]["exit"]:
                    self.close_positions(self.spot_order["instId"])

            if not opening_positions:
                print("----------------------------------")
                print("Inappropriate funding condition, keep waiting")
                print("----------------------------------")
                time.sleep(10)
            else:
                time.sleep(60)
        else:
            print("----------------------------------")
            print("Inappropriate funding condition, keep waiting")
            print("----------------------------------")
            time.sleep(10)


if __name__ == "__main__":

    with open("api_config.json") as config_file:
        if EXCHANGE_ENV == Environment.TESTNET:
            API_CONFIG = json.load(config_file)["TESTNET"]
        else:
            API_CONFIG = json.load(config_file)["MAINNET"]
    
    okx_api = OkxAPI(API_CONFIG)
    trader = Trader(okx_api)
    while True:
        trader.trade()
