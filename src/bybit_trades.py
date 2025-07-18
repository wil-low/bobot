# bybit_trades.py

import argparse
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

from broker.bybit import BybitBroker

def read_config(fn):
    config = {}
    with open(fn) as f:
        config = json.load(f)
    return config

def bybit_trades(args):
    config = read_config(args.config)

    date_from = args.start_date
    date_to = args.end_date

    logger.info("")
    logger.info("Starting bybit_trades")
    logger.debug(config)

    # Add broker
    broker_auth = read_config(config['trade']['auth'])
    broker = BybitBroker(
        logger=logger,
        bot_token=None,
        channel_id=None,
        api_key=broker_auth['api_key'],
        api_secret=broker_auth['api_secret'],
        tickers={}
    )

    while not broker.ready():
        time.sleep(0.5)

    broker.get_trades(date_from, date_to)

    while not broker.ready():
        time.sleep(0.5)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", required=True, help='config file name')
    parser.add_argument("--start_date", "-s", required=True, help='start date in format YYYY-MM-DD')
    parser.add_argument("--end_date", "-e", help='end date in format YYYY-MM-DD')
    args = parser.parse_args()

    bybit_trades(args)
