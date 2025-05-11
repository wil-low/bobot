import threading
import requests
import json
import websocket
from feed.datafeed import BobotLiveDataBase

class OKXLiveData(BobotLiveDataBase):
    """
    A Backtrader live data feed that connects to OKX WebSocket and streams tick data.
    """
    BASE_URL = "https://www.okx.com"
    CANDLESTICK_ENDPOINT = "/api/v5/market/candles"

    def __init__(self, logger, symbol, granularity, history_size):
        super().__init__(logger, symbol, granularity, history_size)
        self.bar = None
        if self.granularity == 1 * 60:
            self.bar = "1m"
        elif self.granularity == 3 * 60:
            self.bar = "3m"
        elif self.granularity == 5 * 60:
            self.bar = "5m"
        elif self.granularity == 15 * 60:
            self.bar = "15m"
        elif self.granularity == 60 * 60:
            self.bar = "1H"
        elif self.granularity == 4 * 60 * 60:
            self.bar = "4H"
        else:
            raise NotImplementedError(granularity)
        print("OKXLive init")

    def start(self):
        super().start()
        print(f"OKXLive start {self.ticker} {self.bar}")
        self.fetch_history()

    def fetch_history(self):
        """
        Fetches OHLC candlestick data from OKX.

        :param symbol: Instrument ID (e.g., BTC-USDT-SWAP)
        :param bar: Timeframe (e.g., 1m, 5m, 1H, 1D)
        :param limit: Number of candles to fetch
        :return: List of OHLC data
        """

        url = f"{self.BASE_URL}{self.CANDLESTICK_ENDPOINT}"
        params = {
            "instId": self.symbol,
            "bar": self.bar,
            "limit": str(self.history_size)
        }

        response = requests.get(url, params=params)
        data = response.json()
        self.log(data)
        if data["code"] != "0":
            self.log(f"Error fetching data: {data['msg']}")
            return

        self.log(f"Historical candles: {len(data['data'])}")

        for candle in reversed(data["data"]):
            if candle[8] == "1":  # completed candle
                ts = int(candle[0])
                c = {
                    "epoch": int(ts / 1000),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": 0 #float(candle[5]),
                }
                self.last_epoch = c['epoch']
                self.ohlc['close'] = c['close']
                #self.log(f"Hist bar queued for epoch: {self.last_epoch}")
                self.md.put(c)
        self.last_epoch += self.granularity
        self.log(f"last_epoch: {self.last_epoch}")
        self.reset_ohlc()
        self._start_ws()

    def _start_ws(self):
        def on_open(ws):
            #self.log("WebSocket connected.")
            self.keep_alive('ping')
            # Subscribe to the candlestick channel
            params = {
                "op": "subscribe",
                "args": [
                    {
                        "channel": "tickers",
                        "instId": self.symbol
                    }
                ]
            }
            s = json.dumps(params)
            self.log(s)
            ws.send(s)

        def on_message(ws, message):
            #self.log(f"datafeed: {message}")
            if message == 'pong':
                return
            data = json.loads(message)

            if "event" in data:
                self.log("Event:", data)
                return

            if "arg" in data and "data" in data:
                for item in data["data"]:
                    if item['lastSz'] != "0":
                        epoch = int(item['ts']) / 1000
                        epoch = int(epoch / self.granularity) * self.granularity
                        self.update_ohlc(epoch, float(item['last']))
                        #self.log(f"{self.granularity}: epoch {epoch}, last {self.last_epoch}")
                        if epoch >= self.last_epoch:
                            if self.last_ts < epoch:
                                self.log(f"New bar {epoch}: {str(self.ohlc)}")
                                self.md.put(self.ohlc.copy())  # Use copy to avoid overwriting
                                self.last_ts = epoch           # ✅ only update after queuing
                                self.reset_ohlc()
                            else:
                                self.log(f"Duplicate epoch skipped: {epoch}")
                            self.last_epoch += self.granularity

        def on_error(ws, message):
            self.log(f"[OKXLiveData] on_error: {repr(message)}")

        def on_close(ws, close_status_code, close_msg):
            self.log(f"[OKXLiveData] WebSocket closed: {close_status_code} - {close_msg}")
        
        def run_ws():
            self.ws = websocket.WebSocketApp(f"wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            self.ws.run_forever()

        self.thread = threading.Thread(target=run_ws)
        self.thread.daemon = True
        self.thread.start()
