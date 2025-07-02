## 📈 Bobot Trading Framework

`bobot` is a modular Python-based framework for building and executing algorithmic trading strategies. Originally conceived as a binary options bot, it has evolved into a robust system for live and paper trading across multiple brokers and exchanges.

### ⚙️ Key Features

* 🧠 **Strategy Framework**: Easily develop and plug in strategies using Backtrader.
* 📊 **Data Handling**: Efficient historical and live data handling via `pandas` and custom adapters.
* 🤝 **Broker Integrations**:

  * ✅ Deriv (binary options)
  * ✅ Bybit
  * ✅ OKX
  * ✅ Roboforex
* 🧩 **Modular Design**: Clean separation of strategy, execution, and data layers.
* 🔄 **Live Trading Support**: Real-time execution and portfolio tracking.
* 💡 **Backtesting Tools**: Use the same codebase to test strategies offline using historical data.

---

### 📅 Future Improvements

* [ ] Web UI for monitoring
* [ ] Strategy parameter tuning engine
* [ ] More broker support (Binance, Interactive Brokers, etc.)
* [ ] Portfolio optimization tools


## 📊 Alpha Portfolio Management System

This project implements a rules-based portfolio management system inspired by *The Alpha Formula* by Chris Cain, Larry Connors, and Connors Research, LLC. It focuses on systematic daily rebalancing using quantitative allocation strategies.

Unlike the `bobot` project (which executes trades), `alpha` generates **daily allocation recommendations**—indicating which assets to buy or sell—without submitting actual orders. Designed for semi-automated or fully manual execution.

---

### 🎯 Key Features

* 📈 **Portfolio Allocation Models**:

  * Mean reversion
  * Momentum
  * Connors’ multi-factor scoring
* 🔁 **Daily Rebalancing Logic**:

  * Calculates portfolio weights based on rules
  * Generates clear buy/sell signals
* 🗂️ **Asset Universe Flexibility**:

  * Support for stocks, ETFs, indices, and crypto
* 📝 **Signal Output**:

  * JSON reports with position sizes and recommended trades

---

### 🧠 Strategy Design

Strategies follow a common interface:

* Load historical price data
* Score and rank assets
* Determine allocations based on position limits, score thresholds, sector constraints, etc.
* Generate trades to move from current to target weights

---

### 📅 Future Improvements

* [ ] Web dashboard to visualize allocations
* [ ] Automated email/slack notifications

---

### 📚 Reference

[The Alpha Formula](https://store.tradingmarkets.com/products/new-the-alpha-formula-high-powered-strategies-to-beat-the-market-with-less-risk) by Chris Cain and Larry Connors

[Connors Research, LLC](https://www.connorsresearch.com)

