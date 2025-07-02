pip install websocket-client loguru pandas matplotlib seaborn plotly nbstripout

git submodule update --init --recursive

nbstripout --install

Here’s a general breakdown of the **most active trading times** for major Forex pairs, based on overlapping trading sessions (when liquidity and volatility are usually highest):

---

### 🔄 **Trading Sessions (UTC Time)**
| Session        | Time (UTC)       |
|----------------|------------------|
| Sydney         | 10:00 PM – 07:00 AM |
| Tokyo (Asia)   | 12:00 AM – 09:00 AM |
| London (Europe)| 08:00 AM – 05:00 PM |
| New York       | 01:00 PM – 10:00 PM |

---

### 🔥 **Most Active Time Ranges by Pair**

| Forex Pair      | Most Active Time (UTC)                | Best Sessions        |
|------------------|----------------------------------------|-----------------------|
| **EUR/USD**      | 01:00 PM – 04:00 PM                    | London + New York    |
| **GBP/USD**      | 08:00 AM – 04:00 PM                    | London + New York    |
| **USD/JPY**      | 12:00 AM – 04:00 AM & 01:00 PM – 04:00 PM | Tokyo + New York     |
| **AUD/USD**      | 10:00 PM – 02:00 AM                    | Sydney + Tokyo       |
| **NZD/USD**      | 10:00 PM – 02:00 AM                    | Sydney + Tokyo       |
| **USD/CAD**      | 01:00 PM – 05:00 PM                    | New York             |
| **EUR/JPY**      | 12:00 AM – 04:00 AM & 08:00 AM – 04:00 PM | Tokyo + London       |
| **GBP/JPY**      | 12:00 AM – 04:00 AM & 08:00 AM – 04:00 PM | Tokyo + London       |
| **EUR/GBP**      | 08:00 AM – 05:00 PM                    | London               |

---

### 🧠 Tips:
- **Highest volatility** often occurs during session overlaps (e.g., **London/New York**: 01:00 PM – 04:00 PM UTC).
- Avoid **low-volume hours** (like 08:00 PM – 11:00 PM UTC) unless you’re trading exotic or range strategies.
- **News events** can create high activity outside normal ranges.

Would you like the same info in your local timezone or tailored for a specific trading strategy (like scalping or swing)?


### Particular strategies

VXX - daily short, "Vol Panics" - Buy the Fear, Sell the Greed, p.74


python src/bybit_trades.py cfg/tps-bybit-testbot.json '20250628 065706' 1
