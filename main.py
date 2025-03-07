import json
from trading import TradingBot

if __name__ == "__main__":
    with open("api_config.json") as f:
        config = json.load(f)["test"]
        
    bot = TradingBot()
    bot.run()