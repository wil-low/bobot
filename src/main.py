# main.py

import json
import sys
import time
import os
from loguru import logger  # pip install loguru


# Get the parent directory and append it to sys.path
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.append(parent_dir)
sys.path.append(parent_dir + '/backtrader')

import backtrader as bt

from broker.deriv import DerivBroker
from broker.okx import OKXBroker
from feed.deriv import DerivLiveData
from feed.okx import OKXLiveData
from strategy import Anty, KissIchimoku, RSIPowerZones

def run_bot():
    config = {}
    with open(sys.argv[1]) as f:
        config = json.load(f)
        print(config)

    tm = time.localtime()

    logger.remove()
    #logger.add(sys.stderr,
    #    format = '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>')
    #    #filter = lambda record: record['extra'] is {})
    logger.add('log/live_%s_%04d%02d%02d.log' % (config["strategy"]["name"], tm.tm_year, tm.tm_mon, tm.tm_mday),
            format = '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}')
            #filter = lambda record, ticker=b['config["ticker"]']: record['extra'].get("ticker", '') == ticker)

    logger.info("")
    logger.info("Starting strategy")

    config_tmp = config.copy()
    del config_tmp['auth']
    logger.debug(f"Config params: {config_tmp}")

    cerebro = bt.Cerebro()

    # Add live data feed
    for symbol in config['feed']['tickers']:
        for gran in config['feed']['timeframe_min']:
            data = None
            if config['feed']['provider'] == "Deriv":
                data = DerivLiveData(logger=logger, app_id=config['auth']['account_id'], symbol=symbol, granularity=gran * 60, history_size=config['feed']['history_size'])
            if config['feed']['provider'] == "OKX":
                data = OKXLiveData(logger=logger, symbol=symbol, granularity=gran * 60, history_size=config['feed']['history_size'])
                data.timeframe_min = gran 
            data.ticker = symbol
            cerebro.adddata(data)

    # Add broker

    broker = None
    if config['trade']['broker'] == "Deriv":
        broker = DerivBroker(
            logger=logger,
            bot_token=config['auth']['bot_token'],
            channel_id=config['auth']['channel_id'],
            app_id=config['auth']['account_id'],
            api_token=config['auth']['api_key'],
            contract_expiration_min=config['trade']['expiration_min'],
            min_payout=config['trade']['min_payout']
        )
    elif config['trade']['broker'] == "OKX":
        broker = OKXBroker(
            logger=logger,
            bot_token=config['auth']['bot_token'],
            channel_id=config['auth']['channel_id'],
            api_key=config['auth']['api_key'],
            api_secret=config['auth']['api_secret'],
            api_passphrase=config['auth']['api_passphrase'],
        )
    cerebro.setbroker(broker)

    while not broker.ready():
        time.sleep(0.5)

    # Add strategy
    if config["strategy"]["name"] == 'RSIPowerZones':
        cerebro.addstrategy(RSIPowerZones, logger=logger, trade=config['trade'])
    elif config["strategy"]["name"] == 'Anty':
        cerebro.addstrategy(Anty, logger=logger, trade=config['trade'])
    elif config["strategy"]["name"] == 'KissIchimoku':
        cerebro.addstrategy(KissIchimoku, logger=logger, trade=config['trade'])

    print(f"🔁 Starting live strategy {config['strategy']['name']}...")
    cerebro.run()

if __name__ == '__main__':
    run_bot()
