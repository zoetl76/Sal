import React, { useEffect, useRef } from "react";
import { createChart, CandlestickSeries, IChartApi } from "lightweight-charts";
import type { Candle } from "../hooks/usePriceFeed";
import { COLORS } from "../constants";

interface Props {
  candles: Candle[];
  height?: number;
}

export function Chart({ candles, height = 160 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);
  const seriesRef    = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: "transparent" },
        textColor: COLORS.subtext,
      },
      grid: {
        vertLines: { color: COLORS.muted + "22" },
        horzLines: { color: COLORS.muted + "22" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: {
        borderColor: COLORS.muted + "44",
        textColor: COLORS.subtext,
      },
      timeScale: {
        borderColor: COLORS.muted + "44",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor:          COLORS.green,
      downColor:        COLORS.red,
      borderUpColor:    COLORS.green,
      borderDownColor:  COLORS.red,
      wickUpColor:      COLORS.green,
      wickDownColor:    COLORS.red,
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: containerRef.current!.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [height]);

  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return;
    seriesRef.current.setData(candles);
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height, background: "transparent" }}
    />
  );
}
