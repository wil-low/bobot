# Daily routine

## Work inside bobot/alpha dir

    cd alpha

## Start from an empty portfolio

Use date for which there is no json file in work/portfolio, e.g:

    python main.py --config cfg/alpha.json --action next --date 2024-05-31

## Every morning after 07:00 UTC+3, except weekends

Download MD for the previous day:

    TOKEN=<POLYGON_API_TOKEN> python dl_daily_summary.py

Verify that portfolio file for today exists in work/portfolio. Start main.py with YYYY-MM-DD of today:

    python main.py --config cfg/alpha.json --action next --date 2025-05-25

The application creates new portfolio file YYYY-MM-DD.json with transitions. Review it.

## Five minutes after US Market open

Execute transitions.

## Execute transitions

After creating positions for Mean Reversion strategy (mr), write down the actual entry price in the new portfolio.

# tickers.disabled values

  * 0 - enabled
  * 1 - filtered out by security type
  * 2 - not available at broker
  * 3 - fraudulent




# "significant price drop, check for splits or fraud!" warning

## Update prices after split (example for IBKR)

```
update prices set
	adjClose = close / 4,
	adjHigh = high / 4,
	adjLow = low / 4,
	adjOpen = open / 4,
	adjVolume = volume * 4,
	splitFactor = 4
where ticker_id=6509 and date < '2025-06-17';
```

## Disable stocks that undergone fraud (CNC, SRPT)

```
update tickers set disabled = 3 where symbol in ('CNC', 'SRPT')
```
