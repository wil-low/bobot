# main.py

from datetime import datetime
from alloc import DynamicTreasures, ETFAvalanches, MeanReversion, RisingAssets

def write_tickers(tickers, fn):
    with open(fn, "w") as f:
        for t in tickers:
            f.write(f"{t}\n")

def alpha_alloc(initial_value):
    today = datetime.now().strftime('%Y-%m-%d')

    strategy0 = RisingAssets(initial_value * 0.3, today)
    strategy0.allocate()
    #strategy0.save_portfolio()

    strategy1 = DynamicTreasures(initial_value * 0.2, today)
    strategy1.allocate()
    #strategy1.save_portfolio()

    strategy2 = ETFAvalanches(initial_value * 0.2, today)
    strategy2.allocate()
    #strategy2.save_portfolio()

    strategy3 = MeanReversion(initial_value * 0.3, today)
    strategy3.allocate()
    #strategy3.save_portfolio()


if __name__ == '__main__':
    #write_tickers(TICKERS_RA, 'cfg/ra.txt')
    #write_tickers(TICKERS_MR, 'cfg/mr.txt')
    #write_tickers(TICKERS_DT, 'cfg/dt.txt')
    #write_tickers(TICKERS_EA, 'cfg/ea.txt')
    alpha_alloc(10000)