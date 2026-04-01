import logging
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

BOT_TOKEN = "8593628816:AAGfsVV5saeuiBqNz4XDl1XzL8bygMuZBps"

OWNER_ID = 6625019627
allowed_users = set([OWNER_ID])
target_groups = {}  # {group_id: group_title}

BD_TZ = timezone(timedelta(hours=6))

data = {
    "broadcast_msg": None,
    "broadcast_photo": None,
    "is_running": False,
    "interval": None,
    "next_broadcast_time": None,
}

logging.basicConfig(level=logging.INFO)


def is_allowed(user_id):
    return user_id in allowed_users


async def access_denied(update: Update):
    user = update.effective_user
    await update.message.reply_text(
        f"🛡 এক্সেস ডিনাইড\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 আপনার তথ্য:\n"
        f"🆔 আইডি: {user.id}\n"
        f"⚠️ স্ট্যাটাস: No Access ❌\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🚫 দুঃখিত, আপনার কাছে এই বটটি\n"
        f"ব্যবহার করার অনুমতি নেই।"
    )


# ============================================
# /start
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    await update.message.reply_text(
        "╔═══════════════════╗\n"
        "  🤖 AutoBroadcast Bot   \n"
        "╚═══════════════════╝\n\n"
        "✨ স্বাগতম! বট সফলভাবে চালু আছে।\n\n"
        "📋 কমান্ড লিস্ট:\n"
        "┌───────────────────\n"
        "│ 🎯 /set — গ্রুপ টার্গেট সেট\n"
        "│ 📋 /groups — গ্রুপ লিস্ট ও বাদ দিন\n"
        "│ 📝 /setmsg — বিজ্ঞাপন সেট\n"
        "│ 📊 /status — অবস্থা দেখুন\n"
        "│ 🛑 /stop — ব্রডকাস্ট বন্ধ\n"
        "│ 👥 /allow [id] — ইউজার অ্যাড\n"
        "│ 🚫 /remove [id] — ইউজার বাদ\n"
        "└───────────────────\n\n"
        "⚡ Powered by AutoBroadcast"
    )


# ============================================
# /allow
# ============================================
async def allow_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await access_denied(update)
        return

    if not context.args:
        await update.message.reply_text("⚠️ ব্যবহার: /allow [user_id]")
        return

    try:
        new_id = int(context.args[0])
        allowed_users.add(new_id)
        await update.message.reply_text(
            f"╔══════════════════╗\n"
            f"║   ✅ অ্যাক্সেস প্রদান    \n"
            f"╚══════════════════╝\n\n"
            f"👤 ইউজার আইডি: {new_id}\n"
            f"🟢 স্ট্যাটাস: Access Granted ✅\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎉 এই ইউজার এখন বট ব্যবহার করতে পারবে।"
        )
    except ValueError:
        await update.message.reply_text("❌ সঠিক User ID দিন!")


# ============================================
# /remove (user)
# ============================================
async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await access_denied(update)
        return

    if not context.args:
        await update.message.reply_text("⚠️ ব্যবহার: /remove [user_id]")
        return

    try:
        rem_id = int(context.args[0])
        if rem_id == OWNER_ID:
            await update.message.reply_text("❌ নিজেকে রিমুভ করা যাবে না!")
            return
        allowed_users.discard(rem_id)
        await update.message.reply_text(
            f"╔══════════════════╗\n"
            f"║   🚫 অ্যাক্সেস বাতিল   ║\n"
            f"╚══════════════════╝\n\n"
            f"👤 ইউজার আইডি: {rem_id}\n"
            f"🔴 স্ট্যাটাস: Access Removed ❌\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚫 এই ইউজার আর বট ব্যবহার করতে পারবে না।"
        )
    except ValueError:
        await update.message.reply_text("❌ সঠিক User ID দিন!")


# ============================================
# /set — গ্রুপ যোগ
# ============================================
async def set_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    # শুধু গ্রুপে কাজ করবে
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text(
            "╔══════════════════╗\n"
            "║  ⚠️ ভুল জায়গা!  ║\n"
            "╚══════════════════╝\n\n"
            "🚫 /set কমান্ড শুধু গ্রুপে কাজ করে!\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📌 যেভাবে করবেন:\n"
            "1. বটকে গ্রুপে Admin করুন\n"
            "2. সেই গ্রুপে গিয়ে /set দিন"
        )
        return

    gid = update.effective_chat.id
    title = update.effective_chat.title or str(gid)
    target_groups[gid] = title

    await update.message.reply_text(
        f"╔══════════════════╗\n"
        f"  🎯 গ্রুপ যোগ সম্পন্ন  ║\n"
        f"╚══════════════════╝\n\n"
        f"✅ গ্রুপ সফলভাবে যোগ হয়েছে!\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📛 নাম: {title}\n"
        f"🆔 আইডি: {gid}\n"
        f"📡 মোট গ্রুপ: {len(target_groups)} টি\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💡 আরো গ্রুপে /set দিয়ে যোগ করুন।"
    )


# ============================================
# /groups — গ্রুপ লিস্ট + বাটনে ❌ বাদ দাও
# ============================================
async def show_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    if not target_groups:
        await update.message.reply_text(
            "╔══════════════════╗\n"
            "║  📋 গ্রুপ লিস্ট খালি  ║\n"
            "╚══════════════════╝\n\n"
            "⚠️ কোনো গ্রুপ সেট হয়নি!\n"
            "💡 গ্রুপে গিয়ে /set দিন।"
        )
        return

    keyboard = []
    group_lines = ""
    for i, (gid, title) in enumerate(target_groups.items(), 1):
        group_lines += f"{i}. 📛 {title}\n    🆔 {gid}\n\n"
        keyboard.append([
            InlineKeyboardButton(f"❌ {title} বাদ দিন", callback_data=f"delgroup_{gid}")
        ])

    await update.message.reply_text(
        f"╔══════════════════╗\n"
        f"║  📋 টার্গেট গ্রুপ লিস্ট  ║\n"
        f"╚══════════════════╝\n\n"
        f"📡 মোট গ্রুপ: {len(target_groups)} টি\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{group_lines}"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❌ বাদ দিতে নিচের বাটন চাপুন:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================
# /setmsg
# ============================================
async def setmsg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    if update.message.photo:
        caption = update.message.caption or ""
        if caption.startswith("/setmsg"):
            caption = caption[len("/setmsg"):].strip()
        data["broadcast_msg"] = caption
        data["broadcast_photo"] = update.message.photo[-1].file_id
    else:
        full_text = update.message.text or ""
        if full_text.startswith("/setmsg"):
            msg_text = full_text[len("/setmsg"):].strip()
        else:
            msg_text = full_text.strip()

        if not msg_text:
            await update.message.reply_text("⚠️ মেসেজ লিখুন!\nউদাহরণ: /setmsg আপনার বিজ্ঞাপন")
            return

        data["broadcast_msg"] = msg_text
        data["broadcast_photo"] = None

    keyboard = [
        [InlineKeyboardButton("🕒 15 Minute", callback_data="interval_15")],
        [InlineKeyboardButton("🕒 30 Minute", callback_data="interval_30")],
    ]

    await update.message.reply_text(
        "╔══════════════════╗\n"
        "║  📝 মেসেজ সেট সম্পন্ন  ║\n"
        "╚══════════════════╝\n\n"
        "✅ বিজ্ঞাপন সফলভাবে সেভ হয়েছে!\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⏱ ব্রডকাস্ট ইন্টারভাল সিলেক্ট করুন:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================
# Callback — interval + group delete
# ============================================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not is_allowed(user_id):
        await query.answer("🚫 আপনার অ্যাক্সেস নেই!", show_alert=True)
        return

    await query.answer()
    cb = query.data

    # গ্রুপ বাদ দেওয়া
    if cb.startswith("delgroup_"):
        gid = int(cb.replace("delgroup_", ""))
        title = target_groups.pop(gid, str(gid))

        if not target_groups:
            await query.edit_message_text(
                f"✅ '{title}' বাদ দেওয়া হয়েছে!\n\n"
                f"⚠️ এখন কোনো গ্রুপ নেই।\n"
                f"💡 গ্রুপে গিয়ে /set দিন।"
            )
            return

        # বাকি গ্রুপগুলো আপডেট করো
        keyboard = []
        for g_id, g_title in target_groups.items():
            keyboard.append([
                InlineKeyboardButton(f"📛 {g_title}", callback_data=f"groupinfo_{g_id}"),
                InlineKeyboardButton("❌ বাদ দিন", callback_data=f"delgroup_{g_id}")
            ])

        await query.edit_message_text(
            f"✅ '{title}' বাদ দেওয়া হয়েছে!\n\n"
            f"╔══════════════════╗\n"
            f"║  📋 টার্গেট গ্রুপ লিস্ট   \n"
            f"╚══════════════════╝\n\n"
            f"📡 বাকি গ্রুপ: {len(target_groups)} টি\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"❌ বাদ দিতে পাশের বাটন চাপুন:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # ইন্টারভাল সিলেক্ট
    elif cb in ["interval_15", "interval_30"]:
        minutes = 15 if cb == "interval_15" else 30
        seconds = minutes * 60

        data["interval"] = seconds
        data["is_running"] = True

        old_jobs = context.application.job_queue.get_jobs_by_name("broadcast_loop")
        for job in old_jobs:
            job.schedule_removal()

        await query.edit_message_text(
            f"╔══════════════════╗\n"
            f"║  🚀 ব্রডকাস্ট শুরু!   \n"
            f"╚══════════════════╝\n\n"
            f"✅ সফলভাবে চালু হয়েছে!\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⏱ ইন্টারভাল: প্রতি {minutes} মিনিটে\n"
            f"📡 গ্রুপ সংখ্যা: {len(target_groups)} টি\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⛔ বন্ধ করতে /stop দিন।"
        )

        await send_broadcast(context)
        data["next_broadcast_time"] = datetime.now(timezone.utc).timestamp() + seconds

        context.application.job_queue.run_repeating(
            broadcast_job,
            interval=seconds,
            first=seconds,
            name="broadcast_loop"
        )


# ============================================
# broadcast_job
# ============================================
async def broadcast_job(context: ContextTypes.DEFAULT_TYPE):
    if not data["is_running"]:
        jobs = context.application.job_queue.get_jobs_by_name("broadcast_loop")
        for job in jobs:
            job.schedule_removal()
        return

    await send_broadcast(context)
    interval = data.get("interval") or 900
    data["next_broadcast_time"] = datetime.now(timezone.utc).timestamp() + interval


# ============================================
# send_broadcast
# ============================================
async def send_broadcast(context: ContextTypes.DEFAULT_TYPE):
    msg = data.get("broadcast_msg")
    photo = data.get("broadcast_photo")

    if not target_groups or not msg:
        return

    for group_id in list(target_groups.keys()):
        try:
            if photo:
                await context.bot.send_photo(chat_id=group_id, photo=photo, caption=msg)
            else:
                await context.bot.send_message(chat_id=group_id, text=msg)
        except Exception as e:
            logging.error(f"Group {group_id} error: {e}")


# ============================================
# /stop
# ============================================
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    data["is_running"] = False
    data["next_broadcast_time"] = None

    jobs = context.application.job_queue.get_jobs_by_name("broadcast_loop")
    for job in jobs:
        job.schedule_removal()

    await update.message.reply_text(
        "╔══════════════════╗\n"
        "║  🛑 ব্রডকাস্ট বন্ধ   \n"
        "╚══════════════════╝\n\n"
        "✅ সফলভাবে বন্ধ করা হয়েছে!\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💤 বট এখন নিষ্ক্রিয় আছে।\n"
        "▶️ আবার শুরু করতে /setmsg দিন।"
    )


# ============================================
# /status
# ============================================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    now_bd = datetime.now(BD_TZ)
    interval = data.get("interval")
    next_time = data.get("next_broadcast_time")

    countdown_text = "N/A"
    if data["is_running"] and next_time:
        remaining = next_time - datetime.now(timezone.utc).timestamp()
        if remaining > 0:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            countdown_text = f"{mins} মিনিট {secs} সেকেন্ড পরে" if mins > 0 else f"{secs} সেকেন্ড পরে"
        else:
            countdown_text = "এখনই যাচ্ছে... ⚡"

    msg_preview = data.get("broadcast_msg") or "সেট হয়নি"
    if len(msg_preview) > 25:
        msg_preview = msg_preview[:25] + "..."

    await update.message.reply_text(
        f"╔══════════════════╗\n"
        f"║  📊 বর্তমান অবস্থা  \n"
        f"╚══════════════════╝\n\n"
        f"🔄 ব্রডকাস্ট: {'✅ চালু' if data['is_running'] else '🛑 বন্ধ'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📡 টার্গেট গ্রুপ: {len(target_groups)} টি\n"
        f"💬 মেসেজ: {msg_preview}\n"
        f"⏱ ইন্টারভাল: {str(interval // 60) + ' মিনিট' if interval else 'সেট হয়নি'}\n"
        f"🕐 BD সময়: {now_bd.strftime('%I:%M %p')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏳ পরের মেসেজ: {countdown_text}"
    )


# ============================================
# MAIN
# ============================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_group))
    app.add_handler(CommandHandler("groups", show_groups))
    app.add_handler(CommandHandler("setmsg", setmsg))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("allow", allow_user))
    app.add_handler(CommandHandler("remove", remove_user))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r'^/setmsg'), setmsg))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
