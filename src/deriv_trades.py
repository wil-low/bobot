# deriv_trades.py

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

from broker.deriv import DerivBroker

def deriv_trades():
    config = {}
    with open(sys.argv[1]) as f:
        config = json.load(f)
        print(config)

    date_from = sys.argv[2]
    date_to = sys.argv[3]

    logger.info("")
    logger.info("Starting deriv_trades")
    logger.debug(config)

    # Add broker (Deriv WebSocket trader)
    broker = DerivBroker(
        logger=logger,
        app_id=config['auth']['account_id'],
        api_token=config['auth']['api_key'],
        contract_expiration_min=config['trade']['expiration_min'],
        bot_token=config['auth']['bot_token'],
        channel_id=config['auth']['channel_id']
    )

    while not broker.ready():
        time.sleep(0.5)

    broker.get_trades(date_from, date_to)

    while not broker.ready():
        time.sleep(0.5)

if __name__ == '__main__':
    deriv_trades()
