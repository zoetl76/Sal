import { useState, useEffect, useRef } from "react";

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export function usePriceFeed() {
  const [price, setPrice]       = useState<number>(0);
  const [candles, setCandles]   = useState<Candle[]>([]);
  const [change1m, setChange1m] = useState<number>(0);
  const wsRef = useRef<WebSocket | null>(null);

  // Fetch candles historiques au démarrage
  useEffect(() => {
    fetch(`${API_BASE}/candles`)
      .then((r) => r.json())
      .then((data: Candle[]) => {
        setCandles(data);
        if (data.length > 0) {
          const last = data[data.length - 1];
          setPrice(last.close);
          if (data.length > 1) {
            const prev = data[data.length - 2];
            setChange1m(((last.close - prev.close) / prev.close) * 100);
          }
        }
      })
      .catch(console.error);
  }, []);

  // WebSocket pour prix en temps réel
  useEffect(() => {
    const wsUrl = (API_BASE + "/ws/price")
      .replace("http://", "ws://")
      .replace("https://", "wss://");

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.price) {
          setPrice(data.price);
          setChange1m(data.change1m ?? 0);
        }
        if (data.candle) {
          setCandles((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.time === data.candle.time) {
              return [...prev.slice(0, -1), data.candle];
            }
            return [...prev, data.candle];
          });
        }
      };

      ws.onclose = () => setTimeout(connect, 3000); // reconnect
      ws.onerror = () => ws.close();
    };

    connect();
    return () => wsRef.current?.close();
  }, []);

  return { price, candles, change1m };
}
