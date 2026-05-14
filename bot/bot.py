"""
Bot Telegram SAL — lance la Mini App S&P 500.
Variables d'environnement requises:
  TELEGRAM_BOT_TOKEN   — token BotFather
  MINI_APP_URL         — URL HTTPS de la frontend déployée
  ADMIN_CHAT_ID        — ID Telegram de l'admin (notifications)
"""

import os
import logging
import asyncio
import aiohttp
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BOT_TOKEN     = os.environ["TELEGRAM_BOT_TOKEN"]
MINI_APP_URL  = os.environ.get("MINI_APP_URL", "https://your-app.vercel.app")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
API_URL       = os.environ.get("API_URL", "http://localhost:8000")


# ─────────────────────────────────────────────────────────────
#  Commandes
# ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text="🚀 Ouvrir SAL Market",
            web_app=WebAppInfo(url=MINI_APP_URL),
        )
    ]])
    await update.message.reply_html(
        f"👋 Salut <b>{user.first_name}</b> !\n\n"
        "📈 <b>SAL</b> est un marché de prédiction sur le <b>S&P 500</b>.\n\n"
        "• Mises en USDC sur Polygon\n"
        "• Rounds de 5 minutes — UP ↑ ou DOWN ↓\n"
        "• Cotes dynamiques — les gagnants partagent le pool\n\n"
        "Clique ci-dessous pour ouvrir l'application 👇",
        reply_markup=keyboard,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 Commandes disponibles:\n\n"
        "/start  — Ouvre le marché S&P 500\n"
        "/stats  — Round actuel + prix\n"
        "/help   — Ce message\n\n"
        "📊 Règles:\n"
        "1. Connecte MetaMask sur Polygon\n"
        "2. Mise minimum: 1 USDC\n"
        "3. Choisis UP ↑ ou DOWN ↓\n"
        "4. Si tu as raison → gains × multiplicateur\n"
        "5. Rounds de 5 minutes, nouveaux rounds en continu"
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        async with aiohttp.ClientSession() as session:
            price_task = session.get(f"{API_URL}/price")
            round_task = session.get(f"{API_URL}/round")

            async with price_task as pr, round_task as rr:
                price_data = await pr.json() if pr.status == 200 else {}
                round_data = await rr.json() if rr.status == 200 else {}

        price     = price_data.get("price", 0)
        change    = price_data.get("change1m", 0)
        secs      = round_data.get("seconds_left", 0)
        up_mult   = round_data.get("up_mult", 2.0)
        down_mult = round_data.get("down_mult", 2.0)
        up_pool   = round_data.get("long_usdc", 0)
        down_pool = round_data.get("short_usdc", 0)
        mm, ss    = divmod(secs, 60)

        trend = "🟢" if change >= 0 else "🔴"
        sign  = "+" if change >= 0 else ""

        await update.message.reply_text(
            f"{trend} <b>S&P 500 — ${price:.2f}</b> ({sign}{change:.2f}%)\n\n"
            f"⏱ Temps restant: <b>{mm:02d}:{ss:02d}</b>\n\n"
            f"↑ UP   {up_mult:.2f}×   — Pool: <b>${up_pool:.0f} USDC</b>\n"
            f"↓ DOWN {down_mult:.2f}× — Pool: <b>${down_pool:.0f} USDC</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚀 Jouer maintenant", web_app=WebAppInfo(url=MINI_APP_URL))
            ]])
        )
    except Exception as e:
        await update.message.reply_text(f"❌ API indisponible: {e}\nDémarre l'oracle: `python oracle.py`", parse_mode="Markdown")


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Commande réservée à l'admin."""
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(
        "🔑 Panel admin SAL\n\n"
        "/admin_stats  — Statistiques du contrat\n"
        "/admin_pause  — Mettre en pause le marché\n"
        "/admin_round  — Infos round en cours"
    )


async def cmd_admin_round(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return
    await cmd_stats(update, ctx)  # réutilise /stats


async def handle_webapp_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reçoit les données depuis la Mini App (ex: confirmation de mise)."""
    data = update.effective_message.web_app_data
    if data:
        log.info(f"WebApp data from {update.effective_user.id}: {data.data}")
        await update.message.reply_text(f"✅ Action reçue: {data.data}")


# ─────────────────────────────────────────────────────────────
#  Notifications admin (boucle background)
# ─────────────────────────────────────────────────────────────

async def notify_admin(app: Application, message: str) -> None:
    if ADMIN_CHAT_ID:
        try:
            await app.bot.send_message(chat_id=ADMIN_CHAT_ID, text=message, parse_mode="HTML")
        except Exception as e:
            log.error(f"Admin notify error: {e}")


async def monitor_loop(app: Application) -> None:
    """Surveillance du prix et alertes admin."""
    last_price = 0.0
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{API_URL}/price") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price  = data.get("price", 0)
                        change = data.get("change1m", 0)

                        # Alerte si variation > 0.5% en 1 minute
                        if abs(change) > 0.5 and last_price > 0:
                            trend = "🚀 HAUSSE" if change > 0 else "⚠️ BAISSE"
                            await notify_admin(
                                app,
                                f"{trend} S&P 500\n"
                                f"Prix: <b>${price:.2f}</b>\n"
                                f"Variation: <b>{change:+.2f}%</b> en 1 min"
                            )
                        last_price = price
        except Exception:
            pass
        await asyncio.sleep(60)


# ─────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    # Commandes
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("admin",       cmd_admin))
    app.add_handler(CommandHandler("admin_round", cmd_admin_round))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))

    # Commandes Telegram (menu BotFather)
    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start", "Ouvrir SAL Market"),
            BotCommand("stats", "Prix et round actuel"),
            BotCommand("help",  "Aide"),
        ])
        if ADMIN_CHAT_ID:
            await notify_admin(
                application,
                "🟢 <b>Bot SAL démarré</b>\n"
                f"Mini App: {MINI_APP_URL}\n"
                f"API: {API_URL}"
            )

    app.post_init = post_init

    log.info(f"Bot SAL démarré (admin: {ADMIN_CHAT_ID})")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
