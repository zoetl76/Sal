// Adresse du contrat après déploiement (remplacer après `npm run deploy:polygon`)
export const CONTRACT_ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS || "0x0000000000000000000000000000000000000000";

// USDC sur Polygon mainnet
export const USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";

// Polygon Mainnet
export const CHAIN_ID = 137;
export const CHAIN_NAME = "Polygon";
export const RPC_URL = "https://polygon-rpc.com";

// Durée d'un round en secondes
export const ROUND_INTERVAL = 300;

// Prix en display (centimes → dollars)
export const formatPrice = (raw: bigint) => (Number(raw) / 100).toFixed(2);
export const formatUsdc  = (raw: bigint) => (Number(raw) / 1e6).toFixed(2);
export const formatMult  = (raw: bigint) => (Number(raw) / 100).toFixed(2) + "×";

// Couleurs du thème (style Euphoria)
export const COLORS = {
  bg:       "#1a0a2e",
  surface:  "#2d1057",
  accent:   "#e91e8c",
  green:    "#00e5a0",
  red:      "#ff3366",
  muted:    "#7a5fa0",
  text:     "#f0e6ff",
  subtext:  "#9b7fc0",
};
