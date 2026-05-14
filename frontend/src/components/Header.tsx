import React from "react";
import { COLORS, formatUsdc } from "../constants";

interface Props {
  address: string | null;
  usdcBalance: bigint;
  onConnect: () => void;
  connecting: boolean;
}

export function Header({ address, usdcBalance, onConnect, connecting }: Props) {
  const short = address
    ? address.slice(0, 6) + "..." + address.slice(-4)
    : null;

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "10px 16px",
      background: COLORS.surface,
      borderBottom: `1px solid ${COLORS.muted}33`,
    }}>
      {/* Logo */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8,
          background: COLORS.accent,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontWeight: 900, fontSize: 14, color: "#fff",
        }}>
          S
        </div>
        <span style={{ fontWeight: 700, fontSize: 15, color: COLORS.text }}>
          SAL Market
        </span>
      </div>

      {/* Wallet */}
      {address ? (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            background: COLORS.bg,
            border: `1px solid ${COLORS.muted}55`,
            borderRadius: 20,
            padding: "4px 12px",
            fontSize: 13,
            color: COLORS.subtext,
          }}>
            💵 {formatUsdc(usdcBalance)} USDC
          </div>
          <div style={{
            background: COLORS.bg,
            border: `1px solid ${COLORS.accent}55`,
            borderRadius: 20,
            padding: "4px 12px",
            fontSize: 12,
            color: COLORS.accent,
          }}>
            {short}
          </div>
        </div>
      ) : (
        <button
          onClick={onConnect}
          disabled={connecting}
          style={{
            background: connecting ? COLORS.muted : COLORS.accent,
            border: "none",
            borderRadius: 20,
            padding: "6px 16px",
            color: "#fff",
            fontWeight: 600,
            fontSize: 13,
            cursor: connecting ? "default" : "pointer",
          }}
        >
          {connecting ? "Connexion..." : "Connecter wallet"}
        </button>
      )}
    </div>
  );
}
