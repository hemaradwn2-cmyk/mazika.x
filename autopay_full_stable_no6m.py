from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import BadRequest
import json, os
from datetime import datetime, timedelta

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # ← هنا التعديل

ADMINS = [8355975939]
PRIVATE_CHANNEL_ID = -1003217329846

USDT_TRC20 = "TN8tugtN2zGKbhUuaVzaTU9UwmPAFTPV2D"
BTC_ADDRESS = "1GV6A8ivQU4LzTwNKwCtQ2xiW8v4P2BU9D"
LTC_ADDRESS = "LSfYbm673DKTAm64eHPCMW7ir6RrZpTRxz"

USERS_DB = "users.json"
LOG_FILE = "payments.log"

# ================= PLANS (بدون 6 شهور) =================
PLANS = {
    "3d":   ("3 Days",    20,   3),
    "1w":   ("1 Week",    50,   7),
    "1m":   ("1 Month",  100,  30),
    "3m":   ("3 Months", 200,  90),
    "life": ("Lifetime", 500, None),
}

# ================= HELPERS =================
def log(text):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {text}\n")

def load_users():
    if not os.path.exists(USERS_DB):
        with open(USERS_DB, "w") as f:
            json.dump({}, f)
    with open(USERS_DB, "r") as f:
        return json.load(f)

def save_users(d):
    with open(USERS_DB, "w") as f:
        json.dump(d, f)

def add_user(uid, days):
    users = load_users()
    if days is None:
        users[str(uid)] = "lifetime"
    else:
        users[str(uid)] = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    save_users(users)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton(f"{v[0]} - {v[1]}$", callback_data=f"plan_{k}")]
        for k, v in PLANS.items()
    ]
    await update.message.reply_text(
        "🔐 *Private VIP Channel*\n\nChoose a plan:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# ================= PLAN =================
async def plan_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    plan = q.data.replace("plan_", "")
    context.user_data.clear()
    context.user_data["plan"] = plan
    context.user_data["stage"] = "payment"

    name, price, _ = PLANS[plan]

    await q.message.reply_text(
        f"""
💳 *Payment Instructions*

🔹 USDT (TRC20)
`{USDT_TRC20}`

🔹 BTC
`{BTC_ADDRESS}`

🔹 LTC
`{LTC_ADDRESS}`

💰 *Amount:* {price} USD

📤 Send *TXID* or *Screenshot*
""",
        parse_mode="Markdown"
    )

# ================= PAYMENT PROOF =================
async def payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("stage") != "payment":
        return

    user = update.effective_user
    plan = context.user_data["plan"]
    name, price, days = PLANS[plan]

    proof = update.message.text if update.message.text else "📷 Screenshot"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve|{user.id}|{plan}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject|{user.id}")
        ]
    ])

    for admin in ADMINS:
        await context.bot.send_message(
            admin,
            f"""
🧾 *Payment Proof*

👤 {user.full_name}
🆔 `{user.id}`
📦 {name}
💰 {price} USD

Proof:
`{proof}`
""",
            reply_markup=kb,
            parse_mode="Markdown"
        )

    log(f"PROOF user={user.id} plan={plan}")
    await update.message.reply_text("⏳ Waiting for admin approval.")
    context.user_data.clear()

# ================= ADMIN ACTION =================
async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id not in ADMINS:
        return

    action, uid, *rest = q.data.split("|")
    uid = int(uid)

    if action == "approve":
        plan = rest[0]
        name, price, days = PLANS[plan]
        add_user(uid, days)

        try:
            invite = await context.bot.create_chat_invite_link(
                PRIVATE_CHANNEL_ID,
                member_limit=1
            )
            await context.bot.send_message(
                uid,
                f"✅ *Payment Approved!*\n📦 {name}\nTap to join:",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔐 Join Channel", url=invite.invite_link)]]
                ),
                parse_mode="Markdown"
            )
        except BadRequest:
            await context.bot.send_message(
                uid,
                f"✅ Approved for *{name}*.\n⚠️ Contact admin to join channel.",
                parse_mode="Markdown"
            )

        log(f"APPROVED user={uid} plan={plan}")
        await q.edit_message_text("✅ Approved")

    elif action == "reject":
        await context.bot.send_message(uid, "❌ Payment rejected.")
        log(f"REJECTED user={uid}")
        await q.edit_message_text("❌ Rejected")

# ================= EXPIRY CHECK =================
async def expiry_job(context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    now = datetime.now()

    for uid, exp in list(users.items()):
        if exp == "lifetime":
            continue
        if datetime.strptime(exp, "%Y-%m-%d") < now:
            try:
                await context.bot.ban_chat_member(PRIVATE_CHANNEL_ID, int(uid))
                await context.bot.unban_chat_member(PRIVATE_CHANNEL_ID, int(uid))
            except:
                pass
            del users[uid]
            log(f"EXPIRED user={uid}")

    save_users(users)

# ================= MAIN =================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(plan_select, pattern="^plan_"))
app.add_handler(CallbackQueryHandler(admin_action, pattern="^(approve|reject)"))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, payment_proof))

# Expiry يومي
app.job_queue.run_repeating(expiry_job, interval=86400, first=60)

print("Bot running (FULL STABLE NO 6M)...")
app.run_polling()
