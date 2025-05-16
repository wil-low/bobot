import json
import queue
import threading
import websocket
import backtrader as bt
from datetime import datetime, timezone
from feed.datafeed import BobotLiveDataBase

class DerivLiveData(BobotLiveDataBase):
    """
    A Backtrader live data feed that connects to Deriv WebSocket and streams tick data.
    """

    def __init__(self, logger, app_id, symbol, granularity, history_size):
        super().__init__(logger, symbol, granularity, history_size)
        self.app_id = app_id

    def start(self):
        super().start()
        self._start_ws()

    def _start_ws(self):
        def on_open(ws):
            self.log("WebSocket connected.")
            self.keep_alive(json.dumps({"forget": "00000000000000000000000000000000"}))
            data = json.dumps({
                "ticks_history": self.symbol,
                "adjust_start_time": 1,
                "count": self.history_size,
                "end": "latest",
                "granularity": self.granularity,
                "start": 1,
                "style": "candles"
            })
            self.log(data)
            ws.send(data)

        def on_message(ws, message):
            #self.log(f"datafeed: {message}")
            data = json.loads(message)
            if "error" in data:
                self.log(f"ERROR in {data['msg_type']}: {data['error']['message']}")
            else:
                if data['msg_type'] == 'candles':
                    # historical MD
                    self.log(data)
                    self.log(f"Historical candles: {len(data['candles'])}")
                    for candle in data['candles']:
                        candle['volume'] = 0
                        self.ohlc['close'] = candle['close']
                        self.md.put(candle)
                    self.reset_ohlc()
                    ws.send(json.dumps({
                        "ticks": self.symbol,
                        "subscribe": 1
                    }))
                elif data['msg_type'] == 'tick':
                    # real-time MD
                    #self.log(data)
                    self.update_ohlc(data['tick']['epoch'], data['tick']['quote'])
                    epoch = self.ohlc['epoch']
                    if epoch % self.granularity == 0:
                        if self.last_ts < epoch:
                            self.log(f"New bar {epoch}: {str(self.ohlc)}")
                            self.md.put(self.ohlc.copy())  # Use copy to avoid overwriting
                            self.last_ts = epoch           # ✅ only update after queuing
                            self.reset_ohlc()
                        else:
                            self.log(f"Duplicate epoch skipped: {epoch}")

        def on_error(ws, message):
            self.log(f"[DerivLiveData] on_error: {str(message)}")

        def on_close(ws, close_status_code, close_msg):
            self.log(f"[DerivLiveData] WebSocket closed: {close_status_code} - {close_msg}")

        def run_ws():
            self.log(f"run_ws, app_id={self.app_id}")
            self.ws = websocket.WebSocketApp(f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            self.ws.run_forever()

        self.thread = threading.Thread(target=run_ws)
        self.thread.daemon = True
        self.thread.start()
