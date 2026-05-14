"""
Bot Telegram SAL — lance la Mini App S&P 500.
Variables d'environnement requises:
  TELEGRAM_BOT_TOKEN   — token BotFather
  MINI_APP_URL         — URL HTTPS de la frontend déployée
"""

import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BOT_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
MINI_APP_URL = os.environ.get("MINI_APP_URL", "https://your-app.vercel.app")


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
        "• Mise en USDC sur Polygon\n"
        "• Rounds de 5 minutes — UP ou DOWN\n"
        "• Les gagnants partagent le pool\n\n"
        "Clique ci-dessous pour ouvrir l'application 👇",
        reply_markup=keyboard,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔸 /start — Ouvre le marché S&P 500\n"
        "🔸 /stats — Statistiques du round actuel\n"
        "🔸 /help  — Ce message\n\n"
        "📖 Règles:\n"
        "1. Connecte ton wallet MetaMask (Polygon)\n"
        "2. Choisis UP ou DOWN pour le prochain round\n"
        "3. Si tu as raison, tu gagnes ta mise × multiplicateur\n"
        "4. Les rounds se ferment toutes les 5 minutes"
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche les stats du round actuel (appel API backend)."""
    import aiohttp
    api_url = os.environ.get("API_URL", "http://localhost:8000")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_url}/round") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    epoch  = data.get("epoch", "—")
                    price  = data.get("price", 0)
                    up_pool   = data.get("long_usdc", 0)
                    down_pool = data.get("short_usdc", 0)
                    up_mult   = data.get("up_mult", 2.0)
                    down_mult = data.get("down_mult", 2.0)
                    secs      = data.get("seconds_left", 0)
                    mm, ss    = divmod(secs, 60)
                    await update.message.reply_text(
                        f"📊 Round #{epoch} — S&P 500\n\n"
                        f"💵 Prix: ${price:.2f}\n"
                        f"⏱ Temps restant: {mm:02d}:{ss:02d}\n\n"
                        f"🟢 UP  {up_mult:.2f}× — Pool: ${up_pool:.0f} USDC\n"
                        f"🔴 DOWN {down_mult:.2f}× — Pool: ${down_pool:.0f} USDC"
                    )
                else:
                    await update.message.reply_text("❌ Données indisponibles pour l'instant.")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur: {e}")


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    log.info("Bot SAL démarré.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
