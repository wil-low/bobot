import json
import threading
import time
import websocket
import backtrader as bt
from datetime import datetime, timezone
from feed.datafeed import BobotLiveDataBase

class DerivLiveData(BobotLiveDataBase):
    """
    A Backtrader live data feed that connects to Deriv WebSocket and streams tick data.
    """

    shared_ws = None
    shared_ws_thread = None
    consumers = {}  # symbol: DerivLiveData

    def __init__(self, logger, app_id, symbol, granularity, history_size, history_only):
        super().__init__(logger, symbol, granularity, history_size)
        self.app_id = app_id
        self.history_only = history_only

    def start(self):
        super().start()
        self.log(f"DerivLiveData::start")
        self._start_ws()

    def get_consumer(symbol):
        return DerivLiveData.consumers[symbol]

    def _start_ws(self):
        def on_open(ws):
            self.log("WebSocket connected.")
            self.keep_alive(json.dumps({'ping': 1}))
            request_ticks(ws)

        def request_ticks(ws):
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
            time.sleep(1)

        def on_message(ws, message):
            #self.log(f"datafeed: {message}")
            data = json.loads(message)
            if "error" in data:
                self.log(f"ERROR in {data['msg_type']}: {data['error']['message']}")
            else:
                if data['msg_type'] == 'candles':
                    consumer = DerivLiveData.get_consumer(data['echo_req']['ticks_history'])
                    # historical MD
                    #consumer.log(data)
                    candle_count = len(data['candles'])
                    consumer.log(f"Historical candles: {candle_count}")
                    for i in range(candle_count):
                        candle = data['candles'][i]
                        if self.history_only and i == candle_count - 1:
                            candle['volume'] = 1  # last candle marked as real-time
                        else:
                            candle['volume'] = 0
                        consumer.ohlc['close'] = candle['close']
                        consumer.md.put(candle)
                    consumer.reset_ohlc()
                    if not self.history_only:
                        ws.send(json.dumps({
                            "ticks": consumer.symbol,
                            "subscribe": 1
                        }))
                elif data['msg_type'] == 'tick':
                    # real-time MD
                    consumer = DerivLiveData.get_consumer(data['tick']['symbol'])
                    #consumer.log(data)
                    consumer.update_ohlc(data['tick']['epoch'], data['tick']['quote'])
                    epoch = consumer.ohlc['epoch']
                    if epoch % consumer.granularity == 0:
                        if consumer.last_ts < epoch:
                            consumer.log(f"New bar {epoch}: {str(consumer.ohlc)}")
                            consumer.md.put(consumer.ohlc.copy())  # Use copy to avoid overwriting
                            consumer.last_ts = epoch           # ✅ only update after queuing
                            consumer.reset_ohlc()
                        else:
                            consumer.log(f"Duplicate epoch skipped: {epoch}")

        def on_error(ws, message):
            self.log(f"[DerivLiveData] on_error: {str(message)}")

        def on_close(ws, close_status_code, close_msg):
            self.log(f"[DerivLiveData] WebSocket closed: {close_status_code} - {close_msg}")

        def run_ws():
            self.log(f"run_ws, app_id={self.app_id}")
            if DerivLiveData.shared_ws is None:
                DerivLiveData.shared_ws = websocket.WebSocketApp(f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}",
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close
                )
                self.ws = DerivLiveData.shared_ws
                DerivLiveData.shared_ws.run_forever()

        DerivLiveData.consumers[self.symbol] = self
        if DerivLiveData.shared_ws_thread is None:
            DerivLiveData.shared_ws_thread = threading.Thread(target=run_ws)
            DerivLiveData.shared_ws_thread.daemon = True
            DerivLiveData.shared_ws_thread.start()
            time.sleep(2)
        else:
            self.ws = DerivLiveData.shared_ws
            request_ticks(self.ws)

