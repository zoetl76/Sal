import { useState, useEffect, useCallback } from "react";
import { Contract, JsonRpcSigner, JsonRpcProvider, formatUnits } from "ethers";
import { CONTRACT_ADDRESS, USDC_ADDRESS, RPC_URL } from "../constants";
import SP500MarketABI from "../abi/SP500Market.json";

const USDC_ABI = [
  "function balanceOf(address) view returns (uint256)",
  "function allowance(address,address) view returns (uint256)",
  "function approve(address,uint256) returns (bool)",
];

export interface RoundData {
  epoch: bigint;
  startTimestamp: bigint;
  lockTimestamp: bigint;
  closeTimestamp: bigint;
  startPrice: bigint;
  closePrice: bigint;
  longAmount: bigint;
  shortAmount: bigint;
  oracleCalled: boolean;
  upMult: bigint;
  downMult: bigint;
}

export function useContract(signer: JsonRpcSigner | null) {
  const [currentEpoch, setCurrentEpoch]   = useState<bigint>(0n);
  const [currentRound, setCurrentRound]   = useState<RoundData | null>(null);
  const [usdcBalance, setUsdcBalance]     = useState<bigint>(0n);
  const [pendingClaims, setPendingClaims] = useState<bigint[]>([]);
  const [loading, setLoading]             = useState(false);
  const [txHash, setTxHash]               = useState<string | null>(null);

  const readProvider = new JsonRpcProvider(RPC_URL);

  const marketRead = new Contract(
    CONTRACT_ADDRESS,
    SP500MarketABI.abi ?? SP500MarketABI,
    readProvider
  );

  const marketWrite = signer
    ? new Contract(CONTRACT_ADDRESS, SP500MarketABI.abi ?? SP500MarketABI, signer)
    : null;

  const usdcRead = new Contract(USDC_ADDRESS, USDC_ABI, readProvider);
  const usdcWrite = signer ? new Contract(USDC_ADDRESS, USDC_ABI, signer) : null;

  const refresh = useCallback(async () => {
    try {
      const epoch: bigint = await marketRead.currentEpoch();
      setCurrentEpoch(epoch);

      if (epoch > 0n) {
        const r = await marketRead.rounds(epoch);
        const [upMult, downMult] = await marketRead.getMultipliers(epoch);
        setCurrentRound({
          epoch: r.epoch,
          startTimestamp: r.startTimestamp,
          lockTimestamp: r.lockTimestamp,
          closeTimestamp: r.closeTimestamp,
          startPrice: r.startPrice,
          closePrice: r.closePrice,
          longAmount: r.longAmount,
          shortAmount: r.shortAmount,
          oracleCalled: r.oracleCalled,
          upMult,
          downMult,
        });
      }
    } catch (_) {
      // Contrat non encore déployé
    }
  }, []);

  const refreshBalance = useCallback(async (address: string) => {
    try {
      const bal: bigint = await usdcRead.balanceOf(address);
      setUsdcBalance(bal);
    } catch (_) {}
  }, []);

  // Auto-refresh toutes les 10s
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10_000);
    return () => clearInterval(id);
  }, [refresh]);

  const betUp = useCallback(async (amount: bigint) => {
    if (!marketWrite || !usdcWrite || !signer) return;
    setLoading(true);
    setTxHash(null);
    try {
      // Approve USDC si nécessaire
      const address = await signer.getAddress();
      const allowance: bigint = await usdcRead.allowance(address, CONTRACT_ADDRESS);
      if (allowance < amount) {
        const approveTx = await usdcWrite.approve(CONTRACT_ADDRESS, amount * 10n);
        await approveTx.wait();
      }
      const tx = await marketWrite.betUp(currentEpoch, amount);
      setTxHash(tx.hash);
      await tx.wait();
      await refresh();
    } catch (e: any) {
      console.error("betUp error:", e.message);
    } finally {
      setLoading(false);
    }
  }, [marketWrite, usdcWrite, currentEpoch, refresh]);

  const betDown = useCallback(async (amount: bigint) => {
    if (!marketWrite || !usdcWrite || !signer) return;
    setLoading(true);
    setTxHash(null);
    try {
      const address = await signer.getAddress();
      const allowance: bigint = await usdcRead.allowance(address, CONTRACT_ADDRESS);
      if (allowance < amount) {
        const approveTx = await usdcWrite.approve(CONTRACT_ADDRESS, amount * 10n);
        await approveTx.wait();
      }
      const tx = await marketWrite.betDown(currentEpoch, amount);
      setTxHash(tx.hash);
      await tx.wait();
      await refresh();
    } catch (e: any) {
      console.error("betDown error:", e.message);
    } finally {
      setLoading(false);
    }
  }, [marketWrite, usdcWrite, currentEpoch, refresh]);

  const claimAll = useCallback(async () => {
    if (!marketWrite || pendingClaims.length === 0) return;
    setLoading(true);
    try {
      const tx = await marketWrite.claim(pendingClaims);
      setTxHash(tx.hash);
      await tx.wait();
      setPendingClaims([]);
      await refresh();
    } catch (e: any) {
      console.error("claim error:", e.message);
    } finally {
      setLoading(false);
    }
  }, [marketWrite, pendingClaims, refresh]);

  return {
    currentEpoch,
    currentRound,
    usdcBalance,
    pendingClaims,
    loading,
    txHash,
    betUp,
    betDown,
    claimAll,
    refresh,
    refreshBalance,
  };
}
