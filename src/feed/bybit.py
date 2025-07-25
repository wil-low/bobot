import csv
from datetime import datetime, timezone
import threading
import time
import requests
import json
import websocket
from feed.datafeed import BobotLiveDataBase

class BybitLiveData(BobotLiveDataBase):
    """
    A Backtrader live data feed that connects to Bybit WebSocket and streams tick data.
    """
    BASE_URL = "https://api.bybit.com"
    CANDLESTICK_ENDPOINT = "/v5/market/kline"

    shared_ws = None
    shared_ws_thread = None
    consumers = {}  # symbol: BybitLiveData

    def __init__(self, logger, symbol, granularity, history_size, realtime_md):
        super().__init__(logger, symbol, granularity, history_size, realtime_md)
        self.bar = None
        #print("BybitLive init")

    def start(self):
        super().start()
        #print(f"BybitLive start {self.ticker} {self.bar}")
        self.fetch_history()

    def get_consumer(symbol):
        return BybitLiveData.consumers[symbol]

    def fetch_candles(self, start_time, end_time):
        """
        Fetches OHLC candlestick data from Bybit.
        """

        year = start_time[:4]

        start_time = datetime.strptime(start_time, "%Y-%m-%d")
        start_time = int(start_time.timestamp()) * 1000

        end_time = datetime.strptime(end_time, "%Y-%m-%d")
        end_time = int(end_time.timestamp()) * 1000

        url = f"{self.BASE_URL}{self.CANDLESTICK_ENDPOINT}"

        klines = []
        self.log(f"Start from {start_time} to {end_time}")
        while start_time < end_time:
            params = {
                "symbol": self.symbol,
                "interval": self.bar,
                "start_time": start_time,
                "end_time": end_time,
                "limit": 10
            }

            response = requests.get(url, params=params)
            data = response.json()
            self.log(data)
            klines += data
            start_time = int(data[-1][0]) + self.granularity * 1000
            self.log(f"new start_time={start_time}")

        with open(f"datasets/Bybit/{self.symbol}_M1{year}.csv", "w", newline="") as csvfile:
            writer = csv.writer(csvfile, delimiter=';')
            
            for candle in klines:
                open_time_ms = candle[0]
                open_ = candle[1]
                high = candle[2]
                low = candle[3]
                close = candle[4]
                volume = candle[5]

                # Convert timestamp to "YYYYMMDD HHMMSS"
                dt = datetime.fromtimestamp(open_time_ms / 1000.0, timezone.utc).strftime('%Y%m%d %H%M%S')

                writer.writerow([dt, open_, high, low, close, volume])

    def fetch_history(self):
        """
        Fetches OHLC candlestick data from Bybit.

        :param symbol: Instrument ID (e.g., BTC-USDT-SWAP)
        :param bar: Timeframe (e.g., 1m, 5m, 1H, 1D)
        :param limit: Number of candles to fetch
        :return: List of OHLC data
        """

        url = f"{self.BASE_URL}{self.CANDLESTICK_ENDPOINT}"
        params = {
            "category": "linear",
            "symbol": self.symbol,
            "interval": self.granularity,
            "limit": str(self.history_size)
        }

        attempt_count = 0
        while attempt_count < 5:
            response = requests.get(url, params=params)
            data = response.json()
            attempt_count += 1
            #self.log(data)
            code = data["retCode"]
            if code != 0:
                self.log(f"Error fetching data: code={code}, {data['retMsg']}, headers={response.headers}, retrying...")
                time.sleep(5)
            else:
                break

        time.sleep(0.5)
        self.log(f"Historical candles: {len(data['result']['list'])}")

        candles = list(reversed(data['result']['list'][1:]))  # skip latest candle
        for i in range(len(candles)):
            candle = candles[i]
            ts = int(candle[0])
            c = {
                "epoch": int(ts / 1000),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]) if not self.realtime_md and (i == len(candles) - 1) else 0,
            }
            self.last_epoch = c['epoch']
            self.ohlc['close'] = c['close']
            #self.log(f"Hist bar queued for epoch: {self.last_epoch}")
            self.md.put(c)
        self.last_epoch += self.granularity * 60
        #self.log(f"last_epoch: {self.last_epoch}")
        if self.realtime_md:
            self.reset_ohlc()
            self._start_ws()

    def _start_ws(self):
        def on_open(ws):
            self.log("WebSocket connected.")
            self.keep_alive(json.dumps({"op": "ping"}))
            request_ticks(ws)

        def request_ticks(ws):
            # Subscribe to the candlestick channel
            params = {
                "op": "subscribe",
                "args": [
                    f"kline.{self.granularity}.{self.symbol}"
                ]
            }
            s = json.dumps(params)
            self.log(s)
            ws.send(s)

        def on_message(ws, message):
            data = json.loads(message)
            if "success" in data:
                if not data['success']:
                    self.log("Failed:", data)
                return
            if "topic" in data:
                op, _, symbol = data['topic'].split('.')
                consumer = BybitLiveData.get_consumer(symbol)
                if op == "kline":
                    for candle in data["data"]:
                        if candle["confirm"]:
                            consumer.log(f"candle: {candle}")
                            ts = int(candle["start"])
                            c = {
                                "epoch": int(ts / 1000),
                                "open": float(candle["open"]),
                                "high": float(candle["high"]),
                                "low": float(candle["low"]),
                                "close": float(candle["close"]),
                                "volume": 1 #float(candle["volume"]),
                            }
                            consumer.last_epoch = c['epoch']
                            #consumer.ohlc['close'] = c['close']
                            #consumer.log(f"WS bar queued for epoch: {consumer.last_epoch}: {c}")
                            consumer.md.put(c)

        def on_error(ws, message):
            self.log(f"[BybitLiveData] on_error: {repr(message)}")

        def on_close(ws, close_status_code, close_msg):
            self.log(f"[BybitLiveData] WebSocket closed: {close_status_code} - {close_msg}")
        
        def run_ws():
            if BybitLiveData.shared_ws is None:
                BybitLiveData.shared_ws  = websocket.WebSocketApp(f"wss://stream.bybit.com/v5/public/linear",
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close
                )
                self.ws = BybitLiveData.shared_ws
                BybitLiveData.shared_ws.run_forever()

        BybitLiveData.consumers[self.symbol] = self
        if BybitLiveData.shared_ws_thread is None:
            BybitLiveData.shared_ws_thread = threading.Thread(target=run_ws)
            BybitLiveData.shared_ws_thread.daemon = True
            BybitLiveData.shared_ws_thread.start()
            time.sleep(2)
        else:
            self.ws = BybitLiveData.shared_ws
            request_ticks(self.ws)

