# SAL Market — S&P 500 Prediction Market

Application de trading de type Euphoria Finance sur le **S&P 500**, sous forme de **Telegram Mini App** avec intégration **DeFi** sur **Polygon**.

## Architecture

```
├── contract/               # Smart contract Solidity (Hardhat)
│   ├── contracts/
│   │   └── SP500Market.sol # Marché de prédiction UP/DOWN
│   ├── scripts/
│   │   └── deploy.js
│   └── hardhat.config.js
│
├── frontend/               # React + Vite (Telegram Mini App)
│   └── src/
│       ├── App.tsx
│       ├── components/
│       │   ├── Chart.tsx      # Graphique candlestick (TradingView)
│       │   ├── Grid.tsx       # Grille de prix style Euphoria
│       │   ├── BetModal.tsx   # Modal de mise
│       │   └── Header.tsx     # Wallet + solde
│       ├── hooks/
│       │   ├── useWallet.ts   # MetaMask / Polygon
│       │   ├── useContract.ts # Interactions smart contract
│       │   └── usePriceFeed.ts# Prix temps réel (WebSocket)
│       └── abi/
│           └── SP500Market.json
│
└── bot/                    # Python — Telegram bot + Oracle API
    ├── bot.py              # Bot Telegram (lance la Mini App)
    └── oracle.py           # API FastAPI + WebSocket + oracle on-chain
```

## Fonctionnement

| Élément | Détail |
|---|---|
| **Actif** | S&P 500 (^GSPC via Yahoo Finance) |
| **Round** | 5 minutes — UP ou DOWN |
| **Mise min.** | 1 USDC |
| **Multiplicateur** | Dynamique (parimutuel) — max 100× |
| **Frais** | 3% du pool total |
| **Blockchain** | Polygon Mainnet |
| **Wallet** | MetaMask / WalletConnect |

## Installation et déploiement

### 1. Variables d'environnement
```bash
cp .env.example .env
# Remplir toutes les valeurs
```

### 2. Déployer le smart contract
```bash
cd contract
npm install
npm run deploy:polygon
# L'ABI + adresse sont auto-copiés dans frontend/src/abi/
```

### 3. Frontend (Vercel / Netlify)
```bash
cd frontend
npm install
npm run build        # dist/ prêt à déployer
# Définir VITE_CONTRACT_ADDRESS et VITE_API_URL dans les env vars du host
```

### 4. Oracle + API (Railway / Render)
```bash
cd bot
pip install -r requirements.txt
python oracle.py     # Démarre sur PORT=8000
```

### 5. Bot Telegram
```bash
cd bot
python bot.py        # À tourner en parallèle
```

### 6. Configurer le bot sur Telegram
- Dans @BotFather: `/setmenubutton` → URL de ta Mini App
- Dans @BotFather: `/setdomain` → domaine HTTPS du frontend

## Flux d'un round

```
Oracle → genesisStartRound(price)
  ↓ utilisateurs misent UP ou DOWN
  ↓ (round verrouillé 30s avant fermeture)
Oracle → executeRound(closePrice, newPrice)
  ↓ gagnants clament leurs gains
```

## Contrat SP500Market

| Fonction | Qui | Description |
|---|---|---|
| `genesisStartRound(price)` | Oracle | Lance le 1er round |
| `executeRound(close, new)` | Oracle | Settle + nouveau round |
| `betUp(epoch, amount)` | User | Mise UP en USDC |
| `betDown(epoch, amount)` | User | Mise DOWN en USDC |
| `claim([epochs])` | User | Réclame les gains |
| `getMultipliers(epoch)` | View | Cotes UP / DOWN × 100 |

## Avertissement

Application expérimentale à usage éducatif. Les smart contracts non audités comportent des risques. Tester d'abord sur Mumbai testnet.
