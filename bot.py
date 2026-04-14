import logging
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

BOT_TOKEN = "8796122248:AAEDysolNwMgdYEoOSZU2pwoZPHkc3ookfA"

OWNER_ID = 6625019627
GROUP_CONTROL_ID = -1002872325078  # অটো অন/অফ গ্রুপ
group_night_msg_id = None  # রাতের মেসেজ ID সেভ
group_reminder_msg_id = None  # ওয়ার্নিং মেসেজ ID সেভ
allowed_users = set([OWNER_ID])
target_groups = {}  # {group_id: group_title}

BD_TZ = timezone(timedelta(hours=6))

data = {
    "broadcast_msg": None,
    "broadcast_photo": None,
    "is_running": False,
    "interval": None,
    "next_broadcast_time": None,
    "last_msg_ids": {},
}

logging.basicConfig(level=logging.INFO)


def is_allowed(user_id):
    return user_id in allowed_users


async def access_denied(update: Update):
    user = update.effective_user
    keyboard = [[InlineKeyboardButton("📞 Contact Admin", url="https://t.me/mrincome9")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🛡 এক্সেস ডিনাইড\n\n"
        f"👤 আপনার তথ্য:\n"
        f"🆔 আইডি: `{user.id}`\n"
        f"⚠️ স্ট্যাটাস: No Access ❌\n"
        f"🚫 দুঃখিত, আপনার কাছে এই বটটি\n"
        f"ব্যবহার করার অনুমতি নেই।",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


# ============================================
# /start
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    keyboard = [[InlineKeyboardButton("⚡ Powered By Mamun", url="https://t.me/mrincome9")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "  🤖 TakaRush বট এ \n\n"
        "✨ স্বাগতম! \n\n"
        "📋 কমান্ড লিস্ট:\n"
        "┌───────────────────\n"
        "│ 🎯 /set — গ্রুপ টার্গেট সেট\n"
        "│ 📋 /groups — গ্রুপ লিস্ট ও বাদ দিন\n"
        "│ 📝 /setmsg — বিজ্ঞাপন সেট\n"
        "│ 📊 /status — অবস্থা দেখুন\n"
        "│ 🛑 /stop — ব্রডকাস্ট বন্ধ\n"
        "│ 👥 /allow [id] — ইউজার অ্যাড\n"
        "│ 🚫 /remove [id] — ইউজার বাদ\n"
        "└───────────────────",
        reply_markup=reply_markup
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
            f"   ✅ অ্যাক্সেস প্রদান    \n\n"
            f"👤 ইউজার আইডি: {new_id}\n"
            f"🟢 স্ট্যাটাস: Access Granted ✅\n"
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
            f"   🚫 অ্যাক্সেস বাতিল    \n\n"
            f"👤 ইউজার আইডি: {rem_id}\n"
            f"🔴 স্ট্যাটাস: Access Removed ❌\n"
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
            "  ⚠️ ভুল জায়গা!   \n\n"
            "🚫 /set কমান্ড শুধু গ্রুপে কাজ করে!\n\n"
            "📌 যেভাবে করবেন:\n"
            "1. বটকে গ্রুপে Admin করুন\n"
            "2. সেই গ্রুপে গিয়ে /set দিন"
        )
        return

    gid = update.effective_chat.id
    title = update.effective_chat.title or str(gid)
    target_groups[gid] = title

    await update.message.reply_text(
        f"✅ গ্রুপ সফলভাবে যোগ হয়েছে!\n\n"
        f"📛 নাম: {title}\n"
        f"🆔 আইডি: {gid}\n"
        f"📡 মোট গ্রুপ: {len(target_groups)} টি\n"
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
            "  📋 গ্রুপ লিস্ট খালি   \n"
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
        f"  📋 টার্গেট গ্রুপ লিস্ট   \n"
        f"📡 মোট গ্রুপ: {len(target_groups)} টি\n"
        f"{group_lines}"
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
        "✅ বিজ্ঞাপন সফলভাবে সেট হয়েছে!\n"
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
            f"  📋 টার্গেট গ্রুপ লিস্ট   \n"
            f"📡 বাকি গ্রুপ: {len(target_groups)} টি\n"
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
            f"🚀 ব্রডকাস্ট চালু হয়েছে!\n\n"
            f"⏱ ইন্টারভাল: প্রতি {minutes} মিনিটে\n"
            f"📡 গ্রুপ সংখ্যা: {len(target_groups)} টি\n"
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
# শিফট শুরুর নোটিশ — সকাল ১১:০০
# ============================================
async def shift_start_notice(context: ContextTypes.DEFAULT_TYPE):
    try:
        today = datetime.now(BD_TZ).strftime("%d/%m/%Y")
        await context.bot.send_message(
            chat_id=GROUP_CONTROL_ID,
            text=(
                "🔔 এখন সকাল ১১ টা বাজে!\n\n"
                "✅ এখন আপনারা কাজ শুরু\n"
                "করতে পারেন! 💪🎯\n"
                f"📅 Date : {today}"
            )
        )
    except Exception as e:
        logging.error(f"Shift start notice error: {e}")


# ============================================
# শিফট শেষের নোটিশ — রাত ৯:৩০
# ============================================
async def shift_end_notice(context: ContextTypes.DEFAULT_TYPE):
    try:
        today = datetime.now(BD_TZ).strftime("%d/%m/%Y")
        await context.bot.send_message(
            chat_id=GROUP_CONTROL_ID,
            text=(
                "🔔✨ বিশেষ বিজ্ঞপ্তি ✨🔔\n\n"
                "   📢 অফিশিয়াল নোটিশ 📢   \n"
                "🕐 আমাদের সকল সহকারীর কাজ\n"
                "সকাল ১১টায় শুরু হয়!! ✅ এবং\n"
                "রাত ৯:৩০ মিনিটে শেষ হয়। 🔴\n\n"
                "😴 এখন রাত ৯:৩০ বাজে তাই\n"
                "আমাদের সহকারী অফলাইন 🚫\n\n"
                "💰 তাই এখন আপনার বোনাস\n"
                "আপনাকেই নিতে হবে 🎯\n"
                "বা যদি কোনো দরকার বা সমস্যা\n"
                "থাকে আগামীকাল বলবেন 😊\n"
                f"📅 Date : {today}"
            )
        )
    except Exception as e:
        logging.error(f"Shift end notice error: {e}")


# ============================================
# ওয়ার্নিং মেসেজ — রাত ১১:০০
# ============================================
async def group_reminder(context: ContextTypes.DEFAULT_TYPE):
    global group_reminder_msg_id
    try:
        sent = await context.bot.send_message(
            chat_id=GROUP_CONTROL_ID,
            text=(
                "🔔⚠️ বিশেষ নোটিশ ⚠️🔔\n\n"
                "  🎁 বোনাস ক্লেম রিমাইন্ডার 🎁  \n"
                "⏰ এখন রাত ১১:০০ টা বাজে!\n\n"
                "🚨 মাত্র ১ ঘণ্টা বাকি আছে!\n"
                "💰 যার যার বোনাস এখনই\n"
                "তাড়াতাড়ি ক্লেম করে নিন! 🎯\n\n"
                "⚠️ রাত ১২:০০ টায় গ্রুপটি\n"
                "🔴 অফ হয়ে যাবে!\n"
                "⚡ দেরি না করে এখনই নিন! ⚡\n"
                "🕛 সময় শেষ হওয়ার আগেই! 🕛"
            )
        )
        group_reminder_msg_id = sent.message_id
    except Exception as e:
        logging.error(f"Reminder error: {e}")


async def delete_reminder(context: ContextTypes.DEFAULT_TYPE):
    global group_reminder_msg_id
    try:
        if group_reminder_msg_id:
            await context.bot.delete_message(
                chat_id=GROUP_CONTROL_ID,
                message_id=group_reminder_msg_id
            )
            group_reminder_msg_id = None
    except Exception as e:
        logging.error(f"Delete reminder error: {e}")

# ============================================
# গ্রুপ অটো অফ — রাত ১২টা
# ============================================
async def group_night_off(context: ContextTypes.DEFAULT_TYPE):
    global group_night_msg_id
    try:
        # Good Night মেসেজ পাঠাও
        sent = await context.bot.send_message(
            chat_id=GROUP_CONTROL_ID,
            text=(
                "🌙✨ 𝐆𝐨𝐨𝐝 𝐍𝐢𝐠𝐡𝐭 ✨🌙\n\n"
                "🤲 ঘুমানোর আগে দোয়া:\n"
                "🕌 اللهم بسمك أموت وأحيا\n\n"
                "📖 বাংলা উচ্চারণ:\n"
                "'আল্লাহুম্মা বিসমিকা আমুতু ওয়া-আহইয়া'\n\n"
                "💫 অর্থ:\n"
                "হে আল্লাহ! আমি তোমারই নামে মৃত্যুবরণ করি,\n"
                "আবার তোমারই নামে জীবন ধারন করি।\n\n"
                "⚠️ বিশেষ দ্রষ্টব্য:\n"
                "এখন কোনো এডমিন লাইনে থাকবে না!!\n"
                "তাই গ্রুপটি অফ 🔴\n"
                "আবার ভোর ৫টায় খোলা হবে। 🌅"
            )
        )
        group_night_msg_id = sent.message_id

        # Text + Photos অফ করো
        await context.bot.set_chat_permissions(
            chat_id=GROUP_CONTROL_ID,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_photos=False,
            )
        )
    except Exception as e:
        logging.error(f"Night off error: {e}")


# ============================================
# গ্রুপ অটো অন — সকাল ৫টা
# ============================================
async def group_morning_on(context: ContextTypes.DEFAULT_TYPE):
    global group_night_msg_id
    try:
        # রাতের মেসেজ ডিলিট করো
        if group_night_msg_id:
            try:
                await context.bot.delete_message(
                    chat_id=GROUP_CONTROL_ID,
                    message_id=group_night_msg_id
                )
                group_night_msg_id = None
            except Exception:
                pass

        # Text + Photos আবার অন করো
        await context.bot.set_chat_permissions(
            chat_id=GROUP_CONTROL_ID,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_photos=True,
            )
        )

        # Good Morning মেসেজ পাঠাও
        await context.bot.send_message(
            chat_id=GROUP_CONTROL_ID,
            text=(
                "🌅✨ 𝐆𝐨𝐨𝐝 𝐌𝐨𝐫𝐧𝐢𝐧𝐠 ✨🌅\n\n"
                "🎉 আমাদের গ্রুপটি খোলা হয়েছে!\n"
                "এখন আপনারা বোনাস নিতে পারবেন। 🎁\n"
            )
        )
    except Exception as e:
        logging.error(f"Morning on error: {e}")

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
            # আগের মেসেজ ডিলিট করো
            old_msg_id = data["last_msg_ids"].get(group_id)
            if old_msg_id:
                try:
                    await context.bot.delete_message(chat_id=group_id, message_id=old_msg_id)
                except Exception:
                    pass

            # নতুন মেসেজ পাঠাও এবং id সেভ করো
            if photo:
                sent = await context.bot.send_photo(chat_id=group_id, photo=photo, caption=msg)
            else:
                sent = await context.bot.send_message(chat_id=group_id, text=msg)

            data["last_msg_ids"][group_id] = sent.message_id

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
        "  🛑 ব্রডকাস্ট বন্ধ   \n\n"
        "✅ সফলভাবে বন্ধ করা হয়েছে!\n"
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
        f"  📊 বর্তমান অবস্থা  \n\n"
        f"🔄 ব্রডকাস্ট: {'✅ চালু' if data['is_running'] else '🛑 বন্ধ'}\n"
        f"📡 টার্গেট গ্রুপ: {len(target_groups)} টি\n"
        f"💬 মেসেজ: {msg_preview}\n"
        f"⏱ ইন্টারভাল: {str(interval // 60) + ' মিনিট' if interval else 'সেট হয়নি'}\n"
        f"🕐 সময়: {now_bd.strftime('%I:%M %p')}\n"
        f"⏳ পরের মেসেজ: {countdown_text}"
    )


# ============================================
# গ্রুপে "time" লিখলে সময় ও তারিখ দেখাবে
# ============================================
async def time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text and text.strip().lower() == "time":
        now_bd = datetime.now(BD_TZ)
        await update.message.reply_text(
            f"🕰️ এখন সময়!!\n\n"
            f"🕐 Time: {now_bd.strftime('%I:%M %p')}\n"
            f"📅 Date: {now_bd.strftime('%d/%m/%Y')}"
        )


# ============================================
# রেফার কোড ডিটেক্ট — অটো রিপ্লাই + ৫ মিনিট পর ডিলিট
# ============================================
import re as _re

async def refer_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or update.message.caption
    if not text:
        return
    text = text.strip()
    if (
        len(text) >= 6
        and _re.fullmatch(r'[A-Za-z0-9]+', text)
        and any(c.isupper() for c in text)
        and any(c.islower() for c in text)
    ):
        reply = await update.message.reply_text(
            f"💬✨ আপনি নিজের WA Task বোনাস\n"
            f"নিজে নেওয়ার জন্য আপনার এই 👇\n\n"
            f"`{text}#4`\n\n"
            f"⬆️ কোড টি এখানে এভাবে পেস্ট করুন 📋\n\n"
            f"আর SMS টাস্ক এর জন্য 👇\n\n"
            f"`{text}#1`\n\n"
            f"⬆️ এভাবে পেস্ট করুন 📲✅",
            parse_mode="Markdown"
        )
        chat_id = reply.chat_id
        message_id = reply.message_id
        async def delete_reply(ctx):
            try:
                await ctx.bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass
        context.job_queue.run_once(delete_reply, when=300)


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
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)^time$'), time_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, refer_code_handler))
    app.add_handler(MessageHandler(filters.PHOTO, refer_code_handler))

    # অটো গ্রুপ অন/অফ শিডিউল (BD Time = UTC+6)
    # রাত ৯:১০ BD = ০৩:১০ UTC
    from datetime import time as dt_time
    # সকাল ১১:০০ BD = UTC 05:00
    app.job_queue.run_daily(shift_start_notice, time=dt_time(5, 0, tzinfo=timezone.utc))
    # রাত ৯:৩০ BD = UTC 15:30
    app.job_queue.run_daily(shift_end_notice, time=dt_time(15, 30, tzinfo=timezone.utc))
    # রাত ১১:০০ BD = UTC 17:00
    app.job_queue.run_daily(group_reminder, time=dt_time(17, 0, tzinfo=timezone.utc))
    # রাত ১১:৫০ BD = UTC 17:50
    app.job_queue.run_daily(delete_reminder, time=dt_time(17, 50, tzinfo=timezone.utc))
    app.job_queue.run_daily(group_night_off, time=dt_time(18, 0, tzinfo=timezone.utc))
    # সকাল ৯:১৫ BD = ০৩:১৫ UTC
    app.job_queue.run_daily(group_morning_on, time=dt_time(23, 0, tzinfo=timezone.utc))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()