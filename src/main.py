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
from broker.bybit import BybitBroker
from broker.roboforex import RStockTrader

from feed.deriv import DerivLiveData
from feed.okx import OKXLiveData
from feed.bybit import BybitLiveData

from strategy import TPS, Anty, KissIchimoku, RSIPowerZones
from strategy_stat import CointegratedPairs, MarketNeutral

def read_config(fn):
    config = {}
    with open(fn) as f:
        config = json.load(f)
    return config

def run_bot():
    config = read_config(sys.argv[1])
    tm = time.localtime()

    logger.remove()
    #logger.add(sys.stderr,
    #    format = '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>')
    #    #filter = lambda record: record['extra'] is {})
    name = config["trade"].get("log_name", config["strategy"]["name"])
    logger.add('log/%s/live_%04d%02d%02d.log' % (name, tm.tm_year, tm.tm_mon, tm.tm_mday),
            format = '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}')
            #filter = lambda record, ticker=b['config["ticker"]']: record['extra'].get("ticker", '') == ticker)

    logger.info("")
    logger.info("Starting strategy")

    logger.debug(f"Config params: {config}")

    cerebro = bt.Cerebro()

    # Add live data feed
    feed_auth = read_config(config['feed']['auth'])
    for symbol in sorted(set(config['feed']['tickers'])):
        for gran in config['feed']['timeframe_min']:
            data = None
            if config['feed']['provider'] == "Deriv":
                data = DerivLiveData(
                    logger=logger,
                    app_id=feed_auth['account_id'],
                    symbol=symbol, granularity=gran * 60,
                    history_size=config['feed']['history_size'],
                    realtime_md=config['feed']['realtime_md']
                )
            elif config['feed']['provider'] == "OKX":
                data = OKXLiveData(
                    logger=logger, symbol=symbol,
                    granularity=gran * 60,
                    history_size=config['feed']['history_size']
                )
            elif config['feed']['provider'] == "Bybit":
                data = BybitLiveData(
                    logger=logger,
                    symbol=symbol,
                    granularity=gran,
                    history_size=config['feed']['history_size'],
                    realtime_md=config['feed']['realtime_md']
                )
            data.timeframe_min = gran 
            data.ticker = symbol
            cerebro.adddata(data)

    # Read notifier auth
    notifier_auth = {}
    if 'auth' in config['notifier']:
        notifier_auth = read_config(config['notifier']['auth'])
    bot_token = notifier_auth.get('api_key', None)
    channel_id = notifier_auth.get('account_id', None)

    # Add broker
    broker = None
    broker_auth = read_config(config['trade']['auth'])
    if config['trade']['broker'] == "Deriv":
        broker = DerivBroker(
            logger=logger,
            bot_token=bot_token,
            channel_id=channel_id,
            app_id=broker_auth['account_id'],
            api_token=broker_auth['api_key'],
            contract_expiration_min=config['trade']['expiration_min'],
            min_payout=config['trade']['min_payout']
        )
    elif config['trade']['broker'] == "OKX":
        broker = OKXBroker(
            logger=logger,
            bot_token=bot_token,
            channel_id=channel_id,
            api_key=broker_auth['api_key'],
            api_secret=broker_auth['api_secret'],
            api_passphrase=broker_auth['api_passphrase'],
            contract_expiration_min=config['trade']['expiration_min']
        )
    elif config['trade']['broker'] == "Bybit":
        broker = BybitBroker(
            logger=logger,
            bot_token=bot_token,
            channel_id=channel_id,
            api_key=broker_auth['api_key'],
            api_secret=broker_auth['api_secret']
        )
    elif config['trade']['broker'] == "RStockTrader":
        broker = RStockTrader(
            logger=logger,
            bot_token=bot_token,
            channel_id=channel_id,
            account_id=broker_auth['account_id'],
            api_key=broker_auth['api_key']
        )
    else:
        raise NotImplementedError(config['trade']['broker'])

    broker.datas = cerebro.datas
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
    elif config["strategy"]["name"] == 'CointegratedPairs':
        cerebro.addstrategy(CointegratedPairs, logger=logger, trade=config['trade'])
    elif config["strategy"]["name"] == 'MarketNeutral':
        cerebro.addstrategy(MarketNeutral, logger=logger, trade=config['trade'])
    elif config["strategy"]["name"] == 'TPS':
        cerebro.addstrategy(TPS, logger=logger, trade=config['trade'])
    else:
        raise NotImplementedError(config["strategy"]["name"])

    print(f"🔁 Starting live strategy {config['strategy']['name']}...")
    cerebro.run()

if __name__ == '__main__':
    run_bot()
