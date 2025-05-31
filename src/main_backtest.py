# main.py

from datetime import datetime
import json
import os
import sys
import time
from loguru import logger  # pip install loguru

# Get the parent directory and append it to sys.path
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.append(parent_dir)
sys.path.append(parent_dir + '/backtrader')

import backtrader as bt

from broker.bo import BinaryOptionsBroker
from feed.datafeed import HistDataCSVData, SQLiteData, TiingoCSVData
from strategy import CRSISP500, TPS, Anty, KissIchimoku, RSIPowerZones, CRSIShort
from strategy_stat import CointegratedPairs

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
        if timeframe <= 1440:
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
            data = None
            if config['feed']['provider'] == "HistData":
                data = HistDataCSVData(
                    dataname=f'datasets/histdata/DAT_ASCII_{symbol}_M1_{config['feed']['year']}.csv',
                    # Do not pass values before this date
                    #fromdate=datetime.datetime(2005, 1, 1),
                    # Do not pass values after this date
                    #todate=datetime(2023, 2, 27),
                )
            elif config['feed']['provider'] == "TiingoS":  # stocks
                fn = f'datasets/tiingo/{symbol}.csv'
                data = TiingoCSVData(
                    dataname=fn,
                    # Do not pass values before this date
                    #fromdate=datetime.datetime(2005, 1, 1),
                    # Do not pass values after this date
                    #todate=datetime(2023, 2, 27),
                )
            elif config['feed']['provider'] == "TiingoC":  # crypto
                fn = f'datasets/tiingo/{symbol}_M1{config['feed']['year']}.csv'
                data = HistDataCSVData(
                    dataname=fn,
                    # Do not pass values before this date
                    #fromdate=datetime.datetime(2005, 1, 1),
                    # Do not pass values after this date
                    #todate=datetime(2023, 2, 27),
                )
            elif config['feed']['provider'] == "sqlite":  # crypto
                fn = f'alpha/work/stock.sqlite'
                data = SQLiteData.from_sqlite(
                    symbol=symbol,
                    database=fn,
                    # fromdate=datetime(2005, 1, 1),
                    # todate=datetime(2023, 2, 27),
                )
            else:
                raise NotImplementedError(config['feed']['provider'])

            data.ticker = symbol
            data.timeframe_min = timeframe_min
            if timeframe_min == 1440:
                cerebro.adddata(data)
            else:
                cerebro.resampledata(data, timeframe=timeframe, compression=compression)

    if config['trade']['broker'] == "BO":
        broker = BinaryOptionsBroker(
            logger=logger,
            bot_token=config['auth']['bot_token'],
            channel_id=config['auth']['channel_id'],
            cash=config['trade']['cash'],
            contract_expiration_min=config['trade']['expiration_min']
        )
        cerebro.setbroker(broker)
    else:
        cerebro.broker.setcash(config['trade']['cash'])
        cerebro.broker.set_slippage_perc(0.0003)
        cerebro.broker.setcommission(commission=0, leverage=config['trade']['leverage'])
        cerebro.broker.post_message = lambda msg: 1

    # Add strategy
    if config["strategy"]["name"] == 'RSIPowerZones':
        cerebro.addstrategy(RSIPowerZones, logger=logger, trade=config['trade'])
    elif config["strategy"]["name"] == 'Anty':
        cerebro.addstrategy(Anty, logger=logger, trade=config['trade'])
    elif config["strategy"]["name"] == 'KissIchimoku':
        cerebro.addstrategy(KissIchimoku, logger=logger, trade=config['trade'])
    elif config["strategy"]["name"] == 'CointegratedPairs':
        cerebro.addstrategy(CointegratedPairs, logger=logger, trade=config['trade'])
    elif config["strategy"]["name"] == 'CRSIShort':
        cerebro.addstrategy(CRSIShort, logger=logger, trade=config['trade'])
    elif config["strategy"]["name"] == 'TPS':
        cerebro.addstrategy(TPS, logger=logger, trade=config['trade'])
    elif config["strategy"]["name"] == 'CRSISP500':
        cerebro.addstrategy(CRSISP500, logger=logger, trade=config['trade'])
    else:
        raise NotImplementedError(config["strategy"]["name"])

    # Analyzer
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    print(f"🔁 Starting backtest strategy {config['strategy']['name']}...")
    result = cerebro.run()

    logged_print(f"Sharpe Ratio: {result[0].analyzers.sharpe.get_analysis()['sharperatio']}")

    #json_str = json.dumps(result[0].analyzers.trades.get_analysis(), indent=4)
    #logger.debug(f'Trade Analyzer: {json_str}')
    print_trade_analysis(result[0].analyzers.trades.get_analysis())
    
    #json_str = json.dumps(result[0].analyzers.drawdown.get_analysis(), indent=4)
    #logger.debug(f'DrawDown: {json_str}')
    drawdown = result[0].analyzers.drawdown.get_analysis()
    logged_print("DrawDown: %.2f (%.2f%%)" % (drawdown['moneydown'], drawdown['drawdown']))

    p = result[0].position
    if p:
        #logged_print(p)
        logged_print('Open Position exists, size: %.2f, cost: %.2f, pnl: %.2f' % (p.size, abs(p.size * p.adjbase), (p.adjbase - p.price) * p.size))

    logged_print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())
    
    if len(config["feed"]["tickers"]) < 10:
        cerebro.plot(style='candle', barup='green', bardown='red', volume=False)

if __name__ == '__main__':
    run_bot()
