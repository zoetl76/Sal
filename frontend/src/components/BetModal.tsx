import React, { useState } from "react";
import { COLORS, formatUsdc } from "../constants";

interface Props {
  direction: "UP" | "DOWN";
  multiplier: number;
  usdcBalance: bigint;
  loading: boolean;
  onConfirm: (amount: bigint) => void;
  onClose: () => void;
}

const PRESETS = [1, 5, 10, 25, 50];

export function BetModal({ direction, multiplier, usdcBalance, loading, onConfirm, onClose }: Props) {
  const [amount, setAmount] = useState<string>("5");

  const usdcBal = Number(usdcBalance) / 1e6;
  const amountNum = parseFloat(amount) || 0;
  const payout = amountNum * multiplier;

  const color = direction === "UP" ? COLORS.green : COLORS.red;
  const arrow = direction === "UP" ? "↑" : "↓";

  const handleConfirm = () => {
    if (amountNum < 1 || amountNum > usdcBal) return;
    const amountRaw = BigInt(Math.floor(amountNum * 1e6));
    onConfirm(amountRaw);
  };

  return (
    <div style={{
      position: "fixed",
      inset: 0,
      background: "#00000099",
      display: "flex",
      alignItems: "flex-end",
      zIndex: 100,
    }}>
      <div style={{
        width: "100%",
        background: COLORS.surface,
        borderRadius: "20px 20px 0 0",
        padding: "20px 20px 36px",
      }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
          <div style={{ fontSize: 18, fontWeight: 700, color }}>
            {arrow} {direction} — {multiplier.toFixed(2)}×
          </div>
          <button
            onClick={onClose}
            style={{
              background: "none", border: "none", color: COLORS.muted,
              fontSize: 22, cursor: "pointer",
            }}
          >
            ×
          </button>
        </div>

        {/* Balance */}
        <div style={{
          fontSize: 12, color: COLORS.subtext, marginBottom: 10,
          textAlign: "right",
        }}>
          Solde: {usdcBal.toFixed(2)} USDC
        </div>

        {/* Presets */}
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          {PRESETS.map((p) => (
            <button
              key={p}
              onClick={() => setAmount(String(p))}
              style={{
                flex: 1,
                padding: "6px 0",
                background: amount === String(p) ? color + "33" : COLORS.bg,
                border: `1px solid ${amount === String(p) ? color : COLORS.muted + "44"}`,
                borderRadius: 8,
                color: amount === String(p) ? color : COLORS.subtext,
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              ${p}
            </button>
          ))}
          <button
            onClick={() => setAmount(String(Math.floor(usdcBal)))}
            style={{
              flex: 1,
              padding: "6px 0",
              background: COLORS.bg,
              border: `1px solid ${COLORS.muted}44`,
              borderRadius: 8,
              color: COLORS.subtext,
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            MAX
          </button>
        </div>

        {/* Input */}
        <div style={{
          display: "flex",
          alignItems: "center",
          background: COLORS.bg,
          border: `1px solid ${COLORS.muted}55`,
          borderRadius: 12,
          padding: "10px 16px",
          marginBottom: 16,
          gap: 8,
        }}>
          <span style={{ color: COLORS.subtext, fontSize: 16 }}>$</span>
          <input
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            min="1"
            step="1"
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              outline: "none",
              color: COLORS.text,
              fontSize: 24,
              fontWeight: 700,
              textAlign: "center",
            }}
          />
          <span style={{ color: COLORS.subtext, fontSize: 12 }}>USDC</span>
        </div>

        {/* Payout preview */}
        <div style={{
          background: color + "11",
          border: `1px solid ${color}33`,
          borderRadius: 10,
          padding: "10px 16px",
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 20,
        }}>
          <span style={{ color: COLORS.subtext, fontSize: 13 }}>Gain potentiel</span>
          <span style={{ color, fontWeight: 700, fontSize: 16 }}>
            ${payout.toFixed(2)} USDC
          </span>
        </div>

        {/* Confirm */}
        <button
          onClick={handleConfirm}
          disabled={loading || amountNum < 1 || amountNum > usdcBal}
          style={{
            width: "100%",
            padding: "14px",
            background: loading || amountNum < 1 ? COLORS.muted : color,
            border: "none",
            borderRadius: 14,
            color: "#fff",
            fontSize: 16,
            fontWeight: 700,
            cursor: loading ? "wait" : "pointer",
          }}
        >
          {loading ? "Transaction en cours..." : `Miser ${amountNum || 0} USDC ${arrow} ${direction}`}
        </button>
      </div>
    </div>
  );
}
