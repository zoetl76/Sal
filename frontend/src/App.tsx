import React, { useState, useEffect } from "react";
import { Header }   from "./components/Header";
import { Chart }    from "./components/Chart";
import { Grid }     from "./components/Grid";
import { BetModal } from "./components/BetModal";
import { useWallet }    from "./hooks/useWallet";
import { useContract }  from "./hooks/useContract";
import { usePriceFeed } from "./hooks/usePriceFeed";
import { COLORS } from "./constants";

declare global {
  interface Window { Telegram?: { WebApp?: any }; }
}

export default function App() {
  const wallet   = useWallet();
  const feed     = usePriceFeed();
  const contract = useContract(wallet.signer);

  const [modal, setModal] = useState<"UP" | "DOWN" | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // Initialiser Telegram WebApp
  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    if (tg) {
      tg.ready();
      tg.expand();
      tg.enableClosingConfirmation();
    }
  }, []);

  // Rafraîchir le solde USDC quand le wallet est connecté
  useEffect(() => {
    if (wallet.address) {
      contract.refreshBalance(wallet.address);
    }
  }, [wallet.address]);

  // Toast sur tx confirmée
  useEffect(() => {
    if (contract.txHash) {
      showToast("✅ Transaction confirmée !");
    }
  }, [contract.txHash]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const handleBet = async (direction: "UP" | "DOWN", amount: bigint) => {
    if (!wallet.address) {
      showToast("Connecte ton wallet d'abord !");
      return;
    }
    setModal(null);
    if (direction === "UP") {
      await contract.betUp(amount);
    } else {
      await contract.betDown(amount);
    }
    await contract.refreshBalance(wallet.address!);
  };

  const upMult   = contract.currentRound ? Number(contract.currentRound.upMult)   / 100 : 2.0;
  const downMult = contract.currentRound ? Number(contract.currentRound.downMult) / 100 : 2.0;
  const change1m  = feed.change1m;

  return (
    <div style={{
      height: "100dvh",
      display: "flex",
      flexDirection: "column",
      background: COLORS.bg,
      position: "relative",
      overflow: "hidden",
    }}>
      {/* Header */}
      <Header
        address={wallet.address}
        usdcBalance={contract.usdcBalance}
        onConnect={wallet.connect}
        connecting={wallet.connecting}
      />

      {/* Prix actuel */}
      <div style={{
        padding: "8px 16px 0",
        display: "flex",
        alignItems: "baseline",
        gap: 10,
      }}>
        <div style={{ fontSize: 28, fontWeight: 800, color: COLORS.text }}>
          S&P 500
        </div>
        <div style={{ fontSize: 22, fontWeight: 700, color: change1m >= 0 ? COLORS.green : COLORS.red }}>
          {feed.price > 0 ? `$${feed.price.toFixed(2)}` : "—"}
        </div>
        <div style={{
          fontSize: 13,
          color: change1m >= 0 ? COLORS.green : COLORS.red,
          fontWeight: 600,
        }}>
          {change1m >= 0 ? "+" : ""}{change1m.toFixed(2)}%
        </div>
      </div>

      {/* Chart */}
      <div style={{ padding: "4px 0", flexShrink: 0 }}>
        <Chart candles={feed.candles} height={150} />
      </div>

      {/* Séparateur */}
      <div style={{
        height: 1,
        background: COLORS.muted + "33",
        margin: "0 16px",
      }} />

      {/* Grid + Boutons */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        <Grid
          price={feed.price}
          round={contract.currentRound}
          change1m={change1m}
          onBetUp={() => setModal("UP")}
          onBetDown={() => setModal("DOWN")}
        />
      </div>

      {/* Erreur wallet */}
      {wallet.error && (
        <div style={{
          position: "absolute",
          bottom: 90,
          left: 16,
          right: 16,
          background: COLORS.red + "22",
          border: `1px solid ${COLORS.red}`,
          borderRadius: 10,
          padding: "10px 14px",
          color: COLORS.red,
          fontSize: 12,
        }}>
          {wallet.error}
        </div>
      )}

      {/* Modal de mise */}
      {modal && (
        <BetModal
          direction={modal}
          multiplier={modal === "UP" ? upMult : downMult}
          usdcBalance={contract.usdcBalance}
          loading={contract.loading}
          onConfirm={(amount) => handleBet(modal, amount)}
          onClose={() => setModal(null)}
        />
      )}

      {/* Toast notifications */}
      {toast && (
        <div style={{
          position: "fixed",
          top: 60,
          left: "50%",
          transform: "translateX(-50%)",
          background: COLORS.surface,
          border: `1px solid ${COLORS.accent}`,
          borderRadius: 12,
          padding: "8px 20px",
          color: COLORS.text,
          fontSize: 13,
          fontWeight: 600,
          zIndex: 200,
          whiteSpace: "nowrap",
        }}>
          {toast}
        </div>
      )}
    </div>
  );
}
