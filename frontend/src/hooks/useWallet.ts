import { useState, useCallback, useEffect } from "react";
import { BrowserProvider, JsonRpcSigner } from "ethers";
import { CHAIN_ID, RPC_URL, CHAIN_NAME } from "../constants";

interface WalletState {
  address: string | null;
  signer: JsonRpcSigner | null;
  usdcBalance: bigint;
  connecting: boolean;
  error: string | null;
}

declare global {
  interface Window {
    ethereum?: any;
    Telegram?: any;
  }
}

export function useWallet() {
  const [state, setState] = useState<WalletState>({
    address: null,
    signer: null,
    usdcBalance: 0n,
    connecting: false,
    error: null,
  });

  const connect = useCallback(async () => {
    if (!window.ethereum) {
      setState((s) => ({ ...s, error: "MetaMask non détecté. Ouvre dans un wallet browser." }));
      return;
    }
    setState((s) => ({ ...s, connecting: true, error: null }));
    try {
      await window.ethereum.request({ method: "eth_requestAccounts" });

      // Switcher sur Polygon si besoin
      try {
        await window.ethereum.request({
          method: "wallet_switchEthereumChain",
          params: [{ chainId: `0x${CHAIN_ID.toString(16)}` }],
        });
      } catch (switchErr: any) {
        if (switchErr.code === 4902) {
          await window.ethereum.request({
            method: "wallet_addEthereumChain",
            params: [{
              chainId: `0x${CHAIN_ID.toString(16)}`,
              chainName: CHAIN_NAME,
              nativeCurrency: { name: "MATIC", symbol: "MATIC", decimals: 18 },
              rpcUrls: [RPC_URL],
              blockExplorerUrls: ["https://polygonscan.com"],
            }],
          });
        }
      }

      const provider = new BrowserProvider(window.ethereum);
      const signer   = await provider.getSigner();
      const address  = await signer.getAddress();

      setState((s) => ({ ...s, address, signer, connecting: false }));
    } catch (e: any) {
      setState((s) => ({ ...s, connecting: false, error: e.message }));
    }
  }, []);

  const disconnect = useCallback(() => {
    setState({ address: null, signer: null, usdcBalance: 0n, connecting: false, error: null });
  }, []);

  // Écoute les changements de compte
  useEffect(() => {
    if (!window.ethereum) return;
    const handler = () => disconnect();
    window.ethereum.on("accountsChanged", handler);
    window.ethereum.on("chainChanged", handler);
    return () => {
      window.ethereum?.removeListener("accountsChanged", handler);
      window.ethereum?.removeListener("chainChanged", handler);
    };
  }, [disconnect]);

  return { ...state, connect, disconnect };
}
