# main.py

from datetime import datetime
from alloc import DynamicTreasures, ETFAvalanches, MeanReversion, RisingAssets
from tickers import TICKERS_DT, TICKERS_EA, TICKERS_MR, TICKERS_RA

def alpha_alloc(initial_value):
    today = datetime.now().strftime('%Y-%m-%d')

    ra = RisingAssets("ra.json", initial_value * 0.3, today, TICKERS_RA)
    ra.save_portfolio()
    ra.allocate()
    ra.save_portfolio()

    ra = DynamicTreasures("dt.json", initial_value * 0.2, today, TICKERS_DT)
    ra.save_portfolio()
    ra.allocate()
    ra.save_portfolio()

    ra = ETFAvalanches("ea.json", initial_value * 0.2, today, TICKERS_EA)
    ra.save_portfolio()
    ra.allocate()
    ra.save_portfolio()

    ra = MeanReversion("mr.json", initial_value * 0.3, today, TICKERS_MR)
    ra.save_portfolio()
    ra.allocate()
    ra.save_portfolio()


if __name__ == '__main__':
    alpha_alloc(10000)