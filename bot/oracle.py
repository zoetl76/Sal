"""
Oracle SAL — serveur API + WebSocket + oracle on-chain.

Rôles:
  1. Fetch le prix S&P 500 toutes les 30s via yfinance
  2. Expose /candles, /round, /ws/price pour le frontend
  3. Poste le prix au smart contract toutes les 5 minutes (executeRound)

Variables d'environnement:
  ORACLE_PRIVATE_KEY    — clé privée du compte oracle
  CONTRACT_ADDRESS      — adresse du contrat SP500Market
  POLYGON_RPC_URL       — RPC Polygon
  PORT                  — port du serveur (défaut 8000)
"""

import os
import asyncio
import json
import time
import logging
from collections import deque
from datetime import datetime, timezone

import yfinance as yf
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────

ORACLE_KEY       = os.getenv("ORACLE_PRIVATE_KEY", "")
CONTRACT_ADDR    = os.getenv("CONTRACT_ADDRESS", "")
POLYGON_RPC      = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
PORT             = int(os.getenv("PORT", 8000))
ROUND_INTERVAL   = 300  # secondes
PRICE_INTERVAL   = 30   # refresh prix

# ─────────────────────────────────────────────────────────────
#  État partagé
# ─────────────────────────────────────────────────────────────

candles: deque = deque(maxlen=200)   # dernières 200 bougies 1min
current_price: float = 0.0
change_1m: float = 0.0
connected_ws: set[WebSocket] = set()
genesis_done: bool = False
next_round_at: float = 0.0

# ─────────────────────────────────────────────────────────────
#  Web3 — contract oracle
# ─────────────────────────────────────────────────────────────

def load_abi() -> list:
    abi_path = os.path.join(os.path.dirname(__file__), "../frontend/src/abi/SP500Market.json")
    with open(abi_path) as f:
        data = json.load(f)
    return data.get("abi", data)

def get_contract():
    if not ORACLE_KEY or not CONTRACT_ADDR:
        return None, None
    w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
    account = w3.eth.account.from_key(ORACLE_KEY)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CONTRACT_ADDR),
        abi=load_abi(),
    )
    return w3, contract, account

async def send_oracle_tx(func_name: str, *args):
    """Envoie une transaction oracle au contrat."""
    try:
        w3, contract, account = get_contract()
        if not w3:
            log.warning("Oracle non configuré (ORACLE_PRIVATE_KEY manquant)")
            return
        fn = getattr(contract.functions, func_name)(*args)
        gas = fn.estimate_gas({"from": account.address})
        nonce = w3.eth.get_transaction_count(account.address)
        tx = fn.build_transaction({
            "from":     account.address,
            "gas":      int(gas * 1.2),
            "gasPrice": w3.eth.gas_price,
            "nonce":    nonce,
            "chainId":  137,
        })
        signed = w3.eth.account.sign_transaction(tx, ORACLE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        log.info(f"Oracle tx {func_name}: {tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        log.info(f"Oracle tx confirmée: block {receipt['blockNumber']}")
    except Exception as e:
        log.error(f"Oracle tx erreur ({func_name}): {e}")

# ─────────────────────────────────────────────────────────────
#  Fetch prix S&P 500
# ─────────────────────────────────────────────────────────────

def price_to_contract(price: float) -> int:
    """Convertit prix float → uint256 (×100, sans décimales)."""
    return int(round(price * 100))

def fetch_spx_price() -> float | None:
    """Récupère le dernier prix SPX via yfinance."""
    try:
        ticker = yf.Ticker("^GSPC")
        hist   = ticker.history(period="1d", interval="1m")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        log.error(f"yfinance error: {e}")
        return None

def build_candle(hist_row, timestamp: int) -> dict:
    return {
        "time":  timestamp,
        "open":  round(float(hist_row["Open"]), 2),
        "high":  round(float(hist_row["High"]), 2),
        "low":   round(float(hist_row["Low"]), 2),
        "close": round(float(hist_row["Close"]), 2),
    }

async def init_candles():
    """Charge les 200 dernières bougies 1min au démarrage."""
    global current_price, change_1m
    log.info("Chargement de l'historique S&P 500...")
    try:
        hist = yf.Ticker("^GSPC").history(period="3d", interval="1m")
        if hist.empty:
            return
        hist = hist.tail(200)
        for ts, row in hist.iterrows():
            epoch = int(ts.timestamp())
            candles.append(build_candle(row, epoch))
        last = candles[-1]
        prev = candles[-2] if len(candles) > 1 else last
        current_price = last["close"]
        change_1m = (last["close"] - prev["close"]) / prev["close"] * 100
        log.info(f"Historique chargé: {len(candles)} bougies, prix={current_price:.2f}")
    except Exception as e:
        log.error(f"Erreur init candles: {e}")

# ─────────────────────────────────────────────────────────────
#  Boucles async
# ─────────────────────────────────────────────────────────────

async def price_loop():
    """Met à jour le prix toutes les 30s et broadcast aux WS."""
    global current_price, change_1m
    while True:
        price = fetch_spx_price()
        if price:
            prev = current_price
            current_price = price
            change_1m = (price - prev) / prev * 100 if prev else 0

            now = int(time.time())
            minute_ts = now - (now % 60)
            candle = {
                "time": minute_ts,
                "open": prev or price,
                "high": max(prev or price, price),
                "low":  min(prev or price, price),
                "close": price,
            }

            msg = json.dumps({
                "price":   round(price, 2),
                "change1m": round(change_1m, 4),
                "candle":  candle,
            })
            for ws in list(connected_ws):
                try:
                    await ws.send_text(msg)
                except Exception:
                    connected_ws.discard(ws)

        await asyncio.sleep(PRICE_INTERVAL)

async def oracle_loop():
    """Lance les rounds toutes les 5 minutes."""
    global genesis_done, next_round_at
    await asyncio.sleep(5)  # attendre que le prix soit chargé

    while True:
        now = time.time()
        if not genesis_done:
            if current_price > 0:
                price_int = price_to_contract(current_price)
                log.info(f"Genesis round: {current_price:.2f} ({price_int})")
                await send_oracle_tx("genesisStartRound", price_int)
                genesis_done = True
                next_round_at = now + ROUND_INTERVAL
            await asyncio.sleep(10)
            continue

        if now >= next_round_at:
            if current_price > 0:
                close_int = price_to_contract(current_price)
                new_int   = price_to_contract(current_price)
                log.info(f"Execute round: close={current_price:.2f}")
                await send_oracle_tx("executeRound", close_int, new_int)
                next_round_at = now + ROUND_INTERVAL
        await asyncio.sleep(15)

# ─────────────────────────────────────────────────────────────
#  FastAPI
# ─────────────────────────────────────────────────────────────

app = FastAPI(title="SAL Oracle API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await init_candles()
    asyncio.create_task(price_loop())
    asyncio.create_task(oracle_loop())

@app.get("/candles")
async def get_candles():
    return list(candles)

@app.get("/round")
async def get_round():
    now = time.time()
    secs_left = max(0, int(next_round_at - now))
    return {
        "price":      round(current_price, 2),
        "change1m":   round(change_1m, 4),
        "seconds_left": secs_left,
        "genesis_done": genesis_done,
        # Ces valeurs seraient idéalement lues depuis le contrat
        "up_mult":    2.0,
        "down_mult":  2.0,
        "long_usdc":  0,
        "short_usdc": 0,
    }

@app.get("/price")
async def get_price():
    return {"price": round(current_price, 2), "change1m": round(change_1m, 4)}

@app.websocket("/ws/price")
async def ws_price(ws: WebSocket):
    await ws.accept()
    connected_ws.add(ws)
    # Envoie l'état courant immédiatement
    await ws.send_text(json.dumps({
        "price":    round(current_price, 2),
        "change1m": round(change_1m, 4),
    }))
    try:
        while True:
            await ws.receive_text()  # keep-alive
    except WebSocketDisconnect:
        connected_ws.discard(ws)

if __name__ == "__main__":
    uvicorn.run("oracle:app", host="0.0.0.0", port=PORT, reload=False)
