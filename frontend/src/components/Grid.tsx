import React, { useMemo } from "react";
import type { RoundData } from "../hooks/useContract";
import { COLORS, formatMult } from "../constants";

interface Props {
  price: number;
  round: RoundData | null;
  onBetUp: () => void;
  onBetDown: () => void;
  change1m: number;
}

const LEVELS = 10; // niveaux au-dessus et en dessous
const STEP   = 5;  // pas en points SPX (ex: 5200, 5205, 5210...)

export function Grid({ price, round, onBetUp, onBetDown, change1m }: Props) {
  // Génère les niveaux de prix autour du prix actuel
  const levels = useMemo(() => {
    if (!price) return [];
    const base = Math.round(price / STEP) * STEP;
    const rows = [];
    for (let i = LEVELS; i >= -LEVELS; i--) {
      rows.push(base + i * STEP);
    }
    return rows;
  }, [price]);

  const upMult   = round ? Number(round.upMult)   / 100 : 2.0;
  const downMult = round ? Number(round.downMult) / 100 : 2.0;
  const totalUp   = round ? Number(round.longAmount)  / 1e6 : 0;
  const totalDown = round ? Number(round.shortAmount) / 1e6 : 0;

  const priceColor = change1m >= 0 ? COLORS.green : COLORS.red;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflowY: "auto" }}>
      {levels.map((lvl) => {
        const isCurrent = Math.abs(lvl - price) < STEP / 2;
        const isAbove   = lvl > price;

        // Calcule un "pool fictif" pour afficher les tailles des cases
        const distancePct = Math.abs(lvl - price) / price;
        const barWidth    = Math.max(5, Math.min(90, 100 - distancePct * 2000));

        return (
          <div
            key={lvl}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 80px 1fr",
              alignItems: "center",
              padding: "3px 8px",
              minHeight: 38,
              borderBottom: isCurrent
                ? `1px solid ${COLORS.accent}88`
                : "1px solid transparent",
              background: isCurrent ? COLORS.accent + "18" : "transparent",
            }}
          >
            {/* Colonne gauche — DOWN */}
            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                alignItems: "center",
                gap: 4,
              }}
            >
              {!isAbove && (
                <div
                  style={{
                    background: COLORS.red + "22",
                    border: `1px solid ${COLORS.red}55`,
                    borderRadius: 6,
                    padding: "3px 8px",
                    fontSize: 11,
                    color: COLORS.red,
                    fontWeight: 600,
                    minWidth: 48,
                    textAlign: "center",
                    width: `${barWidth}%`,
                  }}
                >
                  {downMult.toFixed(2)}×
                </div>
              )}
            </div>

            {/* Colonne centre — prix */}
            <div
              style={{
                textAlign: "center",
                fontSize: isCurrent ? 13 : 11,
                fontWeight: isCurrent ? 700 : 400,
                color: isCurrent ? priceColor : COLORS.subtext,
                background: isCurrent ? COLORS.accent + "11" : "transparent",
                borderRadius: 4,
                padding: "2px 4px",
              }}
            >
              {isCurrent
                ? `$${price.toFixed(2)}`
                : `$${lvl.toFixed(0)}`}
            </div>

            {/* Colonne droite — UP */}
            <div
              style={{
                display: "flex",
                justifyContent: "flex-start",
                alignItems: "center",
                gap: 4,
              }}
            >
              {isAbove && (
                <div
                  style={{
                    background: COLORS.green + "22",
                    border: `1px solid ${COLORS.green}55`,
                    borderRadius: 6,
                    padding: "3px 8px",
                    fontSize: 11,
                    color: COLORS.green,
                    fontWeight: 600,
                    minWidth: 48,
                    textAlign: "center",
                    width: `${barWidth}%`,
                  }}
                >
                  {upMult.toFixed(2)}×
                </div>
              )}
            </div>
          </div>
        );
      })}

      {/* Pool info + Boutons de mise */}
      <div style={{
        position: "sticky",
        bottom: 0,
        background: COLORS.surface,
        borderTop: `1px solid ${COLORS.muted}44`,
        padding: "10px 16px",
        display: "flex",
        gap: 10,
        alignItems: "center",
      }}>
        {/* DOWN */}
        <div style={{ flex: 1, textAlign: "center" }}>
          <div style={{ fontSize: 10, color: COLORS.red, marginBottom: 3 }}>
            Pool: ${totalDown.toFixed(0)} USDC
          </div>
          <button
            onClick={onBetDown}
            style={{
              width: "100%",
              padding: "10px",
              background: COLORS.red + "22",
              border: `1px solid ${COLORS.red}`,
              borderRadius: 10,
              color: COLORS.red,
              fontWeight: 700,
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            ↓ DOWN  {downMult.toFixed(2)}×
          </button>
        </div>

        {/* Timer / round info */}
        <RoundTimer round={round} />

        {/* UP */}
        <div style={{ flex: 1, textAlign: "center" }}>
          <div style={{ fontSize: 10, color: COLORS.green, marginBottom: 3 }}>
            Pool: ${totalUp.toFixed(0)} USDC
          </div>
          <button
            onClick={onBetUp}
            style={{
              width: "100%",
              padding: "10px",
              background: COLORS.green + "22",
              border: `1px solid ${COLORS.green}`,
              borderRadius: 10,
              color: COLORS.green,
              fontWeight: 700,
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            ↑ UP  {upMult.toFixed(2)}×
          </button>
        </div>
      </div>
    </div>
  );
}

function RoundTimer({ round }: { round: RoundData | null }) {
  const [remaining, setRemaining] = React.useState<number>(0);

  React.useEffect(() => {
    if (!round) return;
    const update = () => {
      const now  = Math.floor(Date.now() / 1000);
      const diff = Number(round.closeTimestamp) - now;
      setRemaining(Math.max(0, diff));
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [round]);

  const locked = round
    ? Math.floor(Date.now() / 1000) >= Number(round.lockTimestamp)
    : false;

  const mm  = String(Math.floor(remaining / 60)).padStart(2, "0");
  const ss  = String(remaining % 60).padStart(2, "0");

  return (
    <div style={{ textAlign: "center", minWidth: 52 }}>
      <div style={{
        fontSize: 18,
        fontWeight: 700,
        color: locked ? COLORS.muted : COLORS.accent,
        fontVariantNumeric: "tabular-nums",
      }}>
        {mm}:{ss}
      </div>
      <div style={{ fontSize: 9, color: COLORS.muted }}>
        {locked ? "LOCKED" : `#${round?.epoch?.toString() ?? "—"}`}
      </div>
    </div>
  );
}
