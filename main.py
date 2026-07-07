import random
import urllib.parse
import logging
import re
import os  # Critical: Reads the dynamic server port configurations on Render
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from aiohttp import web
import asyncio

# Enable console logging logs
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- CONFIGURATION ----------
TOKEN = "8926737374:AAHf9pWv458xBerfZmeRfsMprrJSgsiaQTw"
MERCHANT_UPI_ID = "c.sandeep@superyes"
MERCHANT_NAME = "Key Store"

# ---------- DATA STORAGE ----------
active_checkout_sessions = {}  
used_utrs = set()  
license_keys = [
    "GPS-ABCD-1234-EFGH",
    "GPS-IJKL-5678-MNOP",
    "GPS-QRST-9012-UVWX",
]

# ---------- MENUS ----------
main_menu = ReplyKeyboardMarkup(
    [["🔑 Purchase Key", "📋 My Keys"], ["🎁 Redeem Code", "📖 How to Buy"], ["🆔 My ID", "🆘 Contact Support"]],
    resize_keyboard=True
)

brands_menu = ReplyKeyboardMarkup(
    [["GPS LOADER", "ZTRAX LOADER"], ["FIRE X LOADER", "SKIN LOADER"], ["⬅️ Back"]],
    resize_keyboard=True
)

gps_menu = ReplyKeyboardMarkup([["1 DAY KEY - ₹120", "3 DAY KEY - ₹220"], ["7 DAY KEY - ₹330", "5 HOURS KEY - ₹50"], ["⬅️ Back to Brands"]], resize_keyboard=True)
ztrax_menu = ReplyKeyboardMarkup([["ZTRAX 1 DAY - ₹130", "ZTRAX 3 DAY - ₹240"], ["ZTRAX 7 DAY - ₹350", "ZTRAX 5 HOURS - ₹60"], ["⬅️ Back to Brands"]], resize_keyboard=True)
firex_menu = ReplyKeyboardMarkup([["FIRE X 1 DAY - ₹140", "FIRE X 3 DAY - ₹250"], ["FIRE X 7 DAY - ₹380", "FIRE X 5 HOURS - ₹70"], ["⬅️ Back to Brands"]], resize_keyboard=True)
skin_menu = ReplyKeyboardMarkup([["SKIN 1 DAY - ₹100", "SKIN 3 DAY - ₹180"], ["SKIN 7 DAY - ₹280", "SKIN 5 HOURS - ₹70"], ["⬅️ Back to Brands"]], resize_keyboard=True)


# ---------- AUTOMATION WEB RECEIVER (FOR MACRODROID) ----------
async def handle_notification_webhook(request):
    """Listens for payment notifications forwarded from MacroDroid over the cloud."""
    try:
        data = await request.json()
        received_text = data.get("message", "")
        logger.info(f"Notification Received via Webhook: {received_text}")

        # Extract UTR (12 digits) and amount from notification text string
        utr_match = re.search(r'\b\d{12}\b', received_text)
        amt_match = re.search(r'(?:Rs\.?|INR|₹)\s*(\d+(?:\.\d{1,2})?)', received_text, re.IGNORECASE)

        if utr_match and amt_match:
            detected_utr = utr_match.group(0)
            detected_amount = float(amt_match.group(1))

            if detected_utr in used_utrs:
                return web.Response(text="Duplicate transaction ignored.", status=200)

            # Match incoming payment amount with users who have an active checkout session
            for user_id, session in list(active_checkout_sessions.items()):
                if float(session["price"]) == detected_amount:
                    
                    if not license_keys:
                        await request.app['tg_bot'].send_message(
                            chat_id=user_id,
                            text="⚠️ **Payment Confirmed!** However, stock pool is empty. Contact support immediately."
                        )
                        return web.Response(text="Stock Empty fallback executed.", status=200)

                    # Deliver the key automatically
                    delivered_key = license_keys.pop(0)
                    used_utrs.add(detected_utr)
                    active_checkout_sessions.pop(user_id, None)

                    await request.app['tg_bot'].send_message(
                        chat_id=user_id,
                        text=f"✅ **Payment Received and Verified Automatically!**\n\n📦 Product: `{session['product']}`\n🔑 Your Key:\n`{delivered_key}`",
                        parse_mode="Markdown",
                        reply_markup=main_menu
                    )
                    return web.Response(text="Key Auto-Delivered successfully.", status=200)
                    
        return web.Response(text="Notification parsed but no matching active transaction found.", status=200)
    except Exception as e:
        logger.error(f"Error handling MacroDroid Webhook: {e}")
        return web.Response(text="Internal server error.", status=500)


# ---------- START COMMAND ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to Key Store", reply_markup=main_menu)


# ---------- CORE MESSAGE HANDLER ----------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if context.user_data is None:
        context.user_data = {}

    if text == "🔑 Purchase Key" or text == "⬅️ Back to Brands":
        await update.message.reply_text("🎮 Select a brand:", reply_markup=brands_menu)
        return
    elif text == "⬅️ Back":
        await update.message.reply_text("👋 Main Menu", reply_markup=main_menu)
        return
    elif text == "GPS LOADER":
        await update.message.reply_text("⏳ Select duration:", reply_markup=gps_menu)
        return
    elif text == "ZTRAX LOADER":
        await update.message.reply_text("⏳ Select duration:", reply_markup=ztrax_menu)
        return
    elif text == "FIRE X LOADER":
        await update.message.reply_text("⏳ Select duration:", reply_markup=firex_menu)
        return
    elif text == "SKIN LOADER":
        await update.message.reply_text("⏳ Select duration:", reply_markup=skin_menu)
        return
    elif "₹" in text:
        try:
            prices = re.findall(r'₹(\d+)', text)
            if not prices:
                await update.message.reply_text("❌ Price processing failed. Please select a valid key amount.")
                return
                
            # FIXED PERMANENTLY: Extracting string out of array list using index 0
            price_amount = str(prices[0])
            random_suffix = random.randint(1000, 9999)
            order_id = f"ORD{random_suffix}"
            
            # Save user selection to monitor for this exact payment amount
            active_checkout_sessions[user_id] = {
                "product": text,
                "price": price_amount,
                "order_id": order_id
            }

            upi_payload = {
                "pa": str(MERCHANT_UPI_ID).strip(), 
                "pn": str(MERCHANT_NAME).strip(), 
                "am": price_amount, 
                "cu": "INR", 
                "tn": f"pay_ord{random_suffix}"
            }
            
            encoded_url = "upi://pay?" + urllib.parse.urlencode(upi_payload, quote_via=urllib.parse.quote)

            # Generate a secure text-based quick pay layout block
            checkout_caption = (
                f"💳 **Payment Checkout**\n\n"
                f"💵 Amount: **₹{price_amount}**\n"
                f"📦 Item: `{text}`\n"
                f"🧾 Order ID: `{order_id}`\n\n"
                f"📱 **Tap the official payment link below to load your UPI app:**\n"
                f"`{encoded_url}`\n\n"
                f"Alternatively, copy and transfer to our merchant ID manually:\n"
                f"`{MERCHANT_UPI_ID}`"
            )

            await update.message.reply_text(
                text=checkout_caption,
                parse_mode="Markdown"
            )
            
            await update.message.reply_text(
                text="🤖 **The cloud system is monitoring payments 24/7.**\n\nOnce completed, your license key will deliver right here instantly. You do not need to send UTR manually.",
                reply_markup=main_menu
            )
        except Exception as e:
            logger.error(f"CRITICAL EXCEPTION IN CHECKOUT: {e}", exc_info=True)
            await update.message.reply_text("❌ Configuration error. Please try again.")
        return
        
    elif text == "🆔 My ID":
        await update.message.reply_text(f"Your User ID is: `{user_id}`", parse_mode="Markdown")
        return

    return


# ---------- CONCURRENT EXECUTION RUNNERS ----------
async def main():
    # Build the main python-telegram-bot core application
    application = Application.builder().token(TOKEN).build()

    # Link routing triggers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, buttons))

    # Initialize bot components asynchronously
    await application.initialize()
    await application.start()
    
    # Set up web app router to catch MacroDroid Webhook POST notifications
    web_app = web.Application()
    web_app['tg_bot'] = application.bot
    web_app.router.add_post('/webhook', handle_notification_webhook)

    # Read server port bound by Render environment profiles
    server_port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", server_port)
    
    logger.info(f"Starting web server target configuration on port: {server_port}")
    await site.start()

    logger.info("Bot service setup successfully. Initiating polling loop handlers...")
    
    # Run bot polling loops
    await application.updater.start_polling()
    
    # Keep the execution thread running indefinitely
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    # Modern Python 3.12+ explicit loop policy patch for cloud engine runtime environments
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    try:
        loop.run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped manually.")
