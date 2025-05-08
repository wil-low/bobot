# main.py

from datetime import datetime
import json
import sys
import time
import backtrader as bt
from loguru import logger  # pip install loguru

from datafeed import HistDataCSVData
from strategy_nn import AntyCollector

def logged_print(message):
    logger.info(message)
    print(message)

def win_rate(data):
    if data['total'] == 0:
        return '--'
    return '%.2f%%' % (data['won'] / data['total'] * 100)

def print_pnl(data, mode):
    d = data[mode]['pnl']
    logged_print("P/L %s:  total %.2f, average %.2f, max %.2f" % (mode, d['total'], d['average'], d['max']))

def print_trade_analysis(data):
    try:
        logged_print(f"Trades: {data['total']['total']}, long {data['long']['total']}, short {data['short']['total']}, open {data['total']['open']}")
        logged_print(f"Win %: long {win_rate(data['long'])}, short {win_rate(data['short'])}")
        print_pnl(data, 'won')
        print_pnl(data, 'lost')
        logged_print("Avg Bars Held: won %.2f, lost %.2f" % (data['len']['won']['average'], data['len']['lost']['average']))
    except KeyError:
        pass

def run_bot():
    config = {}
    with open(sys.argv[1]) as f:
        config = json.load(f)
        print(config)

    tf = []

    for timeframe in config['feed']['timeframe_min']:
        if timeframe <= 240:
            tf.append((bt.TimeFrame.Minutes, timeframe, timeframe))
        else:
            raise NotImplementedError
        
    tm = time.localtime()

    logger.remove()
    #logger.add(sys.stderr,
    #    format = '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>')
    #    #filter = lambda record: record['extra'] is {})
    logger.add('log/backtest_%s_%04d%02d%02d.log' % (config["strategy"]["name"], tm.tm_year, tm.tm_mon, tm.tm_mday),
            format = '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}')
            #filter = lambda record, ticker=b['config["ticker"]']: record['extra'].get("ticker", '') == ticker)

    logger.info("")
    logger.info("Starting strategy for backtest")

    config_tmp = config.copy()
    del config_tmp['auth']
    logger.debug(f"Config params: {config_tmp}")

    cerebro = bt.Cerebro()

    # Add live data feed
    for symbol in config['feed']['tickers']:
        symbol = symbol.replace('frx', '')

        for timeframe, compression, timeframe_min in tf:
            data = HistDataCSVData(
                dataname=f'datasets/histdata/DAT_ASCII_{symbol}_M1_{config['feed']['year']}.csv',
                # Do not pass values before this date
                #fromdate=datetime.datetime(2005, 1, 1),
                # Do not pass values after this date
                #todate=datetime(2023, 2, 27),
            )
            data.ticker = symbol
            data.timeframe_min = timeframe_min
            cerebro.resampledata(data, timeframe=timeframe, compression=compression)

    # Add strategy
    if config["strategy"]["name"] == 'AntyCollector':
        cerebro.addstrategy(AntyCollector, logger=logger)
    else:
        raise NotImplementedError

    print(f"🔁 Starting neural strategy {config['strategy']['name']}...")
    result = cerebro.run()

if __name__ == '__main__':
    run_bot()
