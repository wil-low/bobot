# Daily routine

## Work inside bobot/alpha dir

    cd alpha

## Start from an empty portfolio

Use date for which there is no json file in work/portfolio, e.g:

    python src/main.py --config cfg/alpha.json --action next --date 2024-05-31

## Every morning after 07:00 UTC+3, except weekends

Download MD for the previous day:

    TOKEN=<POLYGON_API_TOKEN> python src/dl_daily_summary.py

Verify that portfolio file for today exists in work/portfolio. Start main.py with YYYY-MM-DD of today:

    python src/main.py --config cfg/alpha.json --action next --date 2025-05-25

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

# Redesign ETF universe for ETF Avalanches strategy

Got it 👍 — trimming the **country ETF list to 12** while still giving you good global/regional balance and keeping Avalanche-style “short squeeze prone” exposures.

Here’s a **lean 12-country list**:

### 🌍 Core Country Allocation (12 ETFs)

1. **SPMD / SPLG** – US broad market (keep only 1, not both → SPLG is cheaper, so keep SPLG).
2. **EZU** – Eurozone (covers multiple countries, so we don’t need *all* single-country ETFs).
3. **EWG** – Germany (largest EU economy, cyclical).
4. **EWQ** – France (big diversified EU economy).
5. **EWU** – UK (financials, energy exposure).
6. **EWI** – Italy (high beta, debt risk, good for stress scenarios).
7. **EWJ** – Japan (defensive, large market).
8. **EWY** – South Korea (tech + cyclicals, high beta).
9. **EWT** – Taiwan (semis, key risk-on/risk-off market).
10. **EWW** – Mexico (beta to US + EM).
11. **EWZ** – Brazil (commodities, volatile, squeeze-prone).
12. **EZA** – South Africa (resources, EM stress proxy).

---

✅ Why this trim works:

* Europe consolidated → instead of 8–9 ETFs, just keep Eurozone + Germany + France + UK + Italy.
* Asia → Japan + Korea + Taiwan (core trio).
* Americas → US + Mexico + Brazil.
* Africa → South Africa (unique resource/EM risk).
* Removed lower-liquidity/smaller countries (Austria, Belgium, Netherlands, Sweden, Singapore, Malaysia, etc.) since they overlap with EZU.

This keeps **global balance, liquidity, and volatility** while reducing redundancy.

---

👉 Now the full **ETF Avalanche core universe** would be:

* **Countries (12)**: SPLG, EZU, EWG, EWQ, EWU, EWI, EWJ, EWY, EWT, EWW, EWZ, EZA
* **Sectors (US)**: XLB, XLF, XLI, IXN, XLP, XLU, XLV, FDIS, XOP, XME
* **Thematics**: BITO, ARKK, TAN, KWEB, CLOU, ASEA, TUR, ARGT, EIS
* **Commodities/Metals/Uranium/Weapons**: URA, COPX, SLX, SIL, GDXJ, FAN, ITA, PPA, MJ, LIT, REMX

---

Would you like me to **rank these ETFs by "squeeze potential"** (i.e. high beta, prone to violent rallies in bear phases) so you have tiers for Avalanche trades, or just keep them grouped by domain (country, sector, thematic, metals)?
