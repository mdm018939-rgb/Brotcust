import asyncio
import logging
import json
import os
import random
import threading
import html as _html
import re
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ChatMemberHandler,
    TypeHandler, ApplicationHandlerStop
)

# ─── বাটনের রং: প্রতি ক্লিকে পালা করে ঘুরবে (সবুজ → লাল → primary) ───
_PTBButton = InlineKeyboardButton
_PTBMarkup = InlineKeyboardMarkup

_STYLES = ["success", "danger", "primary"]   # সবুজ, লাল, primary
_color_shift = {"n": 0}                      # কত ধাপ ঘুরেছে

def InlineKeyboardButton(text, *args, **kwargs):
    kwargs.pop("style", None)
    return _PTBButton(text, *args, **kwargs)

def _restyle(btn, style):
    kw = {}
    if btn.callback_data is not None:
        kw["callback_data"] = btn.callback_data
    if btn.url is not None:
        kw["url"] = btn.url
    try:
        return _PTBButton(btn.text, style=style, **kw)
    except TypeError:
        try:
            return _PTBButton(btn.text, api_kwargs={"style": style}, **kw)
        except TypeError:
            return _PTBButton(btn.text, **kw)

def InlineKeyboardMarkup(rows, *args, **kwargs):
    shift = _color_shift["n"]
    new_rows = []
    for i, row in enumerate(rows):
        style = _STYLES[(i + shift) % len(_STYLES)]
        new_rows.append([_restyle(b, style) for b in row])
    return _PTBMarkup(new_rows, *args, **kwargs)

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = 6625019627
MAX_GROUPS_PER_USER = 10   # একজন ইউজার সর্বোচ্চ কয়টা গ্রুপ যোগ করতে পারবে (OWNER এর সীমা নেই)

# ============================================================
# Supabase Config removed
# ============================================================

user_group_schedule = {}  # {user_id: {group_id: {"off_hour": 18, "on_hour": 6, "night_msg_id": None}}}
user_target_groups = {}   # {user_id: {group_id: group_title}}
all_bot_users = set()     # যে কেউ /start দিলে এখানে যোগ হবে

BD_TZ = timezone(timedelta(hours=6))

BN_DAYS = ["সোমবার","মঙ্গলবার","বুধবার","বৃহস্পতিবার","শুক্রবার","শনিবার","রবিবার"]
BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
BN_DIGITS_REV = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# ============================================================
# নতুন per-group broadcast data structure
# group_broadcast_data[user_id][group_id] = {
#   broadcast_msg, broadcast_photo, broadcast_video,
#   broadcast_media_group, interval, is_running,
#   next_broadcast_time, last_msg_id
# }
# ============================================================
group_broadcast_data = {}  # {user_id: {group_id: {...}}}
user_waiting_schedule = {}  # Custom সময় লেখার অপেক্ষা
user_waiting_setmsg = {}   # {user_id: group_id} — কোন গ্রুপের জন্য মেসেজ অপেক্ষায়
user_setmsg_prompt = {}    # {user_id: (chat_id, message_id)}
user_lang = {}             # {user_id: "bn" or "en"}

# ============================================================
# Request সিস্টেমের জন্য ডাটা স্ট্রাকচার (লিমিট ছাড়া)
# ============================================================
pending_requests = {}      # {request_id: {"from_user": uid, "to_user": admin_id, "group_id": gid, "group_title": title, "status": "pending", "timestamp": ts}}

# ============================================================
# NEW - Group Lock + Broadcast Request System
# ============================================================
group_lock = {}              # {group_id: owner_user_id}  -- broadcast চলাকালীন কার লকে আছে
broadcast_requests = {}      # {request_id: {"from_user": uid, "to_user": owner_id, "group_id": gid, "group_title": title, "status": "pending", "timestamp": ts}}

LOG_CHANNEL_ID = -1003602859167
GP_TEXT = None
GP_LINK = None
GP_PENDING = set()
BANNED_USERS = set()     # ব্যান করা ইউজার আইডি
admin_waiting = {}       # {owner_id: "br" | "gp" | "ban" | "unban"} — এডমিন প্যানেলে মেসেজ/আইডির অপেক্ষা

# ─── বিজ্ঞাপনের অক্ষর সীমা (শেষের ৯৬ অক্ষর /gp এর লেখার জন্য ফাঁকা) ───
AD_TEXT_LIMIT = 4000      # শুধু টেক্সট বিজ্ঞাপন
AD_CAPTION_LIMIT = 928    # ছবি/ভিডিও/ফাইল ইত্যাদির সাথের লেখা (টেলিগ্রামের সীমা ১০২৪)
GP_TEXT_LIMIT = 94        # /gp এর লেখা

# ─── বিজ্ঞাপনে যেসব ফাইলের ধরন নেওয়া হয় ───
_ITEM_CODE = {"photo": "p", "video": "v", "document": "d", "audio": "a", "voice": "o",
              "animation": "g", "sticker": "s", "video_note": "n"}
_ITEM_FROM_CODE = {v: k for k, v in _ITEM_CODE.items()}
_ITEM_EMOJI = {"photo": "📸", "video": "🎥", "document": "📎", "audio": "🎵", "voice": "🎤",
               "animation": "🎞", "sticker": "😀", "video_note": "⭕"}
_ITEM_LABEL = {
    "bn": {"photo": "📸 ছবি", "video": "🎥 ভিডিও", "document": "📎 ফাইল", "audio": "🎵 অডিও",
           "voice": "🎤 ভয়েস", "animation": "🎞 GIF", "sticker": "😀 স্টিকার", "video_note": "⭕ ভিডিও মেসেজ"},
    "en": {"photo": "📸 Photo", "video": "🎥 Video", "document": "📎 File", "audio": "🎵 Audio",
           "voice": "🎤 Voice", "animation": "🎞 GIF", "sticker": "😀 Sticker", "video_note": "⭕ Video message"},
}
_NO_CAPTION_TYPES = ("sticker", "video_note")   # এই দুই ধরনের সাথে লেখা জোড়া যায় না


def _tg_len(s) -> int:
    """টেলিগ্রাম যেভাবে অক্ষর গোনে (UTF-16)"""
    return len((s or "").encode("utf-16-le")) // 2


def _ad_too_long_text(user_id, n, limit) -> str:
    if user_lang.get(user_id, "bn") == "en":
        return (f"⚠️ Ad is too long!\n\n📏 Now: {n} characters\n✅ Max: {limit} characters\n\n"
                f"✂️ Please shorten it to {limit} characters or less and send again.")
    return (f"⚠️ বিজ্ঞাপন অনেক লম্বা!\n\n📏 এখন: {n} অক্ষর\n✅ সর্বোচ্চ: {limit} অক্ষর\n\n"
            f"✂️ ছোট করে {limit} অক্ষরের মধ্যে পাঠান।")


def _msg_to_item(msg):
    """মেসেজ থেকে ফাইলের ধরন আর file_id বের করে (ফাইল না হলে None)"""
    if msg.photo:
        return {"type": "photo", "file_id": msg.photo[-1].file_id}
    if msg.video:
        return {"type": "video", "file_id": msg.video.file_id}
    if msg.animation:   # GIF এ document ও থাকে, তাই আগে দেখা হয়
        return {"type": "animation", "file_id": msg.animation.file_id}
    if msg.voice:
        return {"type": "voice", "file_id": msg.voice.file_id}
    if msg.audio:
        return {"type": "audio", "file_id": msg.audio.file_id}
    if msg.video_note:
        return {"type": "video_note", "file_id": msg.video_note.file_id}
    if msg.sticker:
        return {"type": "sticker", "file_id": msg.sticker.file_id}
    if msg.document:
        return {"type": "document", "file_id": msg.document.file_id}
    return None


def _apply_items(gdata, items, caption):
    """ফাইলের তালিকা (একটা বা অ্যালবাম) আর লেখা বিজ্ঞাপন হিসেবে বসায়"""
    if len(items) == 1 and items[0]["type"] in ("photo", "video"):
        if items[0]["type"] == "photo":
            gdata["broadcast_photo"] = items[0]["file_id"]
            gdata["broadcast_video"] = None
        else:
            gdata["broadcast_video"] = items[0]["file_id"]
            gdata["broadcast_photo"] = None
        gdata["broadcast_media_group"] = None
    else:
        gdata["broadcast_media_group"] = items
        gdata["broadcast_photo"] = None
        gdata["broadcast_video"] = None
    gdata["broadcast_msg"] = caption


def _set_ad_from_message(gdata, msg) -> bool:
    """একটা মেসেজ থেকে বিজ্ঞাপন সেট করে — সফল হলে True"""
    item = _msg_to_item(msg)
    if item:
        _apply_items(gdata, [item], msg.caption or "")
        return True
    if msg.text:
        gdata["broadcast_msg"] = msg.text
        gdata["broadcast_photo"] = None
        gdata["broadcast_video"] = None
        gdata["broadcast_media_group"] = None
        return True
    return False


def _ad_emoji(gdata) -> str:
    mg = gdata.get("broadcast_media_group")
    if mg:
        return "📸📸" if len(mg) > 1 else _ITEM_EMOJI.get(mg[0]["type"], "📎")
    if gdata.get("broadcast_photo"):
        return "📸"
    if gdata.get("broadcast_video"):
        return "🎥"
    return "📝"


def _msg_emoji(msg) -> str:
    item = _msg_to_item(msg)
    return _ITEM_EMOJI.get(item["type"], "📎") if item else "📝"


def _ad_content_label(user_id, gdata) -> str:
    lang = "en" if user_lang.get(user_id, "bn") == "en" else "bn"
    mg = gdata.get("broadcast_media_group")
    if mg:
        if len(mg) > 1:
            return "📸 Album"
        return _ITEM_LABEL[lang].get(mg[0]["type"], "📎")
    if gdata.get("broadcast_photo"):
        return _ITEM_LABEL[lang]["photo"]
    if gdata.get("broadcast_video"):
        return _ITEM_LABEL[lang]["video"]
    return "📝 Text" if lang == "en" else "📝 টেক্সট"


LOGGED_GROUPS = set()   # যে গ্রুপের লিংক চ্যানেলে গেছে
NOTIFY_OFF = set()   # যারা অটো অন/অফ মেসেজ চায় না


# ============================================================
# ভাষার টেক্সট
# ============================================================
TEXTS = {
    "bn": {
                "welcome": "👋 স্বাগতম, {name}!\n\n📢 আপনার বিজ্ঞাপন অটোমেটিক সব গ্রুপে পাঠান।\n\n✅ কীভাবে কাজ করে:\n1️⃣ বটকে আপনার গ্রুপে এডমিন করুন\n2️⃣ ওই গ্রুপে /set লিখুন\n3️⃣ বিজ্ঞাপন সেট করে ব্রডকাস্ট চালু করুন\n\n👇 নিচের বাটন থেকে বেছে নিন:",
        "btn_groups": "🎯 আমার গ্রুপ",
        "btn_setmsg": "✍️ বিজ্ঞাপন সেট",
        "btn_status": "📡 লাইভ স্ট্যাটাস",
        "btn_stop": "🛑 বিজ্ঞাপন বন্ধ",
        "btn_schedule": "🕒 গ্রুপ অন/অফ",
        "btn_help": "📖 সাহায্য",
        "btn_lang": "🌐 ভাষা / Language",
        "btn_support": "💬 সাপোর্ট",
        "btn_back": "🔙 ব্যাক",
        "btn_cancel": "❌ বাতিল",
        "btn_remove": "❌ {title} বাদ দিন",
        "btn_stop_all": "🛑 All Group বন্ধ করো",
        "auto_off": "🛑 সব গ্রুপের broadcast অটো বন্ধ হয়ে গেছে।\n🌅 সকাল ১০:০০ তে আবার চালু হবে।\n\n🔕 নোটিফিকেশন বন্ধ বা চালু করতে: /off or /on নোটিফিকেশন",
        "auto_on": "🌅 সকাল ১০:০০ বাজে!\n✅ আপনার broadcast অটো চালু হয়েছে।\n\n🔕 নোটিফিকেশন বন্ধ বা চালু করতে: /off or /on নোটিফিকেশন",
        "groups_empty": "📋 গ্রুপ লিস্ট খালি\n⚠️ কোনো গ্রুপ সেট হয়নি!\n💡 গ্রুপে গিয়ে /set দিন।",
        "groups_header": "📋 টার্গেট গ্রুপ লিস্ট\n📡 মোট গ্রুপ: {count} টি\n\n{lines}❌ বাদ দিতে নিচের বাটন চাপুন:",
        "night_break": "🌙 রাতের বিরতি চলছে!\n\n⚠️ এই সময়ে বিজ্ঞাপন সেট করা যাবে না।\n🌅 সকাল ১০:০০ এর পরে আসুন।",
        "no_group_set": "⚠️ আগে গ্রুপ সেট করুন!\n💡 গ্রুপে গিয়ে /set দিন।",
        "select_group_ad": "📡 কোন গ্রুপের জন্য বিজ্ঞাপন সেট করতে চান?",
        "no_broadcast": "⚠️ কোনো গ্রুপে ব্রডকাস্ট চালু নেই!\n\n▶️ চালু করতে বিজ্ঞাপন বাটন চাপুন।",
        "stop_header": "🛑 {count} টি গ্রুপে ব্রডকাস্ট চালু\n\nকোন গ্রুপের ব্রডকাস্ট বন্ধ করবেন?",
        "select_group_schedule": "⚙️ গ্রুপ শিডিউল সেট করুন\n\nকোন গ্রুপের শিডিউল সেট করতে চান?",
        "ad_set_all_photo": "✅ সব গ্রুপে বিজ্ঞাপন সেট হয়েছে! 📸\n📡 মোট: {count} টি গ্রুপ\n\n⏱ ইন্টারভাল সিলেক্ট করুন:",
        "all_group_selected": "📡 সব গ্রুপ সিলেক্ট! ({count} টি)\n\n📝 এখন বিজ্ঞাপন পাঠান\n(ছবি, ভিডিও বা টেক্সট)",
        "ad_set_photo": "✅ বিজ্ঞাপন সেট হয়েছে! 📸\n📛 গ্রুপ: {title}\n\n⏱ ইন্টারভাল সিলেক্ট করুন:",
        "send_ad_now": "📛 গ্রুপ: {title}\n\n📝 এখন এই গ্রুপের বিজ্ঞাপন পাঠান\n(ছবি, ভিডিও বা টেক্সট)",
        "night_set_done": "✅ বিজ্ঞাপন সেট হয়েছে!\n\n📛 গ্রুপ: {title}\n⏱ ইন্টারভাল: প্রতি {minutes} মিনিটে\n\n🌙 এখন রাতের বিরতি চলছে।\n🌅 সকাল ১০:০০ তে অটো চালু হবে।",
        "night_all_done": "✅ সব গ্রুপে বিজ্ঞাপন সেট হয়েছে!\n\n📡 মোট: {started} টি গ্রুপ\n⏱ ইন্টারভাল: প্রতি {minutes} মিনিটে\n{no_admin}\n🌙 এখন রাতের বিরতি চলছে।\n🌅 সকাল ১০:০০ তে অটো চালু হবে।",
        "no_admin_fail": "❌ ব্রডকাস্ট চালু হয়নি!\n\n⛔ কোনো গ্রুপেই বট এডমিন নেই:\n{list}\n\n👉 বটকে এডমিন করে আবার চেষ্টা করুন।",
        "broadcast_started_all": "🚀 সব গ্রুপে ব্রডকাস্ট চালু!\n\n📡 মোট: {started} টি গ্রুপ\n⏱ ইন্টারভাল: প্রতি {minutes} মিনিটে\n{no_admin}⛔ বন্ধ করতে বন্ধ করুন বাটন চাপুন।",
        "not_admin": "❌ ব্রডকাস্ট চালু হয়নি!\n\n📛 গ্রুপ: {title}\n⛔ বটকে এডমিন করুন, তারপর আবার চেষ্টা করুন।",
        "group_check_fail": "❌ গ্রুপ চেক করতে পারিনি!\n📛 গ্রুপ: {title}",
        "broadcast_started": "🚀 ব্রডকাস্ট চালু হয়েছে!\n\n📛 গ্রুপ: {title}\n⏱ ইন্টারভাল: প্রতি {minutes} মিনিটে\n⛔ বন্ধ করতে বন্ধ করুন বাটন চাপুন।",
        "stop_all_done": "🛑 সব গ্রুপের ব্রডকাস্ট বন্ধ করা হয়েছে!\n\n▶️ আবার শুরু করতে বিজ্ঞাপন সেট বাটন চাপুন।",
        "stop_one_no_active": "🛑 '{title}' বন্ধ হয়েছে!\n\n⚠️ আর কোনো active গ্রুপ নেই।\n▶️ আবার শুরু করতে বিজ্ঞাপন সেট বাটন চাপুন।",
        "stop_one_more": "✅ '{title}' বন্ধ হয়েছে!\n\n📡 বাকি active গ্রুপ: {count} টি\nআরও বন্ধ করবেন?",
        "group_removed_empty": "✅ '{title}' বাদ দেওয়া হয়েছে!\n\n⚠️ এখন কোনো গ্রুপ নেই।\n💡 গ্রুপে গিয়ে /set দিন।",
        "group_removed_more": "✅ '{title}' বাদ দেওয়া হয়েছে!\n\n📋 টার্গেট গ্রুপ লিস্ট\n📡 বাকি গ্রুপ: {count} টি\n❌ বাদ দিতে পাশের বাটন চাপুন:",
        "no_group_schedule": "⚠️ কোনো গ্রুপ নেই।",
        "schedule_already_set": "⚠️ এই গ্রুপের শিডিউল আগেই সেট আছে!\n👤 আপনার গ্রুপের অন্য এডমিন সেট করেছেন।",
        "schedule_current": "📛 গ্রুপ: {title}\n\n⚙️ বর্তমান শিডিউল:\n🌙 বন্ধ: {off}\n🌅 চালু: {on}\n\nকী করতে চান?",
        "schedule_set_off": "📛 গ্রুপ: {title}\n\n⏰ কয়টায় গ্রুপ অটো বন্ধ করতে চান?\n\n⚙️ নিজের সময় দিতে Custom চাপুন, অথবা দ্রুত বেছে নিন:",
        "schedule_del_done": "✅ শিডিউল বাদ দেওয়া হয়েছে!\n\n📛 গ্রুপ: {title}\n⚠️ এই গ্রুপ আর অটো অন/অফ হবে না।",
        "schedule_set_on": "📛 গ্রুপ: {title}\n🌙 বন্ধ: {off}\n\n🌅 কয়টায় গ্রুপ অটো চালু করতে চান?\n\n⚙️ নিজের সময় দিতে Custom চাপুন, অথবা দ্রুত বেছে নিন:",
        "schedule_done": "✅ শিডিউল সেট হয়েছে!\n\n📛 গ্রুপ: {title}\n🌙 বন্ধ: {off}\n🌅 চালু: {on}",
        "status_group": "📊 গ্রুপ অবস্থা\n\n📛 গ্রুপ: {title}\n─────────────────\n🔄 ব্রডকাস্ট: {running}\n⏱ ইন্টারভাল: {interval}\n📁 কন্টেন্ট: {ctype}\n💬 মেসেজ: {preview}\n⏳ পরের মেসেজ: {countdown}",
        "status_running": "✅ চালু",
        "status_stopped": "🛑 বন্ধ",
        "status_interval": "{mins} মিনিট",
        "status_not_set": "সেট হয়নি",
        "status_countdown_soon": "এখনই যাচ্ছে... ⚡",
        "status_countdown": "{mins} মিনিট {secs} সেকেন্ড পরে",
        "status_countdown_secs": "{secs} সেকেন্ড পরে",
        "content_text": "📝 টেক্সট",
        "content_album": "📸 Album",
        "content_photo": "📸 ছবি",
        "content_video": "🎥 ভিডিও",
        "btn_refresh": "🔄 Refresh",
        "btn_change_time": "🔄 সময় পরিবর্তন",
        "btn_del_schedule": "❌ শিডিউল বাদ দিন",
        "not_yours": "🚫 এটা আপনার না!",
        "not_your_group": "🚫 এটা আপনার গ্রুপ না!",
        "send_media": "⚠️ এই ধরনের মেসেজ বিজ্ঞাপনে নেওয়া যায় না।\nটেক্সট, ছবি, ভিডিও, ভয়েস, অডিও, ফাইল, GIF, স্টিকার বা ভিডিও মেসেজ পাঠান।",
        "access_denied": "🛡 এক্সেস ডিনাইড\n\n⚠️ দুঃখিত, আপনার কাছে এই বটটি ব্যবহার করার অনুমতি নেই।\n📩 অনুমতি পেতে এডমিন কে আইডি পাঠান!",
        "set_in_group": "⚠️ /set কমান্ড গ্রুপে দিতে হয়!\n\n📌 কিভাবে করবেন:\n1️⃣ আপনার গ্রুপে বটকে এডমিন করুন\n2️⃣ গ্রুপে গিয়ে /set লিখুন\n3️⃣ বট কনফার্ম করবে ✅\n\n💡 এই ইনবক্সে /set কাজ করে না।",
        "not_group_admin": "❌ আপনি এই গ্রুপের এডমিন নন!\n\nশুধু এডমিনরা /set দিতে পারবে।",
        "bot_not_admin": "❌ বটকে আগে এডমিন করুন!\n\n📌 গ্রুপ সেটিংস → এডমিন → বট সিলেক্ট করুন\nতারপর আবার /set দিন।",
        "group_already_added": "⚠️ এই গ্রুপ আগেই যোগ আছে!\n\n📛 নাম: {title}\n🆔 আইডি: {gid}\n📡 মোট গ্রুপ: {count} টি",
        "group_added": "✅ গ্রুপ সফলভাবে যোগ হয়েছে!\n\n📛 নাম: {title}\n🆔 আইডি: {gid}\n📡 মোট গ্রুপ: {count} টি",
        "group_limit": "🚫 গ্রুপের সীমা পূর্ণ!\n\nএকজন ইউজার সর্বোচ্চ {limit}টি গ্রুপ যোগ করতে পারবে।\nনতুন গ্রুপ যোগ করতে চাইলে /start → 🎯 আমার গ্রুপ থেকে একটা গ্রুপ বাদ দিন।",
        "status_menu": "📊 স্ট্যাটাস মেনু\n\nনিচের অপশনগুলো থেকে বেছে নিন:",
        "btn_group_status": "📡 গ্রুপ স্ট্যাটাস",
        "btn_schedule_status": "🕒 Group On/Off",
        "status_no_active": "📊 বর্তমান অবস্থা\n\n🛑 কোনো গ্রুপে ব্রডকাস্ট চালু নেই!\n\n📡 মোট গ্রুপ: {count} টি\n🕒 সময়: {time}\n\n▶️ চালু করতে বিজ্ঞাপন সেট বাটন চাপুন।",
        "status_active": "📊 বর্তমান অবস্থা\n\n✅ {active} টি গ্রুপে ব্রডকাস্ট চালু\n📡 মোট গ্রুপ: {total} টি\n🕒 সময়: {time}\n\n👇 গ্রুপে ট্যাপ করুন বিস্তারিত দেখতে:",
        "schedule_none": "🕒 Group On/Off লিস্ট\n\n🕒 বর্তমান সময়: {time}\n\n⚠️ কোনো শিডিউল সেট করা নেই।",
        "schedule_list": "🕒 Group On/Off লিস্ট\n\n🕒 বর্তমান সময়: {time}",
        "no_group_yet": "⚠️ আগে গ্রুপ সেট করুন!\n💡 গ্রুপে গিয়ে /set দিন।",
        "stop_all_confirm": "🛑 সব গ্রুপের ব্রডকাস্ট বন্ধ করা হয়েছে!\n\n▶️ আবার শুরু করতে বিজ্ঞাপন সেট বাটন চাপুন।",
        "stop_one_done": "🛑 '{title}' বন্ধ হয়েছে!\n\n⚠️ আর কোনো active গ্রুপ নেই।\n▶️ আবার শুরু করতে বিজ্ঞাপন সেট বাটন চাপুন।",
        "bot_join_msg": "👋 হ্যালো! আমি সাথি 🌷\n\n✅ আমাকে এডমিন করুন → /set ক্লিক দিন\nতারপর নিচের বাটনে ক্লিক করে ইনবক্সে আসুন 👇",
        "bot_removed": "⚠️ বট গ্রুপ থেকে সরানো হয়েছে!\n\n📛 গ্রুপ: {title}\n🆔 আইডি: {gid}\n\n🗑 এই গ্রুপের সব ডেটা মুছে গেছে।\n▶️ আবার যোগ করতে গ্রুপে বটকে এডমিন করে /set দিন।",
        "bot_not_admin_schedule": "⚠️ {title} — বট এডমিন নেই!\nগ্রুপ lock হয়নি।",
        "bot_not_admin_unlock": "⚠️ {title} — বট এডমিন নেই!\nগ্রুপ unlock হয়নি।",
        "bot_not_admin_broadcast": "⚠️ {title} — বট এডমিন নেই!\nব্রডকাস্ট বন্ধ হয়ে গেছে।\n\n👉 বটকে এডমিন করে আবার বিজ্ঞাপন সেট বাটন চাপুন।",
        "bot_not_admin_morning": "⚠️ {title} — বট এডমিন নেই!\nসকালে অটো চালু হয়নি।",
        "btn_15min": "⏱ ১৫ মিনিট",
        "btn_30min": "⏱ ৩০ মিনিট",
        "btn_45min": "⏱ ৪৫ মিনিট",
        "btn_60min": "⏱ ১ ঘন্টা",
        "btn_night_9": "রাত ৯টা",
        "btn_night_10": "রাত ১০টা",
        "btn_night_11": "রাত ১১টা",
        "btn_night_12": "রাত ১২টা",
        "btn_night_1": "রাত ১টা",
        "btn_night_2": "রাত ২টা",
        "btn_morning_6": "সকাল ৬টা",
        "btn_morning_7": "সকাল ৭টা",
        "btn_morning_8": "সকাল ৮টা",
        "btn_morning_9": "সকাল ৯টা",
        "btn_morning_10": "সকাল ১০টা",
        "btn_morning_11": "সকাল ১১টা",
        "btn_custom": "⚙️ Custom",
        "btn_main_menu": "🏠 মেইন মেনু",
        "custom_intv_prompt": "⏱ ইন্টারভাল লিখে পাঠান\n\nউদাহরণ:\n1h  •  2 h  •  16m  •  30 m\n১ থেকে ১২ = ঘন্টা  •  ১৫ বা বেশি = মিনিট\n\n⚠️ সর্বনিম্ন ১৫ মিনিট  •  সর্বোচ্চ ৩ দিন",
        "custom_intv_bad": "❌ ইন্টারভালের ফরম্যাট ঠিক নেই।\n\nআবার চেষ্টা করুন।",
        "custom_off_prompt": "⚙️ বন্ধের সময় লিখে পাঠান\n\nউদাহরণ:\n10pm  •  5 am  •  11:30am\n8 1  •  10:4  •  22:15",
        "custom_on_prompt": "🌙 বন্ধ: {off}\n\n⚙️ এবার চালুর সময় লিখে পাঠান\n\nউদাহরণ:\n6am  •  7:30 am  •  14:00\n8 1  •  10:4",
        "custom_bad_format": "❌ সময়ের ফরম্যাট ঠিক নেই।\n\nআবার নতুন করে শুরু করতে /start দিয়ে 🕒 গ্রুপ অন/অফ চাপুন।",
        "custom_same_time": "❌ বন্ধ ও চালুর সময় একই হতে পারবে না।\n\nআবার নতুন করে শুরু করতে /start দিয়ে 🕒 গ্রুপ অন/অফ চাপুন।",
        "select_schedule_group": "⚙️ গ্রুপ শিডিউল সেট করুন\n\nকোন গ্রুপের শিডিউল সেট করতে চান?",
        "ad_set_one": "✅ বিজ্ঞাপন সেট হয়েছে! {emoji}\n📛 গ্রুপ: {title}\n\n⏱ ইন্টারভাল সিলেক্ট করুন:",
        "ad_set_all": "✅ সব গ্রুপে বিজ্ঞাপন সেট হয়েছে! {emoji}\n📡 মোট: {count} টি গ্রুপ\n\n⏱ ইন্টারভাল সিলেক্ট করুন:",
        "send_ad_group": "📛 গ্রুপ: {title}\n\n📝 এখন এই গ্রুপের বিজ্ঞাপন পাঠান\n(টেক্সট, ছবি, ভিডিও, ভয়েস, স্টিকার, ফাইল — যেকোনো কিছু)",
        "send_ad_all": "📡 সব গ্রুপ সিলেক্ট! ({count} টি)\n\n📝 এখন বিজ্ঞাপন পাঠান\n(টেক্সট, ছবি, ভিডিও, ভয়েস, স্টিকার, ফাইল — যেকোনো কিছু)",
        "btn_cancel2": "❌ বাতিল",
        "btn_stop_all2": "🛑 All Group বন্ধ করো",
        "no_admin_text": "\n⛔ এডমিন নেই: {count} টি গ্রুপ\n",
        "no_admin_text2": "\n⛔ এডমিন নেই: {count} টি\n",
        "stop_header2": "🛑 {count} টি গ্রুপে ব্রডকাস্ট চালু\n\nকোন গ্রুপের ব্রডকাস্ট বন্ধ করবেন?",
        "no_broadcast2": "⚠️ কোনো গ্রুপে ব্রডকাস্ট চালু নেই!\n\n▶️ চালু করতে বিজ্ঞাপন সেট বাটন চাপুন।",
        "help_text": (
            "📖 বাটনের কাজ কী কী\n\n"
            "🎯 আমার গ্রুপ বাটনের কাজ:\n"
            "• আপনার সেট করা সব গ্রুপের লিস্ট দেখাবে\n"
            "• কোনো গ্রুপ আর লাগবে না হলে এখান থেকে বাদ দিতে পারবেন\n\n"
            "✍️ বিজ্ঞাপন সেট বাটনের কাজ:\n"
            "• কোন গ্রুপে পাঠাবেন সেটা বেছে নিন\n"
            "• বিজ্ঞাপন (টেক্সট বা ছবি) পাঠান\n"
            "• কত সময় পর পর যাবে (ইন্টারভাল) সেট করুন\n"
            "• এরপর বট নিজে থেকে বিজ্ঞাপন পাঠাতে থাকবে ✅\n\n"
            "📡 লাইভ স্ট্যাটাস বাটনের কাজ:\n"
            "• কোন গ্রুপে বিজ্ঞাপন চালু আছে দেখাবে\n"
            "• কত মিনিট পর পর যাচ্ছে আর পরের মেসেজ কখন যাবে জানাবে\n"
            "• গ্রুপের অন/অফ শিডিউলও এখান থেকে দেখা যাবে\n\n"
            "🛑 বিজ্ঞাপন বন্ধ বাটনের কাজ:\n"
            "• একটা নির্দিষ্ট গ্রুপের বিজ্ঞাপন বন্ধ করতে পারবেন\n"
            "• অথবা এক চাপে সব গ্রুপ বন্ধ করতে পারবেন\n\n"
            "🕒 গ্রুপ অন/অফ বাটনের কাজ:\n"
            "• গ্রুপ বেছে নিন\n"
            "• কখন বিজ্ঞাপন বন্ধ হবে আর কখন আবার চালু হবে সেই সময় ঠিক করুন\n"
            "• বট নিজে থেকেই সময়মতো অন/অফ করবে\n\n"
            "🌐 ভাষা / Language বাটনের কাজ:\n"
            "• বটের ভাষা বাংলা বা ইংরেজি করতে পারবেন\n\n"
            "💬 সাপোর্ট বাটনের কাজ:\n"
            "• কোনো সমস্যা হলে বা কিছু জানার থাকলে এডমিনের সাথে যোগাযোগ করুন\n\n"
            "🚀 শুরু করার নিয়ম:\n"
            "• বটকে গ্রুপে এডমিন করুন\n"
            "• গ্রুপে গিয়ে /set লিখুন\n"
            "• তারপর \"✍️ বিজ্ঞাপন সেট\" বাটন চাপুন\n\n"
            "⚡ Powered By Mamun"
        ),
        "schedule_will_start": "চালু হবে: {h} ঘণ্টা {m} মিনিট পরে",
        "schedule_will_stop": "বন্ধ হবে: {h} ঘণ্টা {m} মিনিট পরে",
        "schedule_will_start_min": "চালু হবে: {m} মিনিট পরে",
        "schedule_will_stop_min": "বন্ধ হবে: {m} মিনিট পরে",
        "off_time_label": "বন্ধ",
        "on_time_label": "চালু",
        # Request সিস্টেমের জন্য টেক্সট (লিমিট ছাড়া)
        "schedule_other_admin": "⚠️ এই গ্রুপের শিডিউল অন্য এডমিন সেট করেছেন!",
        "schedule_other_admin_by": "👤 এডমিন: {name} (ID: {id})",
        "schedule_request_hint": "আপনি রিকুয়েস্ট পাঠিয়ে অনুমতি নিতে পারেন।",
        "btn_send_request": "📨 রিকুয়েস্ট পাঠান",
        "btn_send_request_again": "📨 আবার রিকুয়েস্ট পাঠান",
        "request_sent": "📤 আপনার অনুরোধ পাঠানো হয়েছে!\n\n✅ এডমিন {name} এর কাছে অনুমতি চাওয়া হয়েছে।\n⏳ তিনি সাড়া দিলে আপনাকে জানানো হবে।",
        "request_already_pending": "⏳ আপনার আগের একটি অনুরোধ এখনও পেন্ডিং আছে!\n\nদয়া করে অপেক্ষা করুন।",
        "request_expires_in": "⏰ মেয়াদ শেষ হবে: {countdown} পরে",
        "request_to_admin": "📨 শিডিউল পরিবর্তনের অনুরোধ\n\n📛 গ্রুপ: {group_title}\n👤 অনুরোধকারী: {name} (ID: {id})\n📅 সময়: {time}\n\n{name} এই গ্রুপের শিডিউল পরিবর্তন করতে চান।\nআপনি কি অনুমতি দিতে চান?\n\n⚠️ অনুমতি দিলে আপনার সেট করা শিডিউল মুছে যাবে।",
        "btn_allow": "✅ অনুমতি দিন",
        "btn_reject": "❌ বাতিল করুন",
        "request_approved": "✅ আপনার অনুরোধ গ্রহণ করা হয়েছে!\n\n🔓 এডমিন {name} অনুমতি দিয়েছেন।\nআগের শিডিউল মুছে দেওয়া হয়েছে।\n\nএখন আপনি এই গ্রুপের জন্য নতুন শিডিউল সেট করতে পারেন।",
        "request_rejected": "❌ আপনার অনুরোধ বাতিল করা হয়েছে!\n\nএডমিন {name} অনুমতি দেননি।\nআপনি এই গ্রুপের শিডিউল পরিবর্তন করতে পারবেন না।\n\nআবার চেষ্টা করতে চাইলে নতুন করে রিকুয়েস্ট পাঠান।",
        "admin_allowed": "✅ আপনি অনুমতি দিয়েছেন!\n\n📛 গ্রুপ: {group_title}\n👤 অনুরোধকারী: {name} (ID: {id})\n\nআপনার সেট করা শিডিউল মুছে দেওয়া হয়েছে।\nএখন {name} নতুন শিডিউল সেট করতে পারবেন।",
        "admin_rejected": "❌ আপনি অনুমতি দেননি!\n\n📛 গ্রুপ: {group_title}\n👤 অনুরোধকারী: {name} (ID: {id})\n\nআপনার শিডিউল অপরিবর্তিত রয়েছে।\n{name} এই গ্রুপের শিডিউল পরিবর্তন করতে পারবেন না।",
        "request_expired": "⏰ আপনার অনুরোধের মেয়াদ শেষ হয়ে গেছে!\n\nদয়া করে নতুন করে রিকুয়েস্ট পাঠান।",
        # NEW - Broadcast Lock & Request texts
        "broadcast_locked": "🔒 এই গ্রুপে এখন অন্য একজন এডমিনের ব্রডকাস্ট চলছে!\n\n👤 এডমিন: {owner_name}\n📛 গ্রুপ: {group_title}\n\nআপনি কি তার কাছে ব্রডকাস্ট চালানোর অনুমতি চাইতে চান?",
        "btn_request_broadcast": "🔔 রিকুয়েস্ট পাঠান",
        "broadcast_request_sent": "📤 আপনার রিকুয়েস্ট পাঠানো হয়েছে!\n\n✅ এডমিন {owner_name} এর কাছে অনুমতি চাওয়া হয়েছে।\n⏳ তিনি সাড়া দিলে আপনাকে জানানো হবে।",
        "broadcast_request_already_pending": "⏳ আপনার আগের একটি অনুরোধ এখনও পেন্ডিং আছে!\n\n⏰ মেয়াদ শেষ হবে: {countdown} পরে",
        "broadcast_request_to_owner": "📨 ব্রডকাস্ট চালানোর অনুরোধ\n\n📛 গ্রুপ: {group_title}\n👤 অনুরোধকারী: {name} (ID: {id})\n📅 সময়: {time}\n\n{name} এই গ্রুপে ব্রডকাস্ট চালাতে চান।\nআপনি কি অনুমতি দিতে চান?\n\n⚠️ অনুমতি দিলে আপনার ব্রডকাস্ট বন্ধ হয়ে যাবে।",
        "broadcast_request_approved": "✅ আপনার রিকুয়েস্ট APPROVE করা হয়েছে!\n\n🔓 এডমিন {owner_name} অনুমতি দিয়েছেন।\nএখন আপনি '{group_title}' গ্রুপে নিজের ব্রডকাস্ট সেট করতে পারবেন।",
        "broadcast_request_rejected": "❌ আপনার রিকুয়েস্ট REJECT করা হয়েছে!\n\nএডমিন {owner_name} অনুমতি দেননি।\nআপনি এই গ্রুপে ব্রডকাস্ট চালাতে পারবেন না।",
        "broadcast_owner_approved": "✅ আপনি অনুমতি দিয়েছেন!\n\n📛 গ্রুপ: {group_title}\n👤 অনুরোধকারী: {name} (ID: {id})\n\nআপনার ব্রডকাস্ট বন্ধ করা হয়েছে।\nএখন {name} নতুন ব্রডকাস্ট চালাতে পারবেন।",
        "broadcast_owner_rejected": "❌ আপনি অনুমতি দেননি!\n\n📛 গ্রুপ: {group_title}\n👤 অনুরোধকারী: {name} (ID: {id})\n\nআপনার ব্রডকাস্ট অপরিবর্তিত রয়েছে।",
        "broadcast_request_expired": "⏰ আপনার অনুরোধের মেয়াদ শেষ হয়ে গেছে!\n\nদয়া করে নতুন করে রিকুয়েস্ট পাঠান।",
    },
    "en": {
        "welcome": "👋 Welcome, {name}!\n\n📢 Send your ads to all your groups automatically.\n\n✅ How it works:\n1️⃣ Add the bot to your group as admin\n2️⃣ Send /set in that group\n3️⃣ Set your ad and start broadcasting\n\n👇 Choose an option below:",
        "btn_groups": "🎯 My Groups",
        "btn_setmsg": "✍️ Set Ads",
        "btn_status": "📡 Live Status",
        "btn_stop": "🛑 Stop Ads",
        "btn_schedule": "🕒 Group On/Off",
        "btn_help": "📖 Help",
        "btn_lang": "🌐 Language / ভাষা",
        "btn_support": "💬 Support",
        "btn_back": "🔙 Back",
        "btn_cancel": "❌ Cancel",
        "btn_remove": "❌ Remove {title}",
        "btn_stop_all": "🛑 Stop All Groups",
        "auto_off": "🛑 All group broadcasts have been automatically stopped.\n🌅 Will resume at 10:00 AM.\n\n🔕 Turn notifications off or on: /off or /on notification",
        "auto_on": "🌅 Good Morning!\n✅ Your broadcast has been automatically started.\n\n🔕 Turn notifications off or on: /off or /on notification",
        "groups_empty": "📋 Group list is empty\n⚠️ No group has been set!\n💡 Go to your group and type /set.",
        "groups_header": "📋 Target Group List\n📡 Total Groups: {count}\n\n{lines}❌ Press button below to remove:",
        "night_break": "🌙 Night break is active!\n\n⚠️ You cannot set ads during this time.\n🌅 Please come back after 10:00 AM.",
        "no_group_set": "⚠️ Please set a group first!\n💡 Go to your group and type /set.",
        "select_group_ad": "📡 Which group do you want to set an ad for?",
        "no_broadcast": "⚠️ No broadcast is running!\n\n▶️ Press Set Ad to start.",
        "stop_header": "🛑 {count} group(s) broadcasting\n\nWhich group do you want to stop?",
        "select_group_schedule": "⚙️ Set Group Schedule\n\nWhich group do you want to schedule?",
        "ad_set_all_photo": "✅ Ad set for all groups! 📸\n📡 Total: {count} groups\n\n⏱ Select interval:",
        "all_group_selected": "📡 All groups selected! ({count})\n\n📝 Now send the ad\n(photo, video or text)",
        "ad_set_photo": "✅ Ad has been set! 📸\n📛 Group: {title}\n\n⏱ Select interval:",
        "send_ad_now": "📛 Group: {title}\n\n📝 Now send the ad for this group\n(photo, video or text)",
        "night_set_done": "✅ Ad has been set!\n\n📛 Group: {title}\n⏱ Interval: every {minutes} minutes\n\n🌙 Night break is active.\n🌅 Will auto-start at 10:00 AM.",
        "night_all_done": "✅ Ad set for all groups!\n\n📡 Total: {started} groups\n⏱ Interval: every {minutes} minutes\n{no_admin}\n🌙 Night break is active.\n🌅 Will auto-start at 10:00 AM.",
        "no_admin_fail": "❌ Broadcast failed!\n\n⛔ Bot is not admin in any group:\n{list}\n\n👉 Make the bot admin and try again.",
        "broadcast_started_all": "🚀 Broadcast started for all groups!\n\n📡 Total: {started} groups\n⏱ Interval: every {minutes} minutes\n{no_admin}⛔ Press Stop to stop broadcast.",
        "not_admin": "❌ Broadcast failed!\n\n📛 Group: {title}\n⛔ Make the bot admin and try again.",
        "group_check_fail": "❌ Could not check the group!\n📛 Group: {title}",
        "broadcast_started": "🚀 Broadcast started!\n\n📛 Group: {title}\n⏱ Interval: every {minutes} minutes\n⛔ Press Stop to stop broadcast.",
        "stop_all_done": "🛑 All group broadcasts have been stopped!\n\n▶️ Press Set Ad to start again.",
        "stop_one_no_active": "🛑 '{title}' stopped!\n\n⚠️ No more active groups.\n▶️ Press Set Ad to start again.",
        "stop_one_more": "✅ '{title}' stopped!\n\n📡 Remaining active groups: {count}\nStop more?",
        "group_removed_empty": "✅ '{title}' removed!\n\n⚠️ No groups left.\n💡 Go to your group and type /set.",
        "group_removed_more": "✅ '{title}' removed!\n\n📋 Target Group List\n📡 Remaining: {count} groups\n❌ Press button to remove:",
        "no_group_schedule": "⚠️ No groups found.",
        "schedule_already_set": "⚠️ Schedule already set for this group!\n👤 Another admin in your group set it.",
        "schedule_current": "📛 Group: {title}\n\n⚙️ Current Schedule:\n🌙 Off: {off}\n🌅 On: {on}\n\nWhat would you like to do?",
        "schedule_set_off": "📛 Group: {title}\n\n⏰ What time should the group auto-stop?\n\n⚙️ Tap Custom to type your own time, or pick quickly:",
        "schedule_del_done": "✅ Schedule removed!\n\n📛 Group: {title}\n⚠️ This group will no longer auto on/off.",
        "schedule_set_on": "📛 Group: {title}\n🌙 Off: {off}\n\n🌅 What time should the group auto-start?\n\n⚙️ Tap Custom to type your own time, or pick quickly:",
        "schedule_done": "✅ Schedule has been set!\n\n📛 Group: {title}\n🌙 Off: {off}\n🌅 On: {on}",
        "status_group": "📊 Group Status\n\n📛 Group: {title}\n─────────────────\n🔄 Broadcast: {running}\n⏱ Interval: {interval}\n📁 Content: {ctype}\n💬 Message: {preview}\n⏳ Next message: {countdown}",
        "status_running": "✅ Running",
        "status_stopped": "🛑 Stopped",
        "status_interval": "{mins} minutes",
        "status_not_set": "Not set",
        "status_countdown_soon": "Sending now... ⚡",
        "status_countdown": "{mins} min {secs} sec later",
        "status_countdown_secs": "{secs} sec later",
        "content_text": "📝 Text",
        "content_album": "📸 Album",
        "content_photo": "📸 Photo",
        "content_video": "🎥 Video",
        "btn_refresh": "🔄 Refresh",
        "btn_change_time": "🔄 Change Time",
        "btn_del_schedule": "❌ Remove Schedule",
        "not_yours": "🚫 This is not yours!",
        "not_your_group": "🚫 This is not your group!",
        "send_media": "⚠️ This type of message cannot be used as an ad.\nPlease send text, photo, video, voice, audio, file, GIF, sticker or video message.",
        "access_denied": "🛡 Access Denied\n\n⚠️ Sorry, you do not have permission to use this bot.\n📩 Send your ID to the admin to get access!",
        "set_in_group": "⚠️ /set command must be used in a group!\n\n📌 How to do it:\n1️⃣ Make the bot admin in your group\n2️⃣ Go to the group and type /set\n3️⃣ Bot will confirm ✅\n\n💡 /set does not work in this inbox.",
        "not_group_admin": "❌ You are not an admin of this group!\n\nOnly admins can use /set.",
        "bot_not_admin": "❌ Please make the bot admin first!\n\n📌 Group Settings → Admin → Select Bot\nThen type /set again.",
        "group_already_added": "⚠️ This group is already added!\n\n📛 Name: {title}\n🆔 ID: {gid}\n📡 Total groups: {count}",
        "group_added": "✅ Group added successfully!\n\n📛 Name: {title}\n🆔 ID: {gid}\n📡 Total groups: {count}",
        "group_limit": "🚫 Group limit reached!\n\nA user can add up to {limit} groups.\nTo add a new one, remove a group from /start → 🎯 My Groups first.",
        "status_menu": "📊 Status Menu\n\nChoose from the options below:",
        "btn_group_status": "📡 Group Status",
        "btn_schedule_status": "⏰ Schedule",
        "status_no_active": "📊 Current Status\n\n🛑 No broadcast is running!\n\n📡 Total groups: {count}\n🕒 Time: {time}\n\n▶️ Press Set Ad to start.",
        "status_active": "📊 Current Status\n\n✅ {active} group(s) broadcasting\n📡 Total groups: {total}\n🕒 Time: {time}\n\n👇 Tap a group to see details:",
        "schedule_none": "⏰ Schedule List\n\n🕒 Current time: {time}\n\n⚠️ No schedule has been set.",
        "schedule_list": "⏰ Schedule List\n\n🕒 Current time: {time}",
        "no_group_yet": "⚠️ Please set a group first!\n💡 Go to your group and type /set.",
        "stop_all_confirm": "🛑 All group broadcasts have been stopped!\n\n▶️ Press Set Ad to start again.",
        "stop_one_done": "🛑 '{title}' has been stopped!\n\n⚠️ No more active groups.\n▶️ Press Set Ad to start again.",
        "bot_join_msg": "👋 Hello! I am Sathi 🌷\n\n✅ Make me admin → Click /set\nThen click the button below to go to inbox 👇",
        "bot_removed": "⚠️ Bot has been removed from group!\n\n📛 Group: {title}\n🆔 ID: {gid}\n\n🗑 All data for this group has been deleted.\n▶️ To add again, make the bot admin and type /set.",
        "bot_not_admin_schedule": "⚠️ {title} — Bot is not admin!\nGroup was not locked.",
        "bot_not_admin_unlock": "⚠️ {title} — Bot is not admin!\nGroup was not unlocked.",
        "bot_not_admin_broadcast": "⚠️ {title} — Bot is not admin!\nBroadcast has stopped.\n\n👉 Make bot admin and press Set Ad again.",
        "bot_not_admin_morning": "⚠️ {title} — Bot is not admin!\nAuto-start in the morning failed.",
        "btn_15min": "⏱ 15 min",
        "btn_30min": "⏱ 30 min",
        "btn_45min": "⏱ 45 min",
        "btn_60min": "⏱ 1 hour",
        "btn_night_9": "9 PM",
        "btn_night_10": "10 PM",
        "btn_night_11": "11 PM",
        "btn_night_12": "12 AM",
        "btn_night_1": "1 AM",
        "btn_night_2": "2 AM",
        "btn_morning_6": "6 AM",
        "btn_morning_7": "7 AM",
        "btn_morning_8": "8 AM",
        "btn_morning_9": "9 AM",
        "btn_morning_10": "10 AM",
        "btn_morning_11": "11 AM",
        "btn_custom": "⚙️ Custom",
        "btn_main_menu": "🏠 Main Menu",
        "custom_intv_prompt": "⏱ Send the interval\n\nExamples:\n1h  •  2 h  •  16m  •  30 m\n1 to 12 = hours  •  15 or more = minutes\n\n⚠️ Minimum 15 minutes  •  Maximum 3 days",
        "custom_intv_bad": "❌ Invalid interval format.\n\nPlease try again.",
        "custom_off_prompt": "⚙️ Send the auto-stop time\n\nExamples:\n10pm  •  5 am  •  11:30am\n8 1  •  10:4  •  22:15",
        "custom_on_prompt": "🌙 Off: {off}\n\n⚙️ Now send the auto-start time\n\nExamples:\n6am  •  7:30 am  •  14:00\n8 1  •  10:4",
        "custom_bad_format": "❌ Invalid time format.\n\nSend /start and tap 🕒 Group On/Off to start again.",
        "custom_same_time": "❌ Off time and on time cannot be the same.\n\nSend /start and tap 🕒 Group On/Off to start again.",
        "select_schedule_group": "⚙️ Set Group Schedule\n\nWhich group do you want to schedule?",
        "ad_set_one": "✅ Ad has been set! {emoji}\n📛 Group: {title}\n\n⏱ Select interval:",
        "ad_set_all": "✅ Ad set for all groups! {emoji}\n📡 Total: {count} groups\n\n⏱ Select interval:",
        "send_ad_group": "📛 Group: {title}\n\n📝 Now send the ad for this group\n(text, photo, video, voice, sticker, file — anything)",
        "send_ad_all": "📡 All groups selected! ({count})\n\n📝 Now send the ad\n(text, photo, video, voice, sticker, file — anything)",
        "btn_cancel2": "❌ Cancel",
        "btn_stop_all2": "🛑 Stop All Groups",
        "no_admin_text": "\n⛔ No admin: {count} groups\n",
        "no_admin_text2": "\n⛔ No admin: {count}\n",
        "stop_header2": "🛑 {count} group(s) broadcasting\n\nWhich group do you want to stop?",
        "no_broadcast2": "⚠️ No broadcast is running!\n\n▶️ Press Set Ad to start.",
        "help_text": (
            "📖 What Each Button Does\n\n"
            "🎯 My Groups button:\n"
            "• Shows the list of all your set groups\n"
            "• You can remove a group from here if you no longer need it\n\n"
            "✍️ Set Ad button:\n"
            "• Choose the group you want to send to\n"
            "• Send your advertisement (text or photo)\n"
            "• Set how often it should be sent (interval)\n"
            "• The bot will then keep sending it automatically ✅\n\n"
            "📡 Live Status button:\n"
            "• Shows which groups have ads running\n"
            "• Tells you the interval and when the next message will go\n"
            "• You can also see the group on/off schedule from here\n\n"
            "🛑 Stop Ads button:\n"
            "• Stop ads for one specific group\n"
            "• Or stop all groups with a single tap\n\n"
            "🕒 Group On/Off button:\n"
            "• Choose a group\n"
            "• Set the time when ads should stop and when they should start again\n"
            "• The bot will switch them off and on by itself on time\n\n"
            "🌐 Language / ভাষা button:\n"
            "• Switch the bot language between Bengali and English\n\n"
            "💬 Support button:\n"
            "• Contact the admin if you have a problem or any question\n\n"
            "🚀 How to get started:\n"
            "• Make the bot an admin in your group\n"
            "• Send /set in the group\n"
            "• Then tap the \"✍️ Set Ad\" button\n\n"
            "⚡ Powered By Mamun"
        ),
        "schedule_will_start": "Will start in: {h}h {m}m",
        "schedule_will_stop": "Will stop in: {h}h {m}m",
        "schedule_will_start_min": "Will start in: {m}m",
        "schedule_will_stop_min": "Will stop in: {m}m",
        "off_time_label": "Off",
        "on_time_label": "On",
        # Request সিস্টেমের জন্য টেক্সট (লিমিট ছাড়া)
        "schedule_other_admin": "⚠️ Schedule already set by another admin!",
        "schedule_other_admin_by": "👤 Admin: {name} (ID: {id})",
        "schedule_request_hint": "You can send a request to get permission.",
        "btn_send_request": "📨 SEND REQUEST",
        "btn_send_request_again": "📨 SEND REQUEST AGAIN",
        "request_sent": "📤 Your request has been sent!\n\n✅ Admin {name} has been asked for permission.\n⏳ You will be notified when he responds.",
        "request_already_pending": "⏳ You already have a pending request!\n\nPlease wait.",
        "request_expires_in": "⏰ Expires in: {countdown}",
        "request_to_admin": "📨 Schedule Change Request\n\n📛 Group: {group_title}\n👤 Requester: {name} (ID: {id})\n📅 Time: {time}\n\n{name} wants to change the schedule of this group.\nDo you allow?\n\n⚠️ If you allow, your current schedule will be deleted.",
        "btn_allow": "✅ ALLOW",
        "btn_reject": "❌ REJECT",
        "request_approved": "✅ Your request has been APPROVED!\n\n🔓 Admin {name} has given permission.\nThe previous schedule has been deleted.\n\nYou can now set a new schedule for this group.",
        "request_rejected": "❌ Your request has been REJECTED!\n\nAdmin {name} did not give permission.\nYou cannot change the schedule for this group.\n\nTo try again, send a new request.",
        "admin_allowed": "✅ You have given permission!\n\n📛 Group: {group_title}\n👤 Requester: {name} (ID: {id})\n\nYour schedule has been deleted.\n{name} can now set a new schedule for this group.",
        "admin_rejected": "❌ You have rejected the request!\n\n📛 Group: {group_title}\n👤 Requester: {name} (ID: {id})\n\nYour schedule remains unchanged.\n{name} cannot change the schedule for this group.",
        "request_expired": "⏰ Your request has expired!\n\nPlease send a new request.",
        # NEW - Broadcast Lock & Request texts
        "broadcast_locked": "🔒 This group currently has a broadcast running by another admin!\n\n👤 Admin: {owner_name}\n📛 Group: {group_title}\n\nWould you like to request permission to broadcast?",
        "btn_request_broadcast": "🔔 SEND REQUEST",
        "broadcast_request_sent": "📤 Your request has been sent!\n\n✅ Admin {owner_name} has been asked for permission.\n⏳ You will be notified when he responds.",
        "broadcast_request_already_pending": "⏳ You already have a pending request!\n\n⏰ Expires in: {countdown}",
        "broadcast_request_to_owner": "📨 Broadcast Request\n\n📛 Group: {group_title}\n👤 Requester: {name} (ID: {id})\n📅 Time: {time}\n\n{name} wants to broadcast in this group.\nDo you allow?\n\n⚠️ If you allow, your broadcast will be stopped.",
        "broadcast_request_approved": "✅ Your request has been APPROVED!\n\n🔓 Admin {owner_name} has given permission.\nYou can now set up your own broadcast for '{group_title}' group.",
        "broadcast_request_rejected": "❌ Your request has been REJECTED!\n\nAdmin {owner_name} did not give permission.\nYou cannot broadcast in this group.",
        "broadcast_owner_approved": "✅ You have given permission!\n\n📛 Group: {group_title}\n👤 Requester: {name} (ID: {id})\n\nYour broadcast has been stopped.\n{name} can now start their broadcast.",
        "broadcast_owner_rejected": "❌ You have rejected the request!\n\n📛 Group: {group_title}\n👤 Requester: {name} (ID: {id})\n\nYour broadcast remains unchanged.",
        "broadcast_request_expired": "⏰ Your request has expired!\n\nPlease send a new request.",
    }
}

def get_text(user_id, key):
    lang = user_lang.get(user_id, "bn")
    return TEXTS.get(lang, TEXTS["bn"]).get(key, "")

def get_group_data(user_id, group_id):
    """নির্দিষ্ট user এর নির্দিষ্ট group এর broadcast data পাও"""
    if user_id not in group_broadcast_data:
        group_broadcast_data[user_id] = {}
    if group_id not in group_broadcast_data[user_id]:
        group_broadcast_data[user_id][group_id] = {
            "broadcast_msg": None,
            "broadcast_photo": None,
            "broadcast_video": None,
            "broadcast_media_group": None,
            "interval": None,
            "is_running": False,
            "next_broadcast_time": None,
            "last_msg_id": None,
        }
    return group_broadcast_data[user_id][group_id]


# ============================================
# Time formatting helper functions
# ============================================
def format_time_english(hour: int, minute: int = 0) -> str:
    h12 = hour % 12 or 12
    ampm = "AM" if hour < 12 else "PM"
    if minute:
        return f"{h12}:{minute:02d} {ampm}"
    return f"{h12} {ampm}"

def format_time_bangla(hour: int, minute: int = 0) -> str:
    h12 = hour % 12 or 12
    if hour == 0 or 1 <= hour <= 3:
        period = "রাত"
    elif 4 <= hour <= 5:
        period = "ভোর"
    elif 6 <= hour <= 11:
        period = "সকাল"
    elif 12 <= hour <= 14:
        period = "দুপুর"
    elif 15 <= hour <= 17:
        period = "বিকাল"
    elif 18 <= hour <= 19:
        period = "সন্ধ্যা"
    else:
        period = "রাত"
    text = f"{period} {str(h12).translate(BN_DIGITS)}টা"
    if minute:
        text += f" {str(minute).translate(BN_DIGITS)} মিনিট"
    return text

def format_schedule_time(user_id: int, hour: int, minute: int = 0) -> str:
    lang = user_lang.get(user_id, "bn")
    if lang == "en":
        return format_time_english(hour, minute)
    return format_time_bangla(hour, minute)


def _off_keyboard(owner_id, gid, back_cb):
    def b(key, h):
        return InlineKeyboardButton(get_text(owner_id, key), callback_data=f"offgp_off_{owner_id}_{gid}_{h}")
    return [
        [InlineKeyboardButton(get_text(owner_id, "btn_custom"), callback_data=f"offgp_coff_{owner_id}_{gid}")],
        [b("btn_night_9", 21), b("btn_night_10", 22)],
        [b("btn_night_11", 23), b("btn_night_12", 0)],
        [b("btn_night_1", 1), b("btn_night_2", 2)],
        [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=back_cb)],
    ]


def _on_keyboard(owner_id, gid, off_h, off_m=0):
    def b(key, h):
        return InlineKeyboardButton(get_text(owner_id, key), callback_data=f"offgp_on_{owner_id}_{gid}_{off_h}_{h}_{off_m}")
    return [
        [InlineKeyboardButton(get_text(owner_id, "btn_custom"), callback_data=f"offgp_con_{owner_id}_{gid}_{off_h}_{off_m}")],
        [b("btn_morning_6", 6), b("btn_morning_7", 7)],
        [b("btn_morning_8", 8), b("btn_morning_9", 9)],
        [b("btn_morning_10", 10), b("btn_morning_11", 11)],
        [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_grp_{owner_id}_{gid}")],
    ]


def parse_custom_time(text):
    t = (text or "").strip().lower().translate(BN_DIGITS_REV)
    t = t.replace("a.m.", "am").replace("p.m.", "pm")
    m = re.match(r"^(\d{1,2})(?:[:.\s]+(\d{1,2}))?\s*(am|pm)?$", t)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2)) if m.group(2) else 0
    ap = m.group(3)
    if mi > 59:
        return None
    if ap:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ap == "pm" else 0)
    elif h > 23:
        return None
    return h, mi


def _day_period(hour: int) -> str:
    if hour >= 20 or hour <= 3:
        return "night"
    if 4 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 15:
        return "noon"
    return "evening"


_PERIOD_EMOJI = {"night": "🌙", "morning": "🌅", "noon": "🌞", "evening": "🌇"}


logging.basicConfig(level=logging.INFO)


def is_allowed(user_id):
    return user_id == OWNER_ID or user_id not in BANNED_USERS


def get_user_groups(user_id):
    if user_id not in user_target_groups:
        user_target_groups[user_id] = {}
    return user_target_groups[user_id]


# ============================================
# Supabase user_lang persistence functions removed
# ============================================
async def save_data(bot):
    """Legacy save function - kept for compatibility"""
    # This is now a no-op for the new system
    # The old data structures are now RAM-only
    pass

async def load_data(bot, app=None):
    """Legacy load function - kept for compatibility"""
    # This is now a no-op for the new system
    pass


async def access_denied(update: Update):
    user = update.effective_user
    keyboard = [[InlineKeyboardButton("📞 Contact Admin", url="https://t.me/mrincome9")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    user_id = user.id
    await update.message.reply_text(
        get_text(user_id, "access_denied") + f"\n\n🆔 ID: `{user.id}`",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


# ============================================
# /start
# ============================================
def get_start_keyboard(user_id):
    """Start মেনুর inline keyboard বানাও"""
    keyboard = [
        [
            InlineKeyboardButton(get_text(user_id, "btn_groups"), callback_data=f"menu_groups_{user_id}"),
            InlineKeyboardButton(get_text(user_id, "btn_setmsg"), callback_data=f"menu_setmsg_{user_id}"),
        ],
        [
            InlineKeyboardButton(get_text(user_id, "btn_status"), callback_data=f"menu_status_{user_id}"),
            InlineKeyboardButton(get_text(user_id, "btn_stop"), callback_data=f"menu_stop_{user_id}"),
        ],
        [
            InlineKeyboardButton(get_text(user_id, "btn_schedule"), callback_data=f"menu_offgp_{user_id}"),
            InlineKeyboardButton(get_text(user_id, "btn_help"), callback_data=f"menu_help_{user_id}"),
        ],
        [
            InlineKeyboardButton(get_text(user_id, "btn_lang"), callback_data=f"menu_lang_{user_id}"),
        ],
    ]
    keyboard.append([InlineKeyboardButton(get_text(user_id, "btn_support"), url="https://t.me/teemcs")])
    if user_id == OWNER_ID:
        _adm_label = "🛠 Admin Panel" if user_lang.get(user_id, "bn") == "en" else "🛠 এডমিন প্যানেল"
        keyboard.append([InlineKeyboardButton(_adm_label, callback_data=f"adm_panel_{user_id}")])
    return InlineKeyboardMarkup(keyboard)


user_names = {}   # {user_id: নাম} — স্বাগতম মেসেজে নাম দেখানোর জন্য


def _remember_name(user):
    """টেলিগ্রাম প্রোফাইলের নাম মনে রাখে (সর্বোচ্চ ২৫ অক্ষর)"""
    if user:
        nm = (user.first_name or user.full_name or "").strip()
        if nm:
            user_names[user.id] = nm[:25]


def get_start_text(user_id):
    """Start মেনুর text"""
    default = "friend" if user_lang.get(user_id, "bn") == "en" else "বন্ধু"
    return get_text(user_id, "welcome").format(name=user_names.get(user_id, default))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    user_id = update.effective_user.id
    _remember_name(update.effective_user)

    # নতুন user — আগে ভাষা সিলেক্ট
    if user_id not in all_bot_users:
        all_bot_users.add(user_id)
        # Owner কে নোটিফাই করো
        user = update.effective_user
        name = user.full_name or str(user_id)
        username = f"@{user.username}" if user.username else "username নেই"
        try:
            msg = f"🎉 নতুন ইউজার এসেছে!\n\n📛 নাম: {name}\n🆔 আইডি: {user_id}\n🔗 ইউজারনেম: {username}"
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=msg)
        except Exception:
            pass
        # ভাষা সিলেক্ট স্ক্রিন দেখাও
        keyboard = [[
            InlineKeyboardButton("🇧🇩 বাংলা", callback_data=f"lang_bn_{user_id}"),
            InlineKeyboardButton("🇬🇧 English", callback_data=f"lang_en_{user_id}"),
        ]]
        sent = await update.message.reply_text(
            "🌐 Please select your language\nএকটি ভাষা বেছে নিন",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data["last_menu_msg_id"] = sent.message_id
        return

    # পুরনো user — সরাসরি মেনু (কোনো মেসেজ ডিলিট করব না)
    sent = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=get_start_text(user_id),
        reply_markup=get_start_keyboard(user_id)
    )
    context.user_data["last_menu_msg_id"] = sent.message_id


# ============================================
# /set — private chat এ বললে সঠিক নির্দেশনা দাও
# ============================================
async def set_command_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(get_text(user_id, "set_in_group"))


# ============================================
# গ্রুপের লিংক চ্যানেলে পাঠানো (একবারই)
# ============================================
async def log_group_link(context, chat):
    if chat.id in LOGGED_GROUPS:
        return
    LOGGED_GROUPS.add(chat.id)
    try:
        link_obj = await context.bot.create_chat_invite_link(chat.id, name="info")
        link = link_obj.invite_link
    except Exception:
        link = f"https://t.me/{chat.username}" if chat.username else "লিংক পাওয়া যায়নি"
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=f"✅ নতুন গ্রুপ\n📛 {chat.title}\n🆔 {chat.id}\n🔗 {link}"
        )
    except Exception as e:
        LOGGED_GROUPS.discard(chat.id)
        logging.error(f"log channel error: {e}")


# ============================================
# /set — গ্রুপ যোগ
# ============================================
async def set_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    user_id = update.effective_user.id
    gid = update.effective_chat.id
    title = update.effective_chat.title or str(gid)

    member = await context.bot.get_chat_member(gid, user_id)
    if member.status not in ["administrator", "creator"]:
        await _reply_and_cleanup(
            update, context,
            get_text(user_id, "not_group_admin")
        )
        return

    # বট admin কিনা চেক করো
    bot_member = await context.bot.get_chat_member(gid, context.bot.id)
    if bot_member.status != "administrator":
        await update.message.reply_text(
            get_text(user_id, "bot_not_admin")
        )
        return

    if gid in get_user_groups(user_id):
        await _reply_and_cleanup(
            update, context,
            get_text(user_id, "group_already_added").format(title=title, gid=gid, count=len(get_user_groups(user_id)))
        )
        return

    # সীমা পূর্ণ হলে নতুন গ্রুপ নেওয়া হবে না (OWNER বাদে)
    if user_id != OWNER_ID and len(get_user_groups(user_id)) >= MAX_GROUPS_PER_USER:
        await _reply_and_cleanup(
            update, context,
            get_text(user_id, "group_limit").format(limit=MAX_GROUPS_PER_USER)
        )
        return

    get_user_groups(user_id)[gid] = title

    # চ্যানেলে গ্রুপের লিংক পাঠাও (একবারই যাবে)
    await log_group_link(context, update.effective_chat)

    # ============================================
# গ্রুপের লিংক চ্যানেলে পাঠানো (একবারই)
# ============================================
async def log_group_link(context, chat):
    if chat.id in LOGGED_GROUPS:
        return
    LOGGED_GROUPS.add(chat.id)
    try:
        link_obj = await context.bot.create_chat_invite_link(chat.id, name="info")
        link = link_obj.invite_link
    except Exception:
        link = f"https://t.me/{chat.username}" if chat.username else "লিংক পাওয়া যায়নি"
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=f"✅ নতুন গ্রুপ\n📛 {chat.title}\n🆔 {chat.id}\n🔗 {link}"
        )
    except Exception as e:
        LOGGED_GROUPS.discard(chat.id)
        logging.error(f"log channel error: {e}")


# ============================================
# /set — গ্রুপ যোগ
# ============================================
async def set_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    user_id = update.effective_user.id
    gid = update.effective_chat.id
    title = update.effective_chat.title or str(gid)

    # "Remain Anonymous" চালু থাকলে মেসেজ গ্রুপের নামে আসে, বট এডমিনকে চিনতে পারে না
    _sc = update.message.sender_chat if update.message else None
    if user_id == 1087968824 or (_sc is not None and _sc.id == gid):
        await _reply_and_cleanup(
            update, context,
            "⚠️ আপনার \"Remain Anonymous\" চালু আছে, তাই আমি আপনাকে এডমিন হিসেবে চিনতে পারছি না।\n"
            "আপনি \"Remain Anonymous\" বন্ধ করুন, তারপর আবার /set দিন।\n\n"
            "⚠️ Your \"Remain Anonymous\" is on, so I cannot recognize you as an admin.\n"
            "Please turn off \"Remain Anonymous\", then send /set again.",
            delay=12
        )
        return

    member = await context.bot.get_chat_member(gid, user_id)
    if member.status not in ["administrator", "creator"]:
        await _reply_and_cleanup(
            update, context,
            get_text(user_id, "not_group_admin")
        )
        return

    # বট admin কিনা চেক করো
    bot_member = await context.bot.get_chat_member(gid, context.bot.id)
    if bot_member.status != "administrator":
        await update.message.reply_text(
            get_text(user_id, "bot_not_admin")
        )
        return

    if gid in get_user_groups(user_id):
        await _reply_and_cleanup(
            update, context,
            get_text(user_id, "group_already_added").format(title=title, gid=gid, count=len(get_user_groups(user_id)))
        )
        return

    get_user_groups(user_id)[gid] = title

    await _reply_and_cleanup(
        update, context,
        get_text(user_id, "group_added").format(title=title, gid=gid, count=len(get_user_groups(user_id)))
    )

    # চ্যানেলে গ্রুপের লিংক পাঠাও (একবারই যাবে)
    await log_group_link(context, update.effective_chat)
async def _delete_msg_job(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    try:
        await context.bot.delete_message(chat_id=d["chat_id"], message_id=d["message_id"])
    except Exception:
        pass


async def _reply_and_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, delay: int = 5):
    """মেসেজ পাঠায়, সাথে সাথে /set ডিলিট করে, মেসেজটা delay (৫) সেকেন্ড পরে ডিলিট করে"""
    chat_id = update.effective_chat.id
    sent = await context.bot.send_message(chat_id=chat_id, text=text)
    try:
        await update.message.delete()
    except Exception:
        pass
    context.job_queue.run_once(
        _delete_msg_job, delay,
        data={"chat_id": chat_id, "message_id": sent.message_id}
    )

# ============================================
# /groups
# ============================================
async def show_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    user_id = update.effective_user.id
    my_groups = get_user_groups(user_id)

    if not my_groups:
        await update.message.reply_text(get_text(user_id, "groups_empty"))
        return

    keyboard = []
    group_lines = ""
    for i, (gid, title) in enumerate(my_groups.items(), 1):
        group_lines += f"{i}. 📛 {title}\n    🆔 {gid}\n\n"
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, "btn_remove").format(title=title), callback_data=f"delgroup_{user_id}_{gid}")
        ])
    keyboard.append([InlineKeyboardButton(get_text(user_id, "btn_back"), callback_data=f"groups_back_{user_id}")])

    await update.message.reply_text(
        get_text(user_id, "groups_header").format(count=len(my_groups), lines=group_lines),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# media group buffer
_media_group_buffer = {}


async def _delete_setmsg_prompt(bot, user_id):
    info = user_setmsg_prompt.pop(user_id, None)
    if not info:
        return
    try:
        await bot.delete_message(chat_id=info[0], message_id=info[1])
    except Exception:
        pass

async def _flush_media_group(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    group_id = job_data["group_id"]
    buf_key = f"{user_id}_{group_id}"
    buf = _media_group_buffer.pop(buf_key, None)
    if not buf:
        return

    gdata = get_group_data(user_id, group_id)
    items = buf["items"]
    caption = buf["caption"]
    chat_id = buf.get("chat_id")

    if not items:
        if chat_id:
            await context.bot.send_message(chat_id=chat_id, text=get_text(user_id, "send_media"))
        return
    if _tg_len(caption) > AD_CAPTION_LIMIT:
        if chat_id:
            await context.bot.send_message(chat_id=chat_id, text=_ad_too_long_text(user_id, _tg_len(caption), AD_CAPTION_LIMIT))
        return

    _apply_items(gdata, items, caption)

    if not chat_id:
        return

    # interval সিলেক্ট দেখাও
    my_groups = get_user_groups(user_id)
    g_title = my_groups.get(group_id, str(group_id))
    type_emoji = _ad_emoji(gdata)
    keyboard = _interval_keyboard(user_id, group_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text=get_text(user_id, "ad_set_one").format(emoji=type_emoji, title=g_title),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await _delete_setmsg_prompt(context.bot, user_id)


async def _flush_media_group_all(context: ContextTypes.DEFAULT_TYPE):
    """All Group মোডে media group flush"""
    job_data = context.job.data
    user_id = job_data["user_id"]
    buf_key = f"{user_id}_all"
    buf = _media_group_buffer.pop(buf_key, None)
    if not buf:
        return

    items = buf["items"]
    caption = buf["caption"]
    chat_id = buf.get("chat_id")
    my_groups = get_user_groups(user_id)

    if not items:
        if chat_id:
            await context.bot.send_message(chat_id=chat_id, text=get_text(user_id, "send_media"))
        return
    if _tg_len(caption) > AD_CAPTION_LIMIT:
        if chat_id:
            await context.bot.send_message(chat_id=chat_id, text=_ad_too_long_text(user_id, _tg_len(caption), AD_CAPTION_LIMIT))
        return

    for gid in my_groups:
        # All Group মোডে লক করা গ্রুপ চুপচাপ স্কিপ করো
        if gid in group_lock and group_lock[gid] != user_id:
            continue
        gdata = get_group_data(user_id, gid)
        _apply_items(gdata, items, caption)

    if user_id in user_waiting_setmsg:
        del user_waiting_setmsg[user_id]

    if not chat_id:
        return

    # বাস্তবে যতগুলো group set হয়েছে (যেগুলো লক করা নয়)
    actual_count = len([gid for gid in my_groups if gid not in group_lock or group_lock[gid] == user_id])
    type_emoji = "📸📸" if len(items) > 1 else _ITEM_EMOJI.get(items[0]["type"], "📎")
    keyboard = [
        [
            InlineKeyboardButton(get_text(user_id, "btn_15min"), callback_data=f"intv_all_{user_id}_15"),
            InlineKeyboardButton(get_text(user_id, "btn_30min"), callback_data=f"intv_all_{user_id}_30"),
        ],
        [
            InlineKeyboardButton(get_text(user_id, "btn_45min"), callback_data=f"intv_all_{user_id}_45"),
            InlineKeyboardButton(get_text(user_id, "btn_60min"), callback_data=f"intv_all_{user_id}_60"),
        ],
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text=get_text(user_id, "ad_set_all").format(emoji=type_emoji, count=actual_count),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await _delete_setmsg_prompt(context.bot, user_id)


def _interval_keyboard(user_id, group_id):
    return [
        _custom_interval_row(user_id, group_id),
        [
            InlineKeyboardButton(get_text(user_id, "btn_15min"), callback_data=f"intv_{user_id}_{group_id}_15"),
            InlineKeyboardButton(get_text(user_id, "btn_30min"), callback_data=f"intv_{user_id}_{group_id}_30"),
        ],
        [
            InlineKeyboardButton(get_text(user_id, "btn_45min"), callback_data=f"intv_{user_id}_{group_id}_45"),
            InlineKeyboardButton(get_text(user_id, "btn_60min"), callback_data=f"intv_{user_id}_{group_id}_60"),
        ],
        _back_row(user_id),
    ]
  
# ============================================================
# ⚙️ Custom Interval
# ============================================================
from types import SimpleNamespace as _NS

user_waiting_interval = {}   # {user_id: {"gid": group_id বা "all", "ts": সময়}}
CUSTOM_MIN_MINUTES = 15
CUSTOM_MAX_MINUTES = 3 * 24 * 60   # সর্বোচ্চ ৩ দিন


def parse_custom_interval(text):
    """মিনিট রিটার্ন করে। ভুল হলে None।
    1-12 (শুধু সংখ্যা) = ঘন্টা | 15+ (শুধু সংখ্যা) = মিনিট
    1h / 1 h = ঘন্টা | 16m / 16 m = মিনিট"""
    t = (text or "").strip().lower().translate(BN_DIGITS_REV)
    m = re.match(r"^(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)?$", t)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit is None:
        minutes = n * 60 if 1 <= n <= 12 else n
    elif unit.startswith("h"):
        minutes = n * 60
    else:
        minutes = n
    if minutes < CUSTOM_MIN_MINUTES or minutes > CUSTOM_MAX_MINUTES:
        return None
    return minutes


def _custom_interval_row(user_id, group_id):
    cb = f"intvc_all_{user_id}" if group_id == "all" else f"intvc_{user_id}_{group_id}"
    return [InlineKeyboardButton(get_text(user_id, "btn_custom"), callback_data=cb)]


def _back_row(user_id):
    return [InlineKeyboardButton(get_text(user_id, "btn_back"), callback_data=f"start_back_{user_id}")]


class _MsgQuery:
    """টেক্সট মেসেজকে callback query এর মতো চালায়, যাতে আগের intv_ লজিকই ব্যবহার হয়"""
    def __init__(self, message, user, data):
        self.message = message
        self.from_user = user
        self.data = data

    async def answer(self, *args, **kwargs):
        return None

    async def edit_message_text(self, text, reply_markup=None, **kwargs):
        return await self.message.reply_text(text, reply_markup=reply_markup, **kwargs)


async def custom_interval_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_waiting_interval.get(user_id)
    if not state:
        return
    minutes = parse_custom_interval(update.message.text)
    if minutes is None:
        user_waiting_interval.pop(user_id, None)   # ভুল হলে সেশন বন্ধ
        kb = [[InlineKeyboardButton(get_text(user_id, "btn_main_menu"), callback_data=f"start_back_{user_id}")]]
        await update.message.reply_text(
            get_text(user_id, "custom_intv_bad"),
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    user_waiting_interval.pop(user_id, None)
    gid = state["gid"]
    data = f"intv_all_{user_id}_{minutes}" if gid == "all" else f"intv_{user_id}_{gid}_{minutes}"
    fake_update = _NS(callback_query=_MsgQuery(update.message, update.effective_user, data))
    await button_callback(fake_update, context) 
      
async def schedule_time_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_waiting_schedule.get(user_id)
    if not state:
        return
    parsed = parse_custom_time(update.message.text)
    if not parsed:
        user_waiting_schedule.pop(user_id, None)
        await update.message.reply_text(get_text(user_id, "custom_bad_format"))
        return

    h, mi = parsed
    gid = state["gid"]
    g_title = get_user_groups(user_id).get(gid, str(gid))

    if state["step"] == "off":
        user_waiting_schedule.pop(user_id, None)
        await update.message.reply_text(
            get_text(user_id, "schedule_set_on").format(title=g_title, off=format_schedule_time(user_id, h, mi)),
            reply_markup=InlineKeyboardMarkup(_on_keyboard(user_id, gid, h, mi))
        )
        return

    user_waiting_schedule.pop(user_id, None)
    off_h, off_m = state["off_h"], state["off_m"]
    if off_h * 60 + off_m == h * 60 + mi:
        await update.message.reply_text(get_text(user_id, "custom_same_time"))
        return
    if user_id not in user_group_schedule:
        user_group_schedule[user_id] = {}
    user_group_schedule[user_id][gid] = {
        "off_hour": off_h, "off_min": off_m,
        "on_hour": h, "on_min": mi,
        "night_msg_id": None, "morning_msg_id": None,
    }
    await update.message.reply_text(
        get_text(user_id, "schedule_done").format(
            title=g_title,
            off=format_schedule_time(user_id, off_h, off_m),
            on=format_schedule_time(user_id, h, mi),
        ),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, "btn_back"), callback_data=f"offgp_back_{user_id}")]])
    )


async def setmsg_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message

    if user_id != OWNER_ID and user_id in BANNED_USERS:
        return
    if user_id == OWNER_ID and user_id in admin_waiting:
        await admin_input_receive(update, context)
        return

    _iv = user_waiting_interval.get(user_id)
    if _iv:
        if datetime.now().timestamp() - _iv.get("ts", 0) > 300:
            user_waiting_interval.pop(user_id, None)
        elif msg and msg.text:
            await custom_interval_receive(update, context)
            return

    _st = user_waiting_schedule.get(user_id)
    if _st:
        if datetime.now().timestamp() - _st.get("ts", 0) > 300:
            user_waiting_schedule.pop(user_id, None)
        elif msg and msg.text:
            await schedule_time_receive(update, context)
            return

    if user_id not in user_waiting_setmsg:
        return
    if msg is None:
        return

    # বিজ্ঞাপন অনেক লম্বা হলে আবার পাঠাতে বলো (অ্যালবামের ক্যাপশন flush এর সময় আলাদা করে দেখা হয়)
    if not msg.media_group_id:
        _ad_text = msg.text or msg.caption or ""
        _limit = AD_TEXT_LIMIT if msg.text else AD_CAPTION_LIMIT
        if _tg_len(_ad_text) > _limit:
            await msg.reply_text(_ad_too_long_text(user_id, _tg_len(_ad_text), _limit))
            return

    group_id = user_waiting_setmsg[user_id]
    my_groups = get_user_groups(user_id)

    # ✅ All Group মোড
    if group_id == "all":
        # Media Group (একাধিক ছবি/ভিডিও) — All Group এ সাপোর্ট
        if msg.media_group_id:
            buf_key = f"{user_id}_all"
            buf = _media_group_buffer.get(buf_key)
            item = _msg_to_item(msg)
            if buf and buf["media_group_id"] == msg.media_group_id:
                if item:
                    buf["items"].append(item)
                if msg.caption:
                    buf["caption"] = msg.caption
            else:
                _media_group_buffer[buf_key] = {
                    "media_group_id": msg.media_group_id,
                    "items": [item] if item else [],
                    "caption": msg.caption or "",
                    "chat_id": msg.chat_id,
                    "is_all": True,
                    "user_id": user_id,
                }
                context.application.job_queue.run_once(
                    _flush_media_group_all,
                    when=1.5,
                    data={"user_id": user_id},
                    name=f"flush_mg_{user_id}_all"
                )
            return

        content_ok = False
        for gid in my_groups:
            # All Group মোডে লক করা গ্রুপ স্কিপ করো
            if gid in group_lock and group_lock[gid] != user_id:
                continue
            gdata = get_group_data(user_id, gid)
            if _set_ad_from_message(gdata, msg):
                content_ok = True

        if not content_ok:
            await msg.reply_text(get_text(user_id, "send_media"))
            return

        del user_waiting_setmsg[user_id]

        # বাস্তবে যতগুলো group set হয়েছে (যেগুলো লক করা নয়)
        actual_count = len([gid for gid in my_groups if gid not in group_lock or group_lock[gid] == user_id])
        type_emoji = _msg_emoji(msg)
        keyboard = [
            _custom_interval_row(user_id, "all"),
            [
                InlineKeyboardButton(get_text(user_id, "btn_15min"), callback_data=f"intv_all_{user_id}_15"),
                InlineKeyboardButton(get_text(user_id, "btn_30min"), callback_data=f"intv_all_{user_id}_30"),
            ],
            [
                InlineKeyboardButton(get_text(user_id, "btn_45min"), callback_data=f"intv_all_{user_id}_45"),
                InlineKeyboardButton(get_text(user_id, "btn_60min"), callback_data=f"intv_all_{user_id}_60"),
            ],
            _back_row(user_id),
        ]
        await msg.reply_text(
            get_text(user_id, "ad_set_all").format(emoji=type_emoji, count=actual_count),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await _delete_setmsg_prompt(context.bot, user_id)
        return

    # ─── নির্দিষ্ট একটি গ্রুপ ───
    gdata = get_group_data(user_id, group_id)
    g_title = my_groups.get(group_id, str(group_id))

    # Media Group
    if msg.media_group_id:
        buf_key = f"{user_id}_{group_id}"
        buf = _media_group_buffer.get(buf_key)
        item = _msg_to_item(msg)
        if buf and buf["media_group_id"] == msg.media_group_id:
            if item:
                buf["items"].append(item)
            if msg.caption:
                buf["caption"] = msg.caption
        else:
            _media_group_buffer[buf_key] = {
                "media_group_id": msg.media_group_id,
                "items": [item] if item else [],
                "caption": msg.caption or "",
                "chat_id": msg.chat_id,
            }
            context.application.job_queue.run_once(
                _flush_media_group,
                when=1.5,
                data={"user_id": user_id, "group_id": group_id},
                name=f"flush_mg_{user_id}_{group_id}"
            )
        return

    # একটা মেসেজ: টেক্সট, ছবি, ভিডিও, ভয়েস, অডিও, স্টিকার, GIF, ফাইল, ভিডিও মেসেজ
    if not _set_ad_from_message(gdata, msg):
        await update.message.reply_text(get_text(user_id, "send_media"))
        return

    del user_waiting_setmsg[user_id]

    type_emoji = _ad_emoji(gdata)
    keyboard = _interval_keyboard(user_id, group_id)
    await update.message.reply_text(
        get_text(user_id, "ad_set_one").format(emoji=type_emoji, title=g_title),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await _delete_setmsg_prompt(context.bot, user_id)


# ============================================
# NEW - Group Lock + Broadcast Request Helper Functions
# ============================================
async def _get_user_name(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    """ইউজারের নাম পাওয়ার চেষ্টা করে"""
    try:
        chat = await context.bot.get_chat(user_id)
        return chat.first_name or str(user_id)
    except Exception:
        return str(user_id)

async def _stop_broadcast_for_group(context: ContextTypes.DEFAULT_TYPE, user_id: int, group_id: int):
    """একটা নির্দিষ্ট গ্রুপের broadcast বন্ধ করো"""
    gdata = get_group_data(user_id, group_id)
    gdata["is_running"] = False
    gdata["manual_stop"] = True
    gdata["next_broadcast_time"] = None
    
    jobs = context.application.job_queue.get_jobs_by_name(f"broadcast_{user_id}_{group_id}")
    for job in jobs:
        job.schedule_removal()
    
    old_id = gdata.get("last_msg_id")
    if old_id:
        id_list = old_id if isinstance(old_id, list) else [old_id]
        for mid in id_list:
            try:
                await context.bot.delete_message(chat_id=group_id, message_id=mid)
            except Exception:
                pass
        gdata["last_msg_id"] = None

async def _check_broadcast_lock_and_request(context: ContextTypes.DEFAULT_TYPE, user_id: int, group_id: int, group_title: str, query=None) -> bool:
    """
    ব্রডকাস্ট লক চেক করে। লক থাকলে রিকুয়েস্ট অপশন দেখায়।
    query দেওয়া থাকলে বর্তমান মেসেজ এডিট করবে, নাহলে নতুন মেসেজ পাঠাবে।
    রিটার্ন: True = ব্রডকাস্ট চালু হতে পারে, False = ব্লক করা হয়েছে
    """
    if group_id not in group_lock or group_lock[group_id] == user_id:
        return True

    owner_id = group_lock[group_id]
    owner_name = await _get_user_name(owner_id, context)

    existing_pending = None
    pending_timestamp = None
    for req_id, req in broadcast_requests.items():
        if req["from_user"] == user_id and req["group_id"] == group_id and req["status"] == "pending":
            existing_pending = req_id
            pending_timestamp = req.get("timestamp", 0)
            break

    keyboard = [
        [InlineKeyboardButton(get_text(user_id, "btn_request_broadcast"), callback_data=f"bcast_req_{user_id}_{group_id}_{owner_id}")],
        [InlineKeyboardButton(get_text(user_id, "btn_back"), callback_data=f"start_back_{user_id}")],
    ]

    if existing_pending:
        now_ts = datetime.now(timezone.utc).timestamp()
        remaining = 300 - int(now_ts - pending_timestamp)
        if remaining > 0:
            mins = remaining // 60
            secs = remaining % 60
            lang = user_lang.get(user_id, "bn")
            if lang == "en":
                countdown = f"{mins}m {secs}s"
            else:
                countdown = f"{mins}মি {secs}সে"
            text = get_text(user_id, "broadcast_request_already_pending").format(countdown=countdown)
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, "btn_back"), callback_data=f"start_back_{user_id}")]])
            if query:
                await query.edit_message_text(text, reply_markup=back_kb)
            else:
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=back_kb)
            return False
        else:
            broadcast_requests.pop(existing_pending, None)

    text = get_text(user_id, "broadcast_locked").format(owner_name=owner_name, group_title=group_title)
    markup = InlineKeyboardMarkup(keyboard)
    if query:
        await query.edit_message_text(text, reply_markup=markup)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=markup)
    return False

async def _send_broadcast_request(context: ContextTypes.DEFAULT_TYPE, from_user_id: int, group_id: int, owner_id: int):
    """Owner কে broadcast request পাঠাও"""
    group_title = get_user_groups(from_user_id).get(group_id, str(group_id))
    from_user_name = await _get_user_name(from_user_id, context)
    
    request_id = f"bcast_{from_user_id}_{group_id}_{int(datetime.now().timestamp())}"
    
    broadcast_requests[request_id] = {
        "from_user": from_user_id,
        "to_user": owner_id,
        "group_id": group_id,
        "group_title": group_title,
        "status": "pending",
        "timestamp": datetime.now().timestamp()
    }
    
    # Owner-কে মেসেজ
    owner_text = get_text(owner_id, "broadcast_request_to_owner").format(
        group_title=group_title,
        name=from_user_name,
        id=from_user_id,
        time=datetime.now(BD_TZ).strftime("%I:%M %p - %d/%m/%Y")
    )
    
    keyboard = [
        [
            InlineKeyboardButton(get_text(owner_id, "btn_allow"), callback_data=f"bcast_allow_{request_id}"),
            InlineKeyboardButton(get_text(owner_id, "btn_reject"), callback_data=f"bcast_reject_{request_id}"),
        ]
    ]
    
    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text=owner_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return True
    except Exception as e:
        logging.error(f"Failed to send broadcast request to owner {owner_id}: {e}")
        await context.bot.send_message(
            chat_id=from_user_id,
            text="❌ রিকুয়েস্ট পাঠাতে ব্যর্থ হয়েছে! এডমিন বটকে ব্লক করে থাকতে পারে।"
        )
        return False

async def _cleanup_expired_broadcast_requests():
    """৫ মিনিটের বেশি পুরনো pending broadcast requests ক্লিনাপ করো"""
    now = datetime.now().timestamp()
    expired = []
    for req_id, req in broadcast_requests.items():
        if req.get("status") == "pending" and now - req.get("timestamp", 0) > 300:
            expired.append(req_id)
    for req_id in expired:
        broadcast_requests.pop(req_id, None)


# ============================================
# Request সিস্টেমের হেল্পার ফাংশন (লিমিট ছাড়া)
# ============================================
def _get_other_admin_with_schedule(group_id: int, current_user_id: int):
    """গ্রুপে অন্য কোন এডমিন শিডিউল সেট করেছে কিনা চেক করে"""
    for uid, schedules in user_group_schedule.items():
        if uid != current_user_id and group_id in schedules and schedules[group_id].get("off_hour") is not None:
            return uid, schedules[group_id]
    return None, None


async def _send_request_to_admin(context: ContextTypes.DEFAULT_TYPE, from_user_id: int, to_admin_id: int, group_id: int, group_title: str):
    """এডমিনের কাছে রিকুয়েস্ট পাঠায়"""
    request_id = f"{from_user_id}_{group_id}_{int(datetime.now().timestamp())}"
    from_user_name = await _get_user_name(from_user_id, context)
    
    # পেন্ডিং রিকুয়েস্ট সেভ
    pending_requests[request_id] = {
        "from_user": from_user_id,
        "to_user": to_admin_id,
        "group_id": group_id,
        "group_title": group_title,
        "status": "pending",
        "timestamp": datetime.now().timestamp()
    }
    
    # এডমিনের ভাষা অনুযায়ী টেক্সট
    admin_text = get_text(to_admin_id, "request_to_admin").format(
        group_title=group_title,
        name=from_user_name,
        id=from_user_id,
        time=datetime.now(BD_TZ).strftime("%I:%M %p - %d/%m/%Y")
    )
    
    keyboard = [
        [
            InlineKeyboardButton(get_text(to_admin_id, "btn_allow"), callback_data=f"req_allow_{request_id}"),
            InlineKeyboardButton(get_text(to_admin_id, "btn_reject"), callback_data=f"req_reject_{request_id}"),
        ]
    ]
    
    try:
        await context.bot.send_message(
            chat_id=to_admin_id,
            text=admin_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return True
    except Exception as e:
        logging.error(f"Failed to send request to admin {to_admin_id}: {e}")
        return False


async def _cleanup_expired_requests():
    """২৪ ঘণ্টা পুরনো রিকুয়েস্ট ক্লিনাপ করে"""
    now = datetime.now().timestamp()
    expired = []
    for req_id, req in pending_requests.items():
        if now - req.get("timestamp", 0) > 300:  # 5 minit
            expired.append(req_id)
    for req_id in expired:
        pending_requests.pop(req_id, None)


# ============================================
# user বট block করলে owner notify + data cleanup
# ============================================
async def _handle_user_blocked(context, user_id: int):
    """User বট block করলে সব data মুছে owner কে জানাও।"""
    all_bot_users.discard(user_id)
    user_target_groups.pop(user_id, None)
    group_broadcast_data.pop(user_id, None)
    user_group_schedule.pop(user_id, None)
    user_lang.pop(user_id, None)
    NOTIFY_OFF.discard(user_id)
    # NEW: group_lock and broadcast_requests cleanup
    for gid, owner in list(group_lock.items()):
        if owner == user_id:
            del group_lock[gid]
    for req_id, req in list(broadcast_requests.items()):
        if req.get("from_user") == user_id or req.get("to_user") == user_id:
            del broadcast_requests[req_id]
    # সব broadcast job বন্ধ করো
    for job in context.application.job_queue.jobs():
        if job.data and job.data.get("user_id") == user_id:
            job.schedule_removal()
    if banned:
        return
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=(
                f"🚫 একজন user বট block করেছে!\n\n"
                f"🆔 User ID: {user_id}\n"
                f"🗑 সব ডেটা মুছে দেওয়া হয়েছে।"
            )
        )
    except Exception as e:
        logging.error(f"block notify error: {e}")


# ============================================
# Callback Handler
# ============================================
async def ban_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id == OWNER_ID or user.id not in BANNED_USERS:
        return
    if update.my_chat_member or update.chat_member:
        return
    if update.callback_query:
        await update.callback_query.answer("🚫 You are banned", show_alert=True)
    elif update.message and update.effective_chat.type == "private":
        txt = (update.message.text or "").strip()
        if txt.startswith("/start"):
            await update.message.reply_text(
                "🚫 <b>You are banned</b>\n\n"
                "আপনাকে এই বট ব্যবহার করা থেকে ব্যান করা হয়েছে।\n\n"
                f"🆔 আপনার ID: <code>{user.id}</code>\n\n"
                "✅ <b>আনব্যান হওয়ার জন্য যা করতে হবে:</b>\n"
                "1️⃣ নিচের \"💬 Support\" বাটনে চাপ দিয়ে সাপোর্ট গ্রুপে যান\n"
                "2️⃣ গ্রুপে আপনার ID (ওপরের নম্বরটা) লিখে আনব্যানের অনুরোধ করুন\n"
                "3️⃣ এডমিনের উত্তরের জন্য অপেক্ষা করুন",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("💬 Support", url="https://t.me/teemcs")]]
                ),
            )
        else:
            await update.message.reply_text("🚫 You are banned")
    raise ApplicationHandlerStop


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if user_id != OWNER_ID and user_id in BANNED_USERS:
        await query.answer("🚫 You are banned", show_alert=True)
        return

    _color_shift["n"] = (_color_shift["n"] + 1) % 3   # প্রতি ক্লিকে রং এক ধাপ ঘুরবে

    await query.answer()
    cb = query.data
    _remember_name(query.from_user)
    if not (cb.startswith("offgp_coff_") or cb.startswith("offgp_con_")):
        user_waiting_schedule.pop(query.from_user.id, None)
    if not cb.startswith("intvc_"):
        user_waiting_interval.pop(query.from_user.id, None)    

    # ─── এডমিন প্যানেল ───
    if cb.startswith("adm_"):
        await _handle_adm_callback(query, context, cb)
        return
    admin_waiting.pop(user_id, None)

    # ─── NEW - Broadcast Request callbacks ───
    if cb.startswith("bcast_req_"):
        # bcast_req_{from_user}_{group_id}_{owner_id}
        parts = cb[10:].split("_")
        from_user = int(parts[0])
        group_id = int(parts[1])
        owner_id = int(parts[2])
        
        if user_id != from_user:
            await query.answer(get_text(user_id, "not_yours"), show_alert=True)
            return
        
        await _send_broadcast_request(context, from_user, group_id, owner_id)
        await query.edit_message_text(
            get_text(from_user, "broadcast_request_sent").format(owner_name=await _get_user_name(owner_id, context)),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(from_user, "btn_back"), callback_data=f"start_back_{from_user}")]])
        )
        return
    
    # ─── bcast_allow_ callback ───
    if cb.startswith("bcast_allow_"):
        request_id = cb[12:]  # "bcast_allow_" এর পরের অংশ
        req = broadcast_requests.get(request_id)
        if not req or req.get("status") != "pending":
            await query.edit_message_text(get_text(user_id, "broadcast_request_expired"))
            return

        if datetime.now().timestamp() - req.get("timestamp", 0) > 300:
            broadcast_requests.pop(request_id, None)
            await query.edit_message_text(get_text(user_id, "broadcast_request_expired"))
            return
        
        if user_id != req["to_user"]:
            await query.answer(get_text(user_id, "not_yours"), show_alert=True)
            return
        
        # রিকুয়েস্ট approve
        req["status"] = "approved"
        from_user_id = req["from_user"]
        group_id = req["group_id"]
        group_title = req["group_title"]
        owner_id = req["to_user"]
        
        # Owner-এর broadcast বন্ধ করো (শুধু এই group_id-এর)
        if owner_id in group_broadcast_data and group_id in group_broadcast_data[owner_id]:
            await _stop_broadcast_for_group(context, owner_id, group_id)
        
        # group_lock মুছে ফেলো
        group_lock.pop(group_id, None)
        
        # রিকুয়েস্টকারীকে মেসেজ
        try:
            await context.bot.send_message(
                chat_id=from_user_id,
                text=get_text(from_user_id, "broadcast_request_approved").format(
                    owner_name=await _get_user_name(owner_id, context),
                    group_title=group_title
                )
            )
        except Exception:
            pass
        
        # এডমিনকে নোটিফিকেশন
        await query.edit_message_text(
            get_text(user_id, "broadcast_owner_approved").format(
                group_title=group_title,
                name=await _get_user_name(from_user_id, context),
                id=from_user_id
            ),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, "btn_main_menu"), callback_data=f"start_back_{user_id}")]])
        )
        
        # রিকুয়েস্ট ক্লিনাপ
        broadcast_requests.pop(request_id, None)
        return
    
    # ─── bcast_reject_ callback ───
    if cb.startswith("bcast_reject_"):
        request_id = cb[13:]  # "bcast_reject_" এর পরের অংশ
        req = broadcast_requests.get(request_id)
        if not req or req.get("status") != "pending":
            await query.edit_message_text(get_text(user_id, "broadcast_request_expired"))
            return

        if datetime.now().timestamp() - req.get("timestamp", 0) > 300:
            broadcast_requests.pop(request_id, None)
            await query.edit_message_text(get_text(user_id, "broadcast_request_expired"))
            return
        
        if user_id != req["to_user"]:
            await query.answer(get_text(user_id, "not_yours"), show_alert=True)
            return
        
        # রিকুয়েস্ট reject
        req["status"] = "rejected"
        from_user_id = req["from_user"]
        group_id = req["group_id"]
        group_title = req["group_title"]
        owner_id = req["to_user"]
        
        # রিকুয়েস্টকারীকে মেসেজ
        try:
            await context.bot.send_message(
                chat_id=from_user_id,
                text=get_text(from_user_id, "broadcast_request_rejected").format(
                    owner_name=await _get_user_name(owner_id, context)
                )
            )
        except Exception:
            pass
        
        # এডমিনকে নোটিফিকেশন
        await query.edit_message_text(
            get_text(user_id, "broadcast_owner_rejected").format(
                group_title=group_title,
                name=await _get_user_name(from_user_id, context),
                id=from_user_id
            )
        )
        
        # রিকুয়েস্ট ক্লিনাপ
        broadcast_requests.pop(request_id, None)
        return

    # ─── Request সিস্টেমের callback ───
    if cb.startswith("req_allow_"):
        request_id = cb[10:]  # "req_allow_" এর পরের অংশ
        req = pending_requests.get(request_id)
        if not req or req.get("status") != "pending":
            await query.edit_message_text(get_text(user_id, "request_expired"))
            return
        
        if user_id != req["to_user"]:
            await query.answer(get_text(user_id, "not_yours"), show_alert=True)
            return
        
        # রিকুয়েস্ট approve
        req["status"] = "approved"
        from_user_id = req["from_user"]
        group_id = req["group_id"]
        group_title = req["group_title"]
        
        # অন্য এডমিনের শিডিউল ডিলিট করো
        if user_id in user_group_schedule and group_id in user_group_schedule[user_id]:
            del user_group_schedule[user_id][group_id]
        
        # রিকুয়েস্টকারীকে মেসেজ (শুধু টেক্সট, কোন বাটন নেই)
        try:
            await context.bot.send_message(
                chat_id=from_user_id,
                text=get_text(from_user_id, "request_approved").format(name=await _get_user_name(user_id, context))
            )
        except Exception:
            pass
        
        # এডমিনকে নোটিফিকেশন
        await query.edit_message_text(
            get_text(user_id, "admin_allowed").format(
                group_title=group_title,
                name=await _get_user_name(from_user_id, context),
                id=from_user_id
            )
        )
        
        # রিকুয়েস্ট ক্লিনাপ
        pending_requests.pop(request_id, None)
        return
    
    # ─── req_reject_ callback ───
    if cb.startswith("req_reject_"):
        request_id = cb[11:]  # "req_reject_" এর পরের অংশ
        req = pending_requests.get(request_id)
        if not req or req.get("status") != "pending":
            await query.edit_message_text(get_text(user_id, "request_expired"))
            return
        
        if user_id != req["to_user"]:
            await query.answer(get_text(user_id, "not_yours"), show_alert=True)
            return
        
        # রিকুয়েস্ট reject
        req["status"] = "rejected"
        from_user_id = req["from_user"]
        group_id = req["group_id"]
        group_title = req["group_title"]
        
        # রিকুয়েস্টকারীকে মেসেজ
        try:
            await context.bot.send_message(
                chat_id=from_user_id,
                text=get_text(from_user_id, "request_rejected").format(name=await _get_user_name(user_id, context))
            )
        except Exception:
            pass
        
        # এডমিনকে নোটিফিকেশন
        await query.edit_message_text(
            get_text(user_id, "admin_rejected").format(
                group_title=group_title,
                name=await _get_user_name(from_user_id, context),
                id=from_user_id
            )
        )
        
        # রিকুয়েস্ট ক্লিনাপ
        pending_requests.pop(request_id, None)
        return

    # ─── menu_ বাটন — /start মেনু থেকে ───
    if cb.startswith("menu_"):
        parts = cb.split("_")
        action = parts[1]
        owner_id = int(parts[2])

        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_yours"), show_alert=True)
            return

        if action == "groups":
            my_groups = get_user_groups(owner_id)
            if not my_groups:
                await query.edit_message_text(
                    get_text(owner_id, "groups_empty"),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
                )
                return
            keyboard = []
            group_lines = ""
            for i, (gid, title) in enumerate(my_groups.items(), 1):
                group_lines += f"{i}. 📛 {title}\n    🆔 {gid}\n\n"
                keyboard.append([InlineKeyboardButton(get_text(owner_id, "btn_remove").format(title=title), callback_data=f"delgroup_{owner_id}_{gid}")])
            keyboard.append([InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"groups_back_{owner_id}")])
            await query.edit_message_text(
                get_text(owner_id, "groups_header").format(count=len(my_groups), lines=group_lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        if action == "setmsg":
            now_utc_hour = datetime.now(timezone.utc).hour
            is_night_break = (now_utc_hour >= 16) or (now_utc_hour < 4)
            if is_night_break:
                await query.edit_message_text(
                    get_text(owner_id, "night_break"),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
                )
                return
            my_groups = get_user_groups(owner_id)
            if not my_groups:
                await query.edit_message_text(
                    get_text(owner_id, "no_group_set"),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
                )
                return
            keyboard = []
            for gid, title in my_groups.items():
                keyboard.append([InlineKeyboardButton(f"📛 {title}", callback_data=f"setmsg_sel_{owner_id}_{gid}")])
            keyboard.append([InlineKeyboardButton("📡 All Group", callback_data=f"setmsg_sel_{owner_id}_all")])
            keyboard.append([InlineKeyboardButton(get_text(owner_id, "btn_cancel"), callback_data=f"setmsg_cancel_{owner_id}")])
            await query.edit_message_text(
                get_text(owner_id, "select_group_ad"),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        if action == "status":
            await _show_status_menu(query, owner_id)
            return

        if action == "stop":
            active = _get_active_groups(owner_id)
            if not active:
                await query.edit_message_text(
                    get_text(owner_id, "no_broadcast"),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
                )
                return
            keyboard = []
            for gid, title in active.items():
                keyboard.append([InlineKeyboardButton(f"🛑 {title}", callback_data=f"stopgrp_{owner_id}_{gid}")])
            keyboard.append([InlineKeyboardButton(get_text(owner_id, "btn_stop_all"), callback_data=f"stopgrp_{owner_id}_all")])
            keyboard.append([InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")])
            await query.edit_message_text(
                get_text(owner_id, "stop_header").format(count=len(active)),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        if action == "offgp":
            my_groups = get_user_groups(owner_id)
            if not my_groups:
                await query.edit_message_text(
                    get_text(owner_id, "no_group_set"),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
                )
                return
            keyboard = []
            for gid, title in my_groups.items():
                keyboard.append([InlineKeyboardButton(f"📛 {title}", callback_data=f"offgp_grp_{owner_id}_{gid}")])
            keyboard.append([InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")])
            await query.edit_message_text(
                get_text(owner_id, "select_group_schedule"),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        if action == "lang":
            keyboard = [[
                InlineKeyboardButton("🇧🇩 বাংলা", callback_data=f"lang_bn_{owner_id}"),
                InlineKeyboardButton("🇬🇧 English", callback_data=f"lang_en_{owner_id}"),
            ]]
            await query.edit_message_text(
                "🌐 Please select your language\nএকটি ভাষা বেছে নিন",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        if action == "help":
            await query.edit_message_text(
                get_text(owner_id, "help_text"),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
            )
            return

        return

    # ─── setmsg_cancel — বাতিল ───
    if cb.startswith("setmsg_cancel_"):
        owner_id = int(cb[len("setmsg_cancel_"):])
        if user_id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        # waiting state ক্লিয়ার
        user_waiting_setmsg.pop(owner_id, None)
        user_setmsg_prompt.pop(owner_id, None)
        context.user_data.pop("pending_photo", None)
        context.user_data.pop("pending_caption", None)
        context.user_data.pop("pending_type", None)
        await query.edit_message_text(
            get_start_text(owner_id),
            reply_markup=get_start_keyboard(owner_id)
        )
        return

    # ─── setmsg_sel_all — All Group সিলেক্ট ───
    if cb.startswith("setmsg_sel_") and cb.endswith("_all"):
        parts = cb[len("setmsg_sel_"):]
        owner_id = int(parts.replace("_all", ""))

        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_yours"), show_alert=True)
            return

        my_groups = get_user_groups(owner_id)
        available_count = len([gid for gid in my_groups if gid not in group_lock or group_lock[gid] == owner_id])

        # pending content আছে কিনা চেক (ছবি সহ /setmsg)
        pending_type = context.user_data.get("pending_type")
        if pending_type == "photo":
            for gid in my_groups:
                if gid in group_lock and group_lock[gid] != owner_id:
                    continue
                gdata = get_group_data(owner_id, gid)
                gdata["broadcast_photo"] = context.user_data.get("pending_photo")
                gdata["broadcast_msg"] = context.user_data.get("pending_caption", "")
                gdata["broadcast_video"] = None
                gdata["broadcast_media_group"] = None
            context.user_data.pop("pending_photo", None)
            context.user_data.pop("pending_caption", None)
            context.user_data.pop("pending_type", None)
            keyboard = [
                [
                    InlineKeyboardButton(get_text(owner_id, "btn_15min"), callback_data=f"intv_all_{owner_id}_15"),
                    InlineKeyboardButton(get_text(owner_id, "btn_30min"), callback_data=f"intv_all_{owner_id}_30"),
                ],
                [
                    InlineKeyboardButton(get_text(owner_id, "btn_45min"), callback_data=f"intv_all_{owner_id}_45"),
                    InlineKeyboardButton(get_text(owner_id, "btn_60min"), callback_data=f"intv_all_{owner_id}_60"),
                ],
            ]
            await query.edit_message_text(
                get_text(owner_id, "ad_set_all").format(emoji="📸", count=available_count),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        user_waiting_setmsg[owner_id] = "all"
        if query.message:
            user_setmsg_prompt[owner_id] = (query.message.chat_id, query.message.message_id)
        keyboard = [[InlineKeyboardButton(get_text(owner_id, "btn_cancel2"), callback_data=f"setmsg_cancel_{owner_id}")]]
        await query.edit_message_text(
            get_text(owner_id, "send_ad_all").format(count=available_count),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
 
        # ─── intvc — Custom interval ───
    if cb.startswith("intvc_"):
        rest = cb[len("intvc_"):]
        if rest.startswith("all_"):
            owner_id = int(rest[len("all_"):])
            target = "all"
        else:
            first_us = rest.index("_")
            owner_id = int(rest[:first_us])
            target = int(rest[first_us + 1:])

        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_yours"), show_alert=True)
            return

        user_waiting_interval[owner_id] = {"gid": target, "ts": datetime.now().timestamp()}
        keyboard = [[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]
        await query.edit_message_text(
            get_text(owner_id, "custom_intv_prompt"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return       

    # ─── intv_all — All Group interval ───
    if cb.startswith("intv_all_"):
        parts = cb[len("intv_all_"):].split("_")
        owner_id = int(parts[0])
        minutes = int(parts[1])

        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_yours"), show_alert=True)
            return

        seconds = minutes * 60
        my_groups = get_user_groups(owner_id)

        # রাতের বিরতি চেক
        now_utc_hour = datetime.now(timezone.utc).hour
        is_night_break = (now_utc_hour >= 16) or (now_utc_hour < 4)

        started = 0
        no_admin_groups = []
        for gid in my_groups:
            # All-Group মোডে লক করা গ্রুপ চুপচাপ স্কিপ করো
            if gid in group_lock and group_lock[gid] != owner_id:
                continue

            gdata = get_group_data(owner_id, gid)
            has_content = (
                gdata.get("broadcast_msg") or
                gdata.get("broadcast_photo") or
                gdata.get("broadcast_video") or
                gdata.get("broadcast_media_group")
            )
            if not has_content:
                continue

            # বট admin কিনা চেক
            try:
                bot_member = await context.bot.get_chat_member(gid, context.bot.id)
                if bot_member.status != "administrator":
                    no_admin_groups.append(my_groups[gid])
                    continue
            except Exception:
                no_admin_groups.append(my_groups.get(gid, str(gid)))
                continue

            gdata["interval"] = seconds
            gdata["manual_stop"] = False
            if is_night_break:
                gdata["is_running"] = False
            else:
                gdata["is_running"] = True
                # NEW: Set group lock
                group_lock[gid] = owner_id
                old_jobs = context.application.job_queue.get_jobs_by_name(f"broadcast_{owner_id}_{gid}")
                for job in old_jobs:
                    job.schedule_removal()
                context.application.job_queue.run_repeating(
                    broadcast_job,
                    interval=seconds,
                    first=seconds,
                    name=f"broadcast_{owner_id}_{gid}",
                    data={"user_id": owner_id, "group_id": gid}
                )
                gdata["next_broadcast_time"] = datetime.now(timezone.utc).timestamp() + seconds
            started += 1

        if not is_night_break:
            for gid in my_groups:
                if gid in group_lock and group_lock[gid] != owner_id:
                    continue
                gdata = get_group_data(owner_id, gid)
                if gdata.get("is_running"):
                    await send_broadcast_to_group(context, owner_id, gid)

        if is_night_break:
            no_admin_text = ""
            if no_admin_groups:
                no_admin_text = get_text(owner_id, "no_admin_text").format(count=len(no_admin_groups)) + "\n".join(f"   └ {t}" for t in no_admin_groups)
            text = get_text(owner_id, "night_all_done").format(
                started=started,
                minutes=minutes,
                no_admin=no_admin_text + "\n" if no_admin_text else ""
            )
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
            )
        elif started == 0:
            no_admin_text = "\n".join(f"   └ {t}" for t in no_admin_groups)
            text = get_text(owner_id, "no_admin_fail").format(list=no_admin_text)
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
            )
        else:
            no_admin_text = ""
            if no_admin_groups:
                no_admin_text = get_text(owner_id, "no_admin_text2").format(count=len(no_admin_groups)) + "\n".join(f"   └ {t}" for t in no_admin_groups)
            text = get_text(owner_id, "broadcast_started_all").format(
                started=started,
                minutes=minutes,
                no_admin=no_admin_text
            )
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
            )
        return

    # ─── setmsg_sel — গ্রুপ সিলেক্ট হলে মেসেজ চাও ───
    if cb.startswith("setmsg_sel_"):
        rest = cb[len("setmsg_sel_"):]
        first_us = rest.index("_")
        owner_id = int(rest[:first_us])
        group_id = int(rest[first_us + 1:])

        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_yours"), show_alert=True)
            return

        my_groups = get_user_groups(owner_id)
        g_title = my_groups.get(group_id, str(group_id))

        # NEW: Check if group is locked by another admin BEFORE asking for ad content
        if not await _check_broadcast_lock_and_request(context, owner_id, group_id, g_title, query=query):
            return

        # pending content আছে কিনা চেক (ছবি সহ /setmsg)
        pending_type = context.user_data.get("pending_type")
        if pending_type == "photo":
            gdata = get_group_data(owner_id, group_id)
            gdata["broadcast_photo"] = context.user_data.pop("pending_photo", None)
            gdata["broadcast_msg"] = context.user_data.pop("pending_caption", "")
            gdata["broadcast_video"] = None
            gdata["broadcast_media_group"] = None
            context.user_data.pop("pending_type", None)
            keyboard = _interval_keyboard(owner_id, group_id)
            await query.edit_message_text(
                get_text(owner_id, "ad_set_one").format(emoji="📸", title=g_title),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # মেসেজ অপেক্ষায় রাখো
        user_waiting_setmsg[owner_id] = group_id
        if query.message:
            user_setmsg_prompt[owner_id] = (query.message.chat_id, query.message.message_id)
        keyboard = [[InlineKeyboardButton(get_text(owner_id, "btn_cancel2"), callback_data=f"setmsg_cancel_{owner_id}")]]
        await query.edit_message_text(
            get_text(owner_id, "send_ad_group").format(title=g_title),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

        # ─── intv — interval সিলেক্ট ───
    if cb.startswith("intv_") and not cb.startswith("intv_all_"):
        parts = cb[len("intv_"):].split("_")
        # format: intv_{owner_id}_{group_id}_{minutes}
        # group_id নেগেটিভ হতে পারে, তাই শেষের দুটো নাও
        minutes = int(parts[-1])
        owner_id = int(parts[0])
        group_id = int("_".join(parts[1:-1]))  # মাঝের সব = group_id

        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_yours"), show_alert=True)
            return

        seconds = minutes * 60
        gdata = get_group_data(owner_id, group_id)

        my_groups = get_user_groups(owner_id)
        g_title = my_groups.get(group_id, str(group_id))

        # NEW: Check broadcast lock again before starting
        if not await _check_broadcast_lock_and_request(context, owner_id, group_id, g_title, query=query):
            return

        gdata["interval"] = seconds
        gdata["manual_stop"] = False

        # রাতের বিরতি চেক (রাত ১১টা BD = UTC 17:00 থেকে সকাল ১০টা BD = UTC 04:00)
        now_utc_hour = datetime.now(timezone.utc).hour
        is_night_break = (now_utc_hour >= 16) or (now_utc_hour < 4)

        if is_night_break:
            gdata["is_running"] = False
            text = get_text(owner_id, "night_set_done").format(title=g_title, minutes=minutes)
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
            )
            return

        gdata["is_running"] = True

        # NEW: Set group lock
        group_lock[group_id] = owner_id

        # পুরনো job বন্ধ করো
        old_jobs = context.application.job_queue.get_jobs_by_name(f"broadcast_{owner_id}_{group_id}")
        for job in old_jobs:
            job.schedule_removal()

        # বট admin কিনা চেক
        try:
            bot_member = await context.bot.get_chat_member(group_id, context.bot.id)
            if bot_member.status != "administrator":
                gdata["is_running"] = False
                # NEW: Remove lock if broadcast failed
                group_lock.pop(group_id, None)
                text = get_text(owner_id, "not_admin").format(title=g_title)
                await query.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
                )
                return
        except Exception:
            gdata["is_running"] = False
            # NEW: Remove lock if broadcast failed
            group_lock.pop(group_id, None)
            text = get_text(owner_id, "group_check_fail").format(title=g_title)
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
            )
            return

        text = get_text(owner_id, "broadcast_started").format(title=g_title, minutes=minutes)
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
        )

        # প্রথম broadcast এখনই পাঠাও
        await send_broadcast_to_group(context, owner_id, group_id)
        gdata["next_broadcast_time"] = datetime.now(timezone.utc).timestamp() + seconds

        context.application.job_queue.run_repeating(
            broadcast_job,
            interval=seconds,
            first=seconds,
            name=f"broadcast_{owner_id}_{group_id}",
            data={"user_id": owner_id, "group_id": group_id}
        )
        return

    # ─── status_groups_ — গ্রুপ স্ট্যাটাস পেজ ───
    if cb.startswith("status_groups_"):
        owner_id = int(cb[len("status_groups_"):])
        if user_id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        await _show_group_status(query, owner_id)
        return

    # ─── status_schedule_ — শিডিউল পেজ ───
    if cb.startswith("status_schedule_"):
        owner_id = int(cb[len("status_schedule_"):])
        if user_id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        await _show_schedule_status(query, owner_id)
        return

    # ─── noop — কিছু করবে না ───
    if cb == "noop":
        await query.answer()
        return

    # ─── /status — গ্রুপের বিস্তারিত ───
    if cb.startswith("status_grp_"):
        rest = cb[len("status_grp_"):]
        first_us = rest.index("_")
        owner_id = int(rest[:first_us])
        group_id = int(rest[first_us + 1:])

        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_yours"), show_alert=True)
            return

        my_groups = get_user_groups(owner_id)
        g_title = my_groups.get(group_id, str(group_id))
        gdata = get_group_data(owner_id, group_id)

        interval = gdata.get("interval")
        next_time = gdata.get("next_broadcast_time")
        is_running = gdata.get("is_running", False)

        countdown_text = ""
        if is_running and next_time:
            remaining = next_time - datetime.now(timezone.utc).timestamp()
            if remaining > 0:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                if mins > 0:
                    countdown_text = get_text(owner_id, "status_countdown").format(mins=mins, secs=secs)
                else:
                    countdown_text = get_text(owner_id, "status_countdown_secs").format(secs=secs)
            else:
                countdown_text = get_text(owner_id, "status_countdown_soon")

        msg_preview = gdata.get("broadcast_msg") or get_text(owner_id, "status_not_set")
        if len(msg_preview) > 30:
            msg_preview = msg_preview[:30] + "..."

        content_type = _ad_content_label(owner_id, gdata)

        keyboard = [
            [InlineKeyboardButton(get_text(owner_id, "btn_refresh"), callback_data=f"status_grp_{owner_id}_{group_id}")],
            [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"status_groups_{owner_id}")],
        ]
        running_text = get_text(owner_id, "status_running") if is_running else get_text(owner_id, "status_stopped")
        interval_text = get_text(owner_id, "status_interval").format(mins=interval // 60) if interval else get_text(owner_id, "status_not_set")
        await query.edit_message_text(
            get_text(owner_id, "status_group").format(
                title=g_title, running=running_text,
                interval=interval_text, ctype=content_type,
                preview=msg_preview, countdown=countdown_text
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── status_back ───
    if cb.startswith("status_back_"):
        owner_id = int(cb[len("status_back_"):])
        if user_id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        await _show_status_menu(query, owner_id)
        return

    # ─── /stop — নির্দিষ্ট গ্রুপ বন্ধ ───
    if cb.startswith("stopgrp_"):
        rest = cb[len("stopgrp_"):]
        first_us = rest.index("_")
        owner_id = int(rest[:first_us])
        grp_selection = rest[first_us + 1:]

        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_yours"), show_alert=True)
            return

        my_groups = get_user_groups(owner_id)

        if grp_selection == "all":
            # সব গ্রুপ বন্ধ
            if owner_id in group_broadcast_data:
                for gid in list(group_broadcast_data[owner_id].keys()):
                    group_broadcast_data[owner_id][gid]["is_running"] = False
                    group_broadcast_data[owner_id][gid]["manual_stop"] = True
                    group_broadcast_data[owner_id][gid]["next_broadcast_time"] = None
                    jobs = context.application.job_queue.get_jobs_by_name(f"broadcast_{owner_id}_{gid}")
                    for job in jobs:
                        job.schedule_removal()
                    # NEW: Remove group lock
                    group_lock.pop(gid, None)
                    old_id = group_broadcast_data[owner_id][gid].get("last_msg_id")
                    if old_id:
                        id_list = old_id if isinstance(old_id, list) else [old_id]
                        for mid in id_list:
                            try:
                                await context.bot.delete_message(chat_id=gid, message_id=mid)
                            except Exception:
                                pass
                        group_broadcast_data[owner_id][gid]["last_msg_id"] = None
            keyboard = [[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]
            await query.edit_message_text(
                get_text(owner_id, "stop_all_confirm"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        gid = int(grp_selection)
        title = my_groups.get(gid, str(gid))
        gdata = get_group_data(owner_id, gid)
        gdata["is_running"] = False
        gdata["manual_stop"] = True
        gdata["next_broadcast_time"] = None
        jobs = context.application.job_queue.get_jobs_by_name(f"broadcast_{owner_id}_{gid}")
        for job in jobs:
            job.schedule_removal()
        # NEW: Remove group lock
        group_lock.pop(gid, None)
        old_id = gdata.get("last_msg_id")
        if old_id:
            id_list = old_id if isinstance(old_id, list) else [old_id]
            for mid in id_list:
                try:
                    await context.bot.delete_message(chat_id=gid, message_id=mid)
                except Exception:
                    pass
            gdata["last_msg_id"] = None

        # বাকি active গ্রুপ
        active = _get_active_groups(owner_id)
        if not active:
            keyboard = [[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]
            await query.edit_message_text(
                get_text(owner_id, "stop_one_done").format(title=title),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        keyboard = []
        for g_id, g_title in active.items():
            keyboard.append([
                InlineKeyboardButton(f"🛑 {g_title}", callback_data=f"stopgrp_{owner_id}_{g_id}")
            ])
        keyboard.append([
            InlineKeyboardButton(get_text(owner_id, "btn_stop_all"), callback_data=f"stopgrp_{owner_id}_all")
        ])
        keyboard.append([InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")])
        await query.edit_message_text(
            get_text(owner_id, "stop_one_more").format(title=title, count=len(active)),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── গ্রুপ বাদ দেওয়া ───
    if cb.startswith("delgroup_"):
        rest = cb[len("delgroup_"):]
        first_us = rest.index("_")
        owner_id = int(rest[:first_us])
        gid = int(rest[first_us + 1:])

        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_your_group"), show_alert=True)
            return

        my_groups = get_user_groups(owner_id)
        title = my_groups.pop(gid, str(gid))

        # এই গ্রুপের broadcast job বন্ধ করো
        jobs = context.application.job_queue.get_jobs_by_name(f"broadcast_{owner_id}_{gid}")
        for job in jobs:
            job.schedule_removal()
        if owner_id in group_broadcast_data and gid in group_broadcast_data[owner_id]:
            del group_broadcast_data[owner_id][gid]
        # NEW: Remove group lock
        group_lock.pop(gid, None)

        if not my_groups:
            await query.edit_message_text(
                get_text(owner_id, "group_removed_empty").format(title=title),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
            )
            return

        keyboard = []
        for g_id, g_title in my_groups.items():
            keyboard.append([
                InlineKeyboardButton(get_text(owner_id, "btn_remove").format(title=g_title), callback_data=f"delgroup_{owner_id}_{g_id}")
            ])
        keyboard.append([InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"groups_back_{owner_id}")])
        await query.edit_message_text(
            get_text(owner_id, "group_removed_more").format(title=title, count=len(my_groups)),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── groups_back — /start মেনুতে ফিরে যাও ───
    if cb.startswith("groups_back_"):
        owner_id = int(cb[len("groups_back_"):])
        if user_id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        await query.edit_message_text(
            get_start_text(owner_id),
            reply_markup=get_start_keyboard(owner_id)
        )
        return

    # ─── start_back — /start মেনুতে ফিরে যাও ───
    if cb.startswith("start_back_"):
        owner_id = int(cb[len("start_back_"):])
        if user_id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        await query.edit_message_text(
            get_start_text(owner_id),
            reply_markup=get_start_keyboard(owner_id)
        )
        return

    # ─── /offgp callbacks ───
    if cb.startswith("offgp_back_"):
        owner_id = int(cb.replace("offgp_back_", ""))
        if user_id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        my_groups = get_user_groups(owner_id)
        if not my_groups:
            await query.edit_message_text(
                get_text(owner_id, "no_group_schedule"),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")]]),
            )
            return
        keyboard = []
        for gid, title in my_groups.items():
            keyboard.append([InlineKeyboardButton(f"📛 {title}", callback_data=f"offgp_grp_{owner_id}_{gid}")])
        keyboard.append([InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")])
        await query.edit_message_text(
            get_text(owner_id, "select_group_schedule"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if cb.startswith("offgp_grp_"):
        parts = cb.replace("offgp_grp_", "").split("_")
        owner_id = int(parts[0])
        gid = int(parts[1])

        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_your_group"), show_alert=True)
            return

        my_groups = get_user_groups(owner_id)
        g_title = my_groups.get(gid, str(gid))

        # প্রথমে চেক করো: অন্য এডমিন শিডিউল সেট করেছে কিনা?
        other_admin_id, _ = _get_other_admin_with_schedule(gid, owner_id)
        
        if other_admin_id:
            # অন্য এডমিনের শিডিউল আছে → Request পাঠানোর অপশন দাও
            other_admin_name = await _get_user_name(other_admin_id, context)
            
            # চেক করো আগের রিকুয়েস্ট পেন্ডিং আছে কিনা
            existing_pending = False
            pending_timestamp = None
            for req_id, req in pending_requests.items():
                if req["from_user"] == owner_id and req["group_id"] == gid and req["status"] == "pending":
                    existing_pending = True
                    pending_timestamp = req.get("timestamp", 0)
                    break
            
            if existing_pending:
                now_ts = datetime.now(timezone.utc).timestamp()
                remaining = 300 - int(now_ts - pending_timestamp)
                if remaining > 0:
                    mins = remaining // 60
                    secs = remaining % 60
                    lang = user_lang.get(owner_id, "bn")
                    if lang == "en":
                        countdown = f"{mins} minutes {secs} seconds"
                    else:
                        countdown = f"{mins} মিনিট {secs} সেকেন্ড"
                else:
                    # মেয়াদ শেষ — request মুছে দাও, নতুন দিতে দাও
                    for req_id, req in list(pending_requests.items()):
                        if req["from_user"] == owner_id and req["group_id"] == gid:
                            del pending_requests[req_id]
                    existing_pending = False
                    
                if existing_pending:
                    await query.edit_message_text(
                        get_text(owner_id, "request_already_pending") + "\n\n" + get_text(owner_id, "request_expires_in").format(countdown=countdown),
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_back_{owner_id}")]])
                    )
                    return
            
            # Request বাটন সহ মেসেজ দেখাও (কোন লিমিট চেক নেই)
            keyboard = [
                [InlineKeyboardButton(get_text(owner_id, "btn_send_request"), callback_data=f"send_req_{owner_id}_{gid}_{other_admin_id}")],
                [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_back_{owner_id}")],
            ]
            await query.edit_message_text(
                f"{get_text(owner_id, 'schedule_other_admin')}\n\n"
                f"{get_text(owner_id, 'schedule_other_admin_by').format(name=other_admin_name, id=other_admin_id)}\n\n"
                f"{get_text(owner_id, 'schedule_request_hint')}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # অন্য এডমিনের শিডিউল নেই → আগের মতো শিডিউল সেট করার অপশন দেখাও
        existing = user_group_schedule.get(owner_id, {}).get(gid)
        if existing and existing.get("off_hour") is not None:
            off_h = existing["off_hour"]
            on_h = existing["on_hour"]
            off_label = format_schedule_time(owner_id, off_h, existing.get("off_min", 0))
            on_label = format_schedule_time(owner_id, on_h, existing.get("on_min", 0))
            keyboard = [
                [InlineKeyboardButton(get_text(owner_id, "btn_change_time"), callback_data=f"offgp_change_{owner_id}_{gid}")],
                [InlineKeyboardButton(get_text(owner_id, "btn_del_schedule"), callback_data=f"offgp_del_{owner_id}_{gid}")],
                [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_back_{owner_id}")],
            ]
            await query.edit_message_text(
                get_text(owner_id, "schedule_current").format(title=g_title, off=off_label, on=on_label),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            keyboard = _off_keyboard(owner_id, gid, f"offgp_back_{owner_id}")
            await query.edit_message_text(
                get_text(owner_id, "schedule_set_off").format(title=g_title),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return

    # ─── send_req_ callback (রিকুয়েস্ট পাঠানো) ───
    if cb.startswith("send_req_"):
        parts = cb[9:].split("_")  # "send_req_" এর পর {from_user}_{group_id}_{to_admin}
        from_user = int(parts[0])
        group_id = int(parts[1])
        to_admin = int(parts[2])
        
        if user_id != from_user:
            await query.answer(get_text(user_id, "not_yours"), show_alert=True)
            return
        
        my_groups = get_user_groups(from_user)
        group_title = my_groups.get(group_id, str(group_id))
        
        # রিকুয়েস্ট পাঠাও (কোন লিমিট চেক নেই)
        success = await _send_request_to_admin(context, from_user, to_admin, group_id, group_title)
        
        if success:
            await query.edit_message_text(
                get_text(from_user, "request_sent").format(name=await _get_user_name(to_admin, context)),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(from_user, "btn_back"), callback_data=f"offgp_back_{from_user}")]])
            )
        else:
            await query.edit_message_text(
                "❌ রিকুয়েস্ট পাঠাতে ব্যর্থ হয়েছে! এডমিন বটকে ব্লক করে থাকতে পারে।",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(from_user, "btn_back"), callback_data=f"offgp_back_{from_user}")]])
            )
        return

    if cb.startswith("offgp_change_"):
        parts = cb.replace("offgp_change_", "").split("_")
        owner_id = int(parts[0])
        gid = int(parts[1])
        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_your_group"), show_alert=True)
            return
        my_groups = get_user_groups(owner_id)
        g_title = my_groups.get(gid, str(gid))
        keyboard = _off_keyboard(owner_id, gid, f"offgp_grp_{owner_id}_{gid}")
        await query.edit_message_text(
            get_text(owner_id, "schedule_set_off").format(title=g_title),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if cb.startswith("offgp_del_"):
        parts = cb.replace("offgp_del_", "").split("_")
        owner_id = int(parts[0])
        gid = int(parts[1])
        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_your_group"), show_alert=True)
            return
        my_groups = get_user_groups(owner_id)
        g_title = my_groups.get(gid, str(gid))
        if owner_id in user_group_schedule and gid in user_group_schedule[owner_id]:
            del user_group_schedule[owner_id][gid]
        keyboard = [
            [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_back_{owner_id}")]
        ]
        await query.edit_message_text(
            get_text(owner_id, "schedule_del_done").format(title=g_title),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if cb.startswith("offgp_off_"):
        parts = cb.replace("offgp_off_", "").split("_")
        owner_id = int(parts[0])
        gid = int(parts[1])
        off_hour_bd = int(parts[2])
        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_your_group"), show_alert=True)
            return
        my_groups = get_user_groups(owner_id)
        g_title = my_groups.get(gid, str(gid))
        keyboard = _on_keyboard(owner_id, gid, off_hour_bd, 0)
        await query.edit_message_text(
            get_text(owner_id, "schedule_set_on").format(title=g_title, off=format_schedule_time(owner_id, off_hour_bd)),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
        
     # ─── Custom: বন্ধের সময় নিজে লিখবে ───
    if cb.startswith("offgp_coff_"):
        parts = cb.replace("offgp_coff_", "").split("_")
        owner_id = int(parts[0])
        gid = int(parts[1])
        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_your_group"), show_alert=True)
            return
        user_waiting_setmsg.pop(owner_id, None)
        user_waiting_schedule[owner_id] = {"gid": gid, "step": "off", "ts": datetime.now().timestamp()}
        await query.edit_message_text(
            get_text(owner_id, "custom_off_prompt"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_change_{owner_id}_{gid}")]])
        )
        return

    # ─── Custom: চালুর সময় নিজে লিখবে ───
    if cb.startswith("offgp_con_"):
        parts = cb.replace("offgp_con_", "").split("_")
        owner_id = int(parts[0])
        gid = int(parts[1])
        off_h = int(parts[2])
        off_m = int(parts[3]) if len(parts) > 3 else 0
        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_your_group"), show_alert=True)
            return
        user_waiting_setmsg.pop(owner_id, None)
        user_waiting_schedule[owner_id] = {"gid": gid, "step": "on", "off_h": off_h, "off_m": off_m, "ts": datetime.now().timestamp()}
        await query.edit_message_text(
            get_text(owner_id, "custom_on_prompt").format(off=format_schedule_time(owner_id, off_h, off_m)),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_change_{owner_id}_{gid}")]])
        )
        return   

    # ─── offgp_on — সকালের সময় সিলেক্ট ───
    if cb.startswith("offgp_on_"):
        parts = cb.replace("offgp_on_", "").split("_")
        owner_id = int(parts[0])
        gid = int(parts[1])
        off_hour_bd = int(parts[2])
        on_hour_bd = int(parts[3])
        off_min_bd = int(parts[4]) if len(parts) > 4 else 0
        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_your_group"), show_alert=True)
            return
        if owner_id not in user_group_schedule:
            user_group_schedule[owner_id] = {}
        user_group_schedule[owner_id][gid] = {
            "off_hour": off_hour_bd,
            "off_min": off_min_bd,
            "on_hour": on_hour_bd,
            "on_min": 0,
            "night_msg_id": None,
            "morning_msg_id": None,
        }
        my_groups = get_user_groups(owner_id)
        g_title = my_groups.get(gid, str(gid))
        off_label = format_schedule_time(owner_id, off_hour_bd, off_min_bd)
        on_label = format_schedule_time(owner_id, on_hour_bd, 0)
        keyboard = [
            [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_back_{owner_id}")]
        ]
        await query.edit_message_text(
            get_text(owner_id, "schedule_done").format(title=g_title, off=off_label, on=on_label),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── lang_ — ভাষা সিলেক্ট ───
    if cb.startswith("lang_bn_") or cb.startswith("lang_en_"):
        if cb.startswith("lang_bn_"):
            owner_id = int(cb[len("lang_bn_"):])
            lang = "bn"
        else:
            owner_id = int(cb[len("lang_en_"):])
            lang = "en"
        if query.from_user.id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        user_lang[owner_id] = lang
        await query.edit_message_text(
            get_start_text(owner_id),
            reply_markup=get_start_keyboard(owner_id)
        )
        return

    # ─── br_ — Owner broadcast ───
    if cb.startswith("br_"):
        await _handle_br_callback(query, context, cb)
        return


# ============================================
# Helper: active গ্রুপ পাও
# ============================================
def _get_active_groups(user_id):
    """যেসব গ্রুপে broadcast চালু আছে"""
    my_groups = get_user_groups(user_id)
    active = {}
    if user_id in group_broadcast_data:
        for gid, gdata in group_broadcast_data[user_id].items():
            if gdata.get("is_running") and gid in my_groups:
                active[gid] = my_groups[gid]
    return active


# ============================================
# /status — নতুন সিস্টেম: বাটন আকারে গ্রুপ
# ============================================
async def _show_status_menu(query_or_msg, owner_id, edit=True):
    """Status সাব-মেনু দেখাও"""
    text = get_text(owner_id, "status_menu")
    keyboard = [
        [InlineKeyboardButton(get_text(owner_id, "btn_group_status"), callback_data=f"status_groups_{owner_id}")],
        [InlineKeyboardButton(get_text(owner_id, "btn_schedule_status"), callback_data=f"status_schedule_{owner_id}")],
        [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"start_back_{owner_id}")],
    ]
    if edit:
        await query_or_msg.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query_or_msg.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_group_status(query, owner_id):
    """গ্রুপ স্ট্যাটাস পেজ"""
    my_groups = get_user_groups(owner_id)
    active = _get_active_groups(owner_id)
    now_bd = datetime.now(BD_TZ)

    if not active:
        text = get_text(owner_id, "status_no_active").format(count=len(my_groups), time=now_bd.strftime("%I:%M %p"))
        keyboard = [[InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"status_back_{owner_id}")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    keyboard = []
    for gid, title in active.items():
        keyboard.append([
            InlineKeyboardButton(f"👹 {title}", callback_data=f"status_grp_{owner_id}_{gid}")
        ])
    keyboard.append([InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"status_back_{owner_id}")])

    text = get_text(owner_id, "status_active").format(active=len(active), total=len(my_groups), time=now_bd.strftime("%I:%M %p"))
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_schedule_status(query, owner_id):
    """শিডিউল পেজ"""
    my_groups = get_user_groups(owner_id)
    now_bd = datetime.now(BD_TZ)
    schedules = user_group_schedule.get(owner_id, {})

    keyboard = []
    for gid, sdata in schedules.items():
        off_h = sdata.get("off_hour")
        on_h = sdata.get("on_hour")
        if off_h is None or on_h is None:
            continue
        off_m = sdata.get("off_min", 0)
        on_m = sdata.get("on_min", 0)
        title = my_groups.get(gid, str(gid))

        # কতক্ষণ পরে অন/অফ হবে হিসাব
        current_h = now_bd.hour
        current_m = now_bd.minute

        # off পর্যন্ত বাকি মিনিট
        off_total = off_h * 60 + off_m
        on_total = on_h * 60 + on_m
        now_total = current_h * 60 + current_m

        # রাত বন্ধ আছে কিনা চেক
        if off_total > on_total:
            is_off_time = now_total >= off_total or now_total < on_total
        else:
            is_off_time = on_total > now_total >= off_total

        if is_off_time:
            # চালু হবে কতক্ষণ পরে
            mins_left = (on_total - now_total) % (24 * 60)
            h = mins_left // 60
            m = mins_left % 60
            if h > 0:
                label = get_text(owner_id, "schedule_will_start").format(h=h, m=m)
            else:
                label = get_text(owner_id, "schedule_will_start_min").format(m=m)
        else:
            # বন্ধ হবে কতক্ষণ পরে
            mins_left = (off_total - now_total) % (24 * 60)
            h = mins_left // 60
            m = mins_left % 60
            if h > 0:
                label = get_text(owner_id, "schedule_will_stop").format(h=h, m=m)
            else:
                label = get_text(owner_id, "schedule_will_stop_min").format(m=m)

        keyboard.append([
            InlineKeyboardButton(f"⏰ {title} — {label}", callback_data="noop")
        ])

    keyboard.append([
        InlineKeyboardButton(get_text(owner_id, "btn_refresh"), callback_data=f"status_schedule_{owner_id}"),
        InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"status_back_{owner_id}"),
    ])

    if len(keyboard) <= 1:  # only refresh and back buttons
        text = get_text(owner_id, "schedule_none").format(time=now_bd.strftime("%I:%M %p"))
    else:
        text = get_text(owner_id, "schedule_list").format(time=now_bd.strftime("%I:%M %p"))
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    user_id = update.effective_user.id
    await _show_status_menu(update.message, user_id, edit=False)


# ============================================
# /offgp
# ============================================
async def offgp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    user_id = update.effective_user.id
    my_groups = get_user_groups(user_id)

    if not my_groups:
        await update.message.reply_text(
            get_text(user_id, "no_group_yet")
        )
        return

    keyboard = []
    for gid, title in my_groups.items():
        keyboard.append([InlineKeyboardButton(f"📛 {title}", callback_data=f"offgp_grp_{user_id}_{gid}")])
    keyboard.append([InlineKeyboardButton(get_text(user_id, "btn_back"), callback_data=f"start_back_{user_id}")])

    await update.message.reply_text(
        get_text(user_id, "select_schedule_group"),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================
# গ্রুপ অটো অফ
# ============================================
async def do_group_night_off(bot, group_id: int, on_hour_bd: int, user_id: int, on_min: int = 0):
    try:
        # বট admin কিনা চেক
        bot_member = await bot.get_chat_member(group_id, bot.id)
        if bot_member.status != "administrator":
            my_groups = get_user_groups(user_id)
            g_title = my_groups.get(group_id, str(group_id))
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=get_text(user_id, "bot_not_admin_schedule").format(title=g_title)
                )
            except Exception:
                pass
            return

        on_label = _html.escape(format_schedule_time(user_id, on_hour_bd, on_min))
        on_emoji = _PERIOD_EMOJI[_day_period(on_hour_bd)]

        # সকালের মেসেজ ডিলিট
        morning_msg_id = user_group_schedule.get(user_id, {}).get(group_id, {}).get("morning_msg_id")
        if morning_msg_id:
            try:
                await bot.delete_message(chat_id=group_id, message_id=morning_msg_id)
            except Exception:
                pass
            user_group_schedule[user_id][group_id]["morning_msg_id"] = None

        # বন্ধের সময় অনুযায়ী মেসেজ
        period = _day_period(datetime.now(BD_TZ).hour)
        notice = (
            "⚠️ <b>বিশেষ দ্রষ্টব্য:</b>\n"
            "এখন কোনো এডমিন লাইনে থাকবে না!!\n"
            "তাই গ্রুপটি অফ 🔴\n"
            f"আবার {on_label} খোলা হবে। {on_emoji}"
        )
        if period == "night":
            text = (
                "🌙✨ <b>𝐆𝐨𝐨𝐝 𝐍𝐢𝐠𝐡𝐭</b> ✨🌙\n\n"
                "😴 <b>সবাইকে শুভরাত্রি!</b>\n\n"
                "🤲 <b>ঘুমানোর আগে দোয়া:</b>\n"
                "اللَّهُمَّ بِاسْمِكَ أَمُوتُ وَأَحْيَا\n\n"
                "📖 <b>বাংলা উচ্চারণ:</b>\n"
                "আল্লাহুম্মা বিসমিকা আমুতু ওয়া আহইয়া\n\n"
                "💫 <b>অর্থ:</b> হে আল্লাহ! আমি তোমারই নামে মৃত্যুবরণ করি, "
                "আবার তোমারই নামে জীবন ধারণ করি।\n\n"
                f"{notice}\n\n"
                "🌟 আল্লাহ সবার রাত শান্তিময় করুন। 🌷"
            )
        elif period == "morning":
            text = f"☀️✨ <b>সকালের বিরতি</b> ✨☀️\n\n⏸ <b>গ্রুপটি কিছুক্ষণের জন্য বন্ধ</b> 🔴\n\n{notice}"
        elif period == "noon":
            text = f"🌞✨ <b>দুপুরের বিরতি</b> ✨🌞\n\n⏸ <b>গ্রুপটি কিছুক্ষণের জন্য বন্ধ</b> 🔴\n\n{notice}"
        else:
            text = f"🌇✨ <b>বিকালের বিরতি</b> ✨🌇\n\n⏸ <b>গ্রুপটি কিছুক্ষণের জন্য বন্ধ</b> 🔴\n\n{notice}"

        sent = await bot.send_message(
            chat_id=group_id,
            parse_mode="HTML",
            text=text
        )
        if user_id not in user_group_schedule:
            user_group_schedule[user_id] = {}
        if group_id not in user_group_schedule[user_id]:
            user_group_schedule[user_id][group_id] = {}
        user_group_schedule[user_id][group_id]["night_msg_id"] = sent.message_id

        await bot.set_chat_permissions(
            chat_id=group_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_photos=False,
            )
        )
    except Exception as e:
        logging.error(f"Night off error group {group_id}: {e}")


async def do_group_morning_on(bot, group_id: int, user_id: int):
    try:
        # বট admin কিনা চেক
        bot_member = await bot.get_chat_member(group_id, bot.id)
        if bot_member.status != "administrator":
            my_groups = get_user_groups(user_id)
            g_title = my_groups.get(group_id, str(group_id))
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=get_text(user_id, "bot_not_admin_unlock").format(title=g_title)
                )
            except Exception:
                pass
            return

        night_msg_id = None
        if user_id in user_group_schedule and group_id in user_group_schedule[user_id]:
            night_msg_id = user_group_schedule[user_id][group_id].get("night_msg_id")

        if night_msg_id:
            try:
                await bot.delete_message(chat_id=group_id, message_id=night_msg_id)
                user_group_schedule[user_id][group_id]["night_msg_id"] = None
            except Exception:
                pass

        await bot.set_chat_permissions(
            chat_id=group_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_photos=True,
            )
        )

        now_bd = datetime.now(BD_TZ)
        day_name = BN_DAYS[now_bd.weekday()]
        date_str = now_bd.strftime("%d/%m/%Y").translate(BN_DIGITS)
        period = _day_period(now_bd.hour)

        opened = f"🎉 <b>আমাদের গ্রুপটি খোলা হয়েছে!</b>\n📅 {day_name}, {date_str}\n\n"
        if period == "morning":
            text = (
                "🌅✨ <b>𝐆𝐨𝐨𝐝 𝐌𝐨𝐫𝐧𝐢𝐧𝐠</b> ✨🌅\n\n"
                + opened +
                "🤲 <b>ঘুম থেকে উঠার দোয়া:</b>\n"
                "الْحَمْدُ لِلَّهِ الَّذِي أَحْيَانَا بَعْدَ مَا أَمَاتَنَا وَإِلَيْهِ النُّشُورُ\n\n"
                "💫 <b>অর্থ:</b> সমস্ত প্রশংসা আল্লাহর, যিনি মৃত্যুর (ঘুমের) পর "
                "আমাদের জীবিত করেছেন, আর তাঁরই কাছে ফিরে যেতে হবে।\n\n"
                "✨ সবার দিনটা সুন্দর ও বরকতময় হোক। 🌷"
            )
        elif period == "noon":
            text = "🌞✨ <b>𝐆𝐨𝐨𝐝 𝐍𝐨𝐨𝐧</b> ✨🌞\n\n" + opened + "✨ সবার দুপুরটা সুন্দর কাটুক। 🌷"
        elif period == "evening":
            text = "🌇✨ <b>𝐆𝐨𝐨𝐝 𝐄𝐯𝐞𝐧𝐢𝐧𝐠</b> ✨🌇\n\n" + opened + "✨ সবার সন্ধ্যাটা সুন্দর কাটুক। 🌷"
        else:
            text = "🌙✨ <b>গ্রুপ আবার চালু</b> ✨🌙\n\n" + opened + "✨ সবার রাতটা সুন্দর কাটুক। 🌷"

        sent = await bot.send_message(
            chat_id=group_id,
            parse_mode="HTML",
            text=text
        )

        # সকালের মেসেজের ID সেভ (বন্ধের সময় ডিলিট করার জন্য)
        if user_id not in user_group_schedule:
            user_group_schedule[user_id] = {}
        if group_id not in user_group_schedule[user_id]:
            user_group_schedule[user_id][group_id] = {}
        user_group_schedule[user_id][group_id]["morning_msg_id"] = sent.message_id
    except Exception as e:
        logging.error(f"Morning on error group {group_id}: {e}")


# ============================================
# শিডিউল চেকার
# ============================================
async def schedule_checker(context: ContextTypes.DEFAULT_TYPE):
    now_bd = datetime.now(BD_TZ)
    current_hour = now_bd.hour
    current_minute = now_bd.minute
    minute_key = now_bd.strftime("%Y%m%d%H%M")

    tasks = []
    for user_id, schedules in list(user_group_schedule.items()):
        for group_id, sdata in list(schedules.items()):
            off_h = sdata.get("off_hour")
            on_h = sdata.get("on_hour")
            if off_h is None or on_h is None:
                continue
            off_m = sdata.get("off_min", 0)
            on_m = sdata.get("on_min", 0)
            if current_hour == off_h and current_minute == off_m:
                if sdata.get("last_off_key") == minute_key:
                    continue
                sdata["last_off_key"] = minute_key
                tasks.append(do_group_night_off(context.bot, group_id, on_h, user_id, on_m))
            elif current_hour == on_h and current_minute == on_m:
                if sdata.get("last_on_key") == minute_key:
                    continue
                sdata["last_on_key"] = minute_key
                tasks.append(do_group_morning_on(context.bot, group_id, user_id))

    if tasks:
        await asyncio.gather(*tasks)


# ============================================
# broadcast_job — per-group
# ============================================
async def broadcast_job(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    group_id = job_data["group_id"]
    gdata = get_group_data(user_id, group_id)

    if not gdata["is_running"]:
        jobs = context.application.job_queue.get_jobs_by_name(f"broadcast_{user_id}_{group_id}")
        for job in jobs:
            job.schedule_removal()
        # NEW: Remove lock if job stopped
        group_lock.pop(group_id, None)
        return

    await send_broadcast_to_group(context, user_id, group_id)
    interval = gdata.get("interval") or 900
    gdata["next_broadcast_time"] = datetime.now(timezone.utc).timestamp() + interval

# ============================================
# _send_one_item — একটা ফাইল পাঠায়
# ============================================
async def _send_one_item(bot, chat_id, item, caption_html):
    """একটা ফাইল পাঠায়। স্টিকার/ভিডিও মেসেজে লেখা জোড়া যায় না, তাই লেখা আলাদা মেসেজে যায়।
    পাঠানো মেসেজের id এর তালিকা ফেরত দেয়"""
    t, f = item["type"], item["file_id"]
    cap = caption_html or None
    ids = []
    if t == "sticker":
        sent = await bot.send_sticker(chat_id=chat_id, sticker=f)
    elif t == "video_note":
        sent = await bot.send_video_note(chat_id=chat_id, video_note=f)
    elif t == "voice":
        sent = await bot.send_voice(chat_id=chat_id, voice=f, caption=cap, parse_mode="HTML")
    elif t == "audio":
        sent = await bot.send_audio(chat_id=chat_id, audio=f, caption=cap, parse_mode="HTML")
    elif t == "animation":
        sent = await bot.send_animation(chat_id=chat_id, animation=f, caption=cap, parse_mode="HTML")
    elif t == "photo":
        sent = await bot.send_photo(chat_id=chat_id, photo=f, caption=cap, parse_mode="HTML")
    elif t == "video":
        sent = await bot.send_video(chat_id=chat_id, video=f, caption=cap, parse_mode="HTML")
    else:
        sent = await bot.send_document(chat_id=chat_id, document=f, caption=cap, parse_mode="HTML")
    ids.append(sent.message_id)
    if t in _NO_CAPTION_TYPES and (caption_html or "").strip():
        extra = await bot.send_message(chat_id=chat_id, text=caption_html.strip(), parse_mode="HTML", disable_web_page_preview=True)
        ids.append(extra.message_id)
    return ids


# ============================================
# send_broadcast_to_group — একটি গ্রুপে পাঠাও
# ============================================
async def send_broadcast_to_group(context: ContextTypes.DEFAULT_TYPE, user_id: int, group_id: int):
    from telegram import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio
    gdata = get_group_data(user_id, group_id)
    msg = gdata.get("broadcast_msg") or ""
    photo = gdata.get("broadcast_photo")
    video = gdata.get("broadcast_video")
    media_group = gdata.get("broadcast_media_group")

    if not msg and not photo and not video and not media_group:
        return

    # বট admin কিনা চেক
    try:
        bot_member = await context.bot.get_chat_member(group_id, context.bot.id)
        if bot_member.status != "administrator":
            gdata["is_running"] = False
            gdata["next_broadcast_time"] = None
            # NEW: Remove lock if bot not admin
            group_lock.pop(group_id, None)
            logging.warning(f"Broadcast stopped: bot not admin in group {group_id}")
            try:
                my_groups = get_user_groups(user_id)
                g_title = my_groups.get(group_id, str(group_id))
                await context.bot.send_message(
                    chat_id=user_id,
                    text=get_text(user_id, "bot_not_admin_broadcast").format(title=g_title)
                )
            except Exception as notify_err:
                err_str = str(notify_err).lower()
                if "forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str:
                    await _handle_user_blocked(context, user_id)
            return
    except Exception as e:
        logging.error(f"Admin check error group {group_id}: {e}")
        return

    try:
        # পুরনো মেসেজ ডিলিট
        old_id = gdata.get("last_msg_id")
        if old_id:
            id_list = old_id if isinstance(old_id, list) else [old_id]
            for mid in id_list:
                try:
                    await context.bot.delete_message(chat_id=group_id, message_id=mid)
                except Exception:
                    pass

        # /gp এর লেখা (একবারের জন্য)
        final_msg = _html.escape(msg)
        use_footer = bool(GP_TEXT) and (user_id, group_id) in GP_PENDING
        if use_footer:
            if GP_LINK:
                final_msg += f'\n\n<a href="{_html.escape(GP_LINK, quote=True)}">{_html.escape(GP_TEXT)}</a>'
            else:
                final_msg += f'\n\n{_html.escape(GP_TEXT)}'

        # Album বা ভয়েস/স্টিকার/ফাইল ইত্যাদি
        if media_group:
            if len(media_group) > 1:
                _cls = {"photo": InputMediaPhoto, "video": InputMediaVideo, "audio": InputMediaAudio}
                media_list = []
                for i, item in enumerate(media_group):
                    caption_text = final_msg if (i == 0 and final_msg) else None
                    cls = _cls.get(item["type"], InputMediaDocument)
                    media_list.append(cls(media=item["file_id"], caption=caption_text, parse_mode="HTML"))
                sent_list = await context.bot.send_media_group(chat_id=group_id, media=media_list)
                gdata["last_msg_id"] = [s.message_id for s in sent_list]
            else:
                gdata["last_msg_id"] = await _send_one_item(context.bot, group_id, media_group[0], final_msg)

        # Single Photo
        elif photo:
            sent = await context.bot.send_photo(chat_id=group_id, photo=photo, caption=final_msg or None, parse_mode="HTML")
            gdata["last_msg_id"] = sent.message_id

        # Single Video
        elif video:
            sent = await context.bot.send_video(chat_id=group_id, video=video, caption=final_msg or None, parse_mode="HTML")
            gdata["last_msg_id"] = sent.message_id

        # Text
        else:
            sent = await context.bot.send_message(chat_id=group_id, text=final_msg, parse_mode="HTML", disable_web_page_preview=True)
            gdata["last_msg_id"] = sent.message_id

        # লিংক একবার গেছে, এখন pending থেকে বাদ
        if use_footer:
            GP_PENDING.discard((user_id, group_id))

    except Exception as e:
        logging.error(f"Group {group_id} broadcast error: {e}")


# ============================================
# /stop
# ============================================
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    user_id = update.effective_user.id
    active = _get_active_groups(user_id)

    if not active:
        await update.message.reply_text(
            get_text(user_id, "no_broadcast2")
        )
        return

    keyboard = []
    for gid, title in active.items():
        keyboard.append([
            InlineKeyboardButton(f"🛑 {title}", callback_data=f"stopgrp_{user_id}_{gid}")
        ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, "btn_stop_all2"), callback_data=f"stopgrp_{user_id}_all")
    ])
    keyboard.append([InlineKeyboardButton(get_text(user_id, "btn_back"), callback_data=f"start_back_{user_id}")])

    await update.message.reply_text(
        get_text(user_id, "stop_header2").format(count=len(active)),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================
# /help
# ============================================
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [[InlineKeyboardButton(get_text(user_id, "btn_back"), callback_data=f"start_back_{user_id}")]]
    await update.message.reply_text(
        get_text(user_id, "help_text"),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================
# অটো broadcast বন্ধ — রাত ১১:০০ BD (UTC 17:00)
# ============================================
async def auto_broadcast_off(context: ContextTypes.DEFAULT_TYPE):
    notified = set()
    if group_broadcast_data:
        for user_id, user_groups in list(group_broadcast_data.items()):
            stopped = False
            for gid, gdata in list(user_groups.items()):
                if gdata.get("is_running"):
                    gdata["is_running"] = False
                    gdata["slot_anchor"] = gdata.get("next_broadcast_time")   # ছন্দের স্লট মনে রাখো
                    gdata["next_broadcast_time"] = None
                    jobs = context.application.job_queue.get_jobs_by_name(f"broadcast_{user_id}_{gid}")
                    for job in jobs:
                        job.schedule_removal()
                    # NEW: Remove lock
                    group_lock.pop(gid, None)
                    # লাস্ট broadcast মেসেজ delete করো
                    old_id = gdata.get("last_msg_id")
                    if old_id:
                        id_list = old_id if isinstance(old_id, list) else [old_id]
                        for mid in id_list:
                            try:
                                await context.bot.delete_message(chat_id=gid, message_id=mid)
                            except Exception:
                                pass
                        gdata["last_msg_id"] = None
                    stopped = True
            if stopped and user_id not in notified and user_id not in NOTIFY_OFF:
                notified.add(user_id)
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=get_text(user_id, "auto_off")
                    )
                except Exception as e:
                    err_str = str(e).lower()
                    if "forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str:
                        await _handle_user_blocked(context, user_id)
                    else:
                        logging.error(f"auto_broadcast_off notify error {user_id}: {e}")
    logging.info("🌙 রাত ১০:০০ — সবার broadcast অটো বন্ধ হয়েছে।")


# ============================================
# অটো broadcast চালু — সকাল ১০:০০ BD (UTC 04:00)
# ============================================
async def auto_broadcast_on(context: ContextTypes.DEFAULT_TYPE):
    ref_ts = datetime.now(timezone.utc).timestamp() - 30   # ১০:০০-এর স্লটও ধরার জন্য একটু পিছন থেকে
    if group_broadcast_data:
        for user_id, user_groups in list(group_broadcast_data.items()):
            restarted = False
            for gid, gdata in list(user_groups.items()):
                has_content = (
                    gdata.get("broadcast_msg") or
                    gdata.get("broadcast_photo") or
                    gdata.get("broadcast_video") or
                    gdata.get("broadcast_media_group")
                )
                if not gdata.get("is_running") and has_content and gdata.get("interval") and not gdata.get("manual_stop"):
                    # গ্রুপ এখনো সেটে আছে কিনা চেক
                    my_groups = get_user_groups(user_id)
                    if gid not in my_groups:
                        continue
                    # বট admin কিনা চেক
                    try:
                        bot_member = await context.bot.get_chat_member(gid, context.bot.id)
                        if bot_member.status != "administrator":
                            g_title = my_groups.get(gid, str(gid))
                            try:
                                await context.bot.send_message(
                                    chat_id=user_id,
                                    text=get_text(user_id, "bot_not_admin_morning").format(title=g_title)
                                )
                            except Exception as ne:
                                err_str = str(ne).lower()
                                if "forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str:
                                    await _handle_user_blocked(context, user_id)
                            continue
                    except Exception:
                        continue
                    gdata["is_running"] = True
                    # NEW: Set group lock
                    group_lock[gid] = user_id
                    interval = gdata["interval"]
                    now_ts = datetime.now(timezone.utc).timestamp()
                    anchor = gdata.get("slot_anchor")
                    if interval <= 2100:
                        # ১৫–৩৫ মিনিট: নিজের ছন্দের যে স্লট ১০:০০ বা তার পরে পড়ে সেখান থেকে চলবে
                        first = interval
                        if anchor:
                            slot = anchor
                            if slot < ref_ts:
                                slot += int(-((slot - ref_ts) // interval)) * interval
                            first = max(slot - now_ts, 1)
                    else:
                        # ৩৫ মিনিটের বেশি: ১০টায় চালু হয়ে সাথে সাথেই প্রথম মেসেজ
                        first = 1
                    gdata["slot_anchor"] = None
                    gdata["next_broadcast_time"] = now_ts + first
                    context.application.job_queue.run_repeating(
                        broadcast_job,
                        interval=interval,
                        first=first,
                        name=f"broadcast_{user_id}_{gid}",
                        data={"user_id": user_id, "group_id": gid}
                    )
                    restarted = True

            if restarted and user_id not in NOTIFY_OFF:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=get_text(user_id, "auto_on")
                    )
                except Exception as e:
                    err_str = str(e).lower()
                    if "forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str:
                        await _handle_user_blocked(context, user_id)
                    else:
                        logging.error(f"auto_broadcast_on notify error {user_id}: {e}")
    logging.info("🌅 সকাল ১০:০০ — সবার broadcast অটো চালু হয়েছে।")


# ============================================
# বট গ্রুপে অ্যাড/রিমুভ হলে — একটাই handler
# ============================================
async def handle_bot_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    my_chat_member = update.my_chat_member
    if not my_chat_member:
        return

    # ইউজার বটকে ব্লক করলে সাথে সাথে তার ডাটা মুছে দাও
    if my_chat_member.chat.type == "private":
        if my_chat_member.new_chat_member.status in ["kicked", "left"]:
            await _handle_user_blocked(context, my_chat_member.chat.id)
        return

    if my_chat_member.chat.type not in ["group", "supergroup"]:
        return

    old_status = my_chat_member.old_chat_member.status
    new_status = my_chat_member.new_chat_member.status

    # ─── বট এডমিন হলে → চ্যানেলে লিংক পাঠাও ───
    if new_status == "administrator" and old_status != "administrator":
        await log_group_link(context, my_chat_member.chat)

    # ─── বট ADD হলে (যে গ্রুপ আগেই যোগ করা আছে সেখানে আবার হ্যালো নয়) ───
    _gid_known = any(my_chat_member.chat.id in _g for _g in user_target_groups.values())
    if old_status == "left" and new_status in ["member", "administrator"] and not _gid_known:
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
        keyboard = [
    [
        InlineKeyboardButton("🌷 Support", url="https://t.me/teemcs"),
        InlineKeyboardButton("📩 Open Inbox", url=f"https://t.me/{bot_username}?start=hello"),
    ],
]
        try:
            await context.bot.send_message(
                chat_id=my_chat_member.chat.id,
                text=get_text(OWNER_ID, "bot_join_msg"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logging.error(f"bot add message error: {e}")

    # ─── বট REMOVE হলে ───
    elif new_status in ["left", "kicked", "banned"]:
        group_id = my_chat_member.chat.id
        group_title = my_chat_member.chat.title or str(group_id)

        # NEW: Clear group lock
        group_lock.pop(group_id, None)
        
        # NEW: Clear broadcast requests for this group
        for req_id, req in list(broadcast_requests.items()):
            if req.get("group_id") == group_id:
                del broadcast_requests[req_id]

        affected_users = [
            uid for uid, groups in list(user_target_groups.items())
            if group_id in groups
        ]
        if not affected_users:
            return

        for uid in affected_users:
            if uid in user_target_groups and group_id in user_target_groups[uid]:
                del user_target_groups[uid][group_id]

            jobs = context.application.job_queue.get_jobs_by_name(f"broadcast_{uid}_{group_id}")
            for job in jobs:
                job.schedule_removal()

            if uid in group_broadcast_data and group_id in group_broadcast_data[uid]:
                del group_broadcast_data[uid][group_id]

            if uid in user_group_schedule and group_id in user_group_schedule[uid]:
                del user_group_schedule[uid][group_id]

            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=get_text(uid, "bot_removed").format(title=group_title, gid=group_id)
                )
            except Exception as e:
                logging.error(f"bot remove notify error uid={uid}: {e}")

        logging.info(f"🗑 বট {group_title} ({group_id}) থেকে সরানো হয়েছে।")

    # ─── বট REMOVE হলে ───
    elif new_status in ["left", "kicked", "banned"]:
        group_id = my_chat_member.chat.id
        group_title = my_chat_member.chat.title or str(group_id)

        # NEW: Clear group lock
        group_lock.pop(group_id, None)
        
        # NEW: Clear broadcast requests for this group
        for req_id, req in list(broadcast_requests.items()):
            if req.get("group_id") == group_id:
                del broadcast_requests[req_id]

        affected_users = [
            uid for uid, groups in list(user_target_groups.items())
            if group_id in groups
        ]
        if not affected_users:
            return

        for uid in affected_users:
            if uid in user_target_groups and group_id in user_target_groups[uid]:
                del user_target_groups[uid][group_id]

            jobs = context.application.job_queue.get_jobs_by_name(f"broadcast_{uid}_{group_id}")
            for job in jobs:
                job.schedule_removal()

            if uid in group_broadcast_data and group_id in group_broadcast_data[uid]:
                del group_broadcast_data[uid][group_id]

            if uid in user_group_schedule and group_id in user_group_schedule[uid]:
                del user_group_schedule[uid][group_id]

            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=get_text(uid, "bot_removed").format(title=group_title, gid=group_id)
                )
            except Exception as e:
                logging.error(f"bot remove notify error uid={uid}: {e}")

        logging.info(f"🗑 বট {group_title} ({group_id}) থেকে সরানো হয়েছে।")


# ============================================
# /br — Owner এর লুকানো broadcast কমান্ড
# ============================================
br_pending = {}  # {owner_id: message_text}

async def br_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return  # লুকানো — অন্য কেউ জানবেও না

    if not context.args:
        await update.message.reply_text("⚠️ ব্যবহার: /br আপনার মেসেজ")
        return

    msg_text = " ".join(context.args)

    # সব user গোনো — যারা /start দিয়েছে
    total = len(all_bot_users)

    br_pending[OWNER_ID] = msg_text

    bn_count = sum(1 for u in all_bot_users if user_lang.get(u, "bn") == "bn")
    en_count = total - bn_count
    keyboard = [
        [InlineKeyboardButton(f"✅ সবাইকে ({total})", callback_data=f"br_send_{OWNER_ID}")],
        [
            InlineKeyboardButton(f"🇧🇩 বাংলা ({bn_count})", callback_data=f"br_bn_{OWNER_ID}"),
            InlineKeyboardButton(f"🇬🇧 English ({en_count})", callback_data=f"br_en_{OWNER_ID}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"br_cancel_{OWNER_ID}")],
    ]
    await update.message.reply_text(
        f"📢 ব্রডকাস্ট প্রিভিউ\n\n"
        f"{msg_text}\n\n"
        f"👥 মোট প্রাপক: {total} জন\n"
        f"🇧🇩 বাংলা: {bn_count} জন\n"
        f"🇬🇧 English: {en_count} জন\n\n"
        f"কাদের পাঠাবেন?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def off_notify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in NOTIFY_OFF:
        await update.message.reply_text(
            "🔕 Notifications are already turned off.\n✅ To turn on, send /on" if user_lang.get(uid, "bn") == "en" else "🔕 নোটিফিকেশন আগে থেকেই বন্ধ আছে।\n✅ চালু করতে /on দিন"
        )
    else:
        NOTIFY_OFF.add(uid)
        await update.message.reply_text(
            "🔕 Auto notifications turned off.\n✅ To turn on again, send /on" if user_lang.get(uid, "bn") == "en" else "🔕 অটো নোটিফিকেশন বন্ধ হয়েছে।\n✅ আবার চালু করতে /on দিন"
        )


async def on_notify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in NOTIFY_OFF:
        NOTIFY_OFF.discard(uid)
        await update.message.reply_text(
            "🔔 Auto notifications turned on." if user_lang.get(uid, "bn") == "en" else "🔔 অটো নোটিফিকেশন চালু হয়েছে।"
        )
    else:
        await update.message.reply_text(
            "🔔 Notifications are already turned on.\n✅ To turn off, send /off" if user_lang.get(uid, "bn") == "en" else "🔔 নোটিফিকেশন আগে থেকেই চালু আছে।\n✅ বন্ধ করতে /off দিন"
        )


async def gp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GP_TEXT, GP_LINK
    if update.effective_user.id != OWNER_ID:
        return

    parts = update.message.text.split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text("⚠️ ব্যবহার: /gp আপনার মেসেজ [লিংক]")
        return

    body = parts[1].strip()

    # লেখা (লিংক বাদে) অনেক লম্বা হলে সেট হবে না
    _b = body
    _w = _b.rsplit(None, 1)
    if len(_w) == 2 and (_w[1].startswith("http") or _w[1].startswith("t.me/")):
        _b = _w[0].strip()
    if _tg_len(_b) > GP_TEXT_LIMIT:
        await update.message.reply_text(
            f"⚠️ /gp এর লেখা অনেক লম্বা!\n\n📏 এখন: {_tg_len(_b)} অক্ষর\n✅ সর্বোচ্চ: {GP_TEXT_LIMIT} অক্ষর"
        )
        return

    GP_LINK = None

    words = body.rsplit(None, 1)
    if len(words) == 2 and (words[1].startswith("http") or words[1].startswith("t.me/")):
        GP_LINK = words[1] if words[1].startswith("http") else "https://" + words[1]
        body = words[0].strip()

    GP_TEXT = body

    GP_PENDING.clear()
    for uid, groups in group_broadcast_data.items():
        for gid, gd in groups.items():
            if gd.get("is_running"):
                GP_PENDING.add((uid, gid))

    await update.message.reply_text(
        f"✅ সেট হয়েছে\n"
        f"🔗 লিংক: {'আছে' if GP_LINK else 'নেই'}\n"
        f"📡 {len(GP_PENDING)} টি গ্রুপের পরের মেসেজে যাবে"
    )


async def _do_broadcast(context, owner_id: int, msg_text: str, target):
    """পেছনে (background) এক এক করে সবার কাছে পাঠায়, শেষে রিপোর্ট দেয়"""
    users = [u for u in list(all_bot_users) if target is None or user_lang.get(u, "bn") == target]
    success = 0
    failed = []

    for uid in users:
        for attempt in range(2):
            try:
                await context.bot.send_message(chat_id=uid, text=msg_text)
                success += 1
                break
            except Exception as e:
                err_str = str(e).lower()
                # টেলিগ্রাম থামতে বললে অপেক্ষা করে আবার একবার চেষ্টা
                if attempt == 0 and ("retry" in err_str or "flood" in err_str or "too many" in err_str):
                    m = re.search(r"(\d+)", err_str)
                    await asyncio.sleep(int(m.group(1)) + 1 if m else 3)
                    continue
                if "forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str:
                    await _handle_user_blocked(context, uid)
                failed.append(uid)
                break

    report = (
        f"📊 ব্রডকাস্ট রিপোর্ট\n\n"
        f"✅ সফল: {success} জন\n"
        f"❌ ব্যর্থ: {len(failed)} জন"
    )
    if failed:
        report += "\n\n❌ যায়নি:\n"
        for uid in failed:
            report += f"• {uid}\n"

    try:
        await context.bot.send_message(chat_id=owner_id, text=report)
    except Exception as e:
        logging.error(f"broadcast report error: {e}")


async def _handle_br_callback(query, context, cb):
    """br_ callback গুলো handle করো"""
    if cb.startswith("br_cancel_"):
        owner_id = int(cb[len("br_cancel_"):])
        if query.from_user.id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        br_pending.pop(owner_id, None)
        await query.edit_message_text("❌ ব্রডকাস্ট বাতিল করা হয়েছে।")
        return True

    if cb.startswith("br_send_") or cb.startswith("br_bn_") or cb.startswith("br_en_"):
        if cb.startswith("br_bn_"):
            target = "bn"
            owner_id = int(cb[len("br_bn_"):])
        elif cb.startswith("br_en_"):
            target = "en"
            owner_id = int(cb[len("br_en_"):])
        else:
            target = None
            owner_id = int(cb[len("br_send_"):])
        if query.from_user.id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        msg_text = br_pending.pop(owner_id, None)
        if not msg_text:
            await query.edit_message_text("⚠️ মেসেজ পাওয়া যায়নি। আবার চেষ্টা করুন।")
            return True

        await query.edit_message_text("📤 পাঠানো হচ্ছে... পেছনে চলছে, শেষ হলে রিপোর্ট পাবেন।")

        # পেছনে চালাও — বট এর বাকি কাজ আটকে থাকবে না
        _t = asyncio.create_task(_do_broadcast(context, owner_id, msg_text, target))
        _bg_tasks.add(_t)
        _t.add_done_callback(_bg_tasks.discard)
        return True

    return False

# ============================================================
# 💾 চ্যানেলে ডাটা সেভ/লোড — রিস্টার্ট বা ডিপ্লয়েও ভাষা, গ্রুপ, শিডিউল থাকবে
# ============================================================
DATA_CHANNELS = {
    "lang": -1004440717446,       # Sathi Data - Language
    "groups": -1004420248967,     # Sathi Data - Groups
    "schedule": -1004441324345,   # Sathi Data - Schedule
    "broadcast": -1004471127230,  # Sathi Data - Broadcast (বিজ্ঞাপন)
    "ban": -1003827449614,        # Sathi Data - Ban
}
TEMP_CHANNEL_ID = -1003900769068  # Sathi Data - Temp (শুধু পড়ার জন্য)
CHUNK_LIMIT = 3800                # একটা মেসেজে সর্বোচ্চ অক্ষর (টেলিগ্রামের সীমা ৪০৯৬)

store_ids = {n: {"index_id": None, "index_ids": [], "chunk_ids": []} for n in DATA_CHANNELS}
store_loaded = {n: False for n in DATA_CHANNELS}
store_saved_lines = {n: None for n in DATA_CHANNELS}


def _ulen(s: str) -> int:
    """টেলিগ্রাম যেভাবে অক্ষর গোনে (UTF-16)"""
    return len(s.encode("utf-16-le")) // 2


def _snap_lang():
    out = []
    for uid, lang in user_lang.items():
        out.append(json.dumps([uid, lang, 1 if uid in NOTIFY_OFF else 0], separators=(",", ":")))
    for uid in NOTIFY_OFF:
        if uid not in user_lang:
            out.append(json.dumps([uid, None, 1], separators=(",", ":")))
    return sorted(out)


def _snap_groups():
    out = []
    for uid, groups in user_target_groups.items():
        for gid, title in groups.items():
            out.append(json.dumps([uid, gid, title], ensure_ascii=False, separators=(",", ":")))
    return sorted(out)


def _snap_schedule():
    out = []
    for uid, scheds in user_group_schedule.items():
        for gid, s in scheds.items():
            if s.get("off_hour") is None or s.get("on_hour") is None:
                continue
            out.append(json.dumps(
                [uid, gid, s["off_hour"], s.get("off_min", 0), s["on_hour"], s.get("on_min", 0),
                 s.get("night_msg_id"), s.get("morning_msg_id")],
                separators=(",", ":")
            ))
    return sorted(out)


def _apply_lang(lines):
    for ln in lines:
        try:
            rec = json.loads(ln)
            uid, lang = int(rec[0]), rec[1]
            notify_off = rec[2] if len(rec) > 2 else 0
            if lang is not None:
                user_lang.setdefault(uid, lang)
            if notify_off:
                NOTIFY_OFF.add(uid)
        except Exception:
            logging.warning(f"lang লাইন পড়া যায়নি: {ln[:60]}")
    all_bot_users.update(user_lang.keys())


def _apply_groups(lines):
    for ln in lines:
        try:
            uid, gid, title = json.loads(ln)
            user_target_groups.setdefault(int(uid), {}).setdefault(int(gid), title)
        except Exception:
            logging.warning(f"groups লাইন পড়া যায়নি: {ln[:60]}")


def _apply_schedule(lines):
    for ln in lines:
        try:
            uid, gid, oh, om, nh, nm, night_id, morning_id = json.loads(ln)
            user_group_schedule.setdefault(int(uid), {}).setdefault(int(gid), {
                "off_hour": oh, "off_min": om, "on_hour": nh, "on_min": nm,
                "night_msg_id": night_id, "morning_msg_id": morning_id,
            })
        except Exception:
            logging.warning(f"schedule লাইন পড়া যায়নি: {ln[:60]}")


_BC_PART = 1400  # লম্বা রেকর্ড এত অক্ষর করে ভেঙে রাখা হয়


def _is_pristine(g) -> bool:
    return not (g.get("broadcast_msg") or g.get("broadcast_photo") or g.get("broadcast_video")
                or g.get("broadcast_media_group") or g.get("interval") or g.get("is_running"))


def _snap_broadcast():
    out = []
    for uid, groups in group_broadcast_data.items():
        for gid, g in groups.items():
            if _is_pristine(g):
                continue
            if g.get("manual_stop") and not g.get("is_running"):
                continue  # হাতে বন্ধ করা বিজ্ঞাপন চ্যানেল থেকে মুছে যাবে
            mg = g.get("broadcast_media_group")
            mg_c = [[_ITEM_CODE.get(it.get("type"), "d"), it.get("file_id")] for it in mg] if mg else None
            nxt = g.get("next_broadcast_time") or g.get("slot_anchor")
            rec = json.dumps(
                [uid, gid, g.get("interval"), 1 if g.get("is_running") else 0,
                 int(nxt) if nxt else None, g.get("last_msg_id"), 1 if g.get("manual_stop") else 0,
                 g.get("broadcast_msg"), g.get("broadcast_photo"), g.get("broadcast_video"), mg_c],
                ensure_ascii=False, separators=(",", ":")
            )
            if _ulen(rec) <= 3000:
                out.append(rec)
            else:
                parts = [rec[i:i + _BC_PART] for i in range(0, len(rec), _BC_PART)]
                for i, p in enumerate(parts):
                    out.append(f"P|{uid}:{gid}|{i}|{len(parts)}|{p}")
    return sorted(out)


def _apply_broadcast(lines):
    records = []
    parts = {}
    for ln in lines:
        if ln.startswith("P|"):
            try:
                _, key, i, n, p = ln.split("|", 4)
                parts.setdefault(key, {})[int(i)] = (int(n), p)
            except Exception:
                logging.warning(f"broadcast অংশ পড়া যায়নি: {ln[:60]}")
        else:
            records.append(ln)
    for key, d in parts.items():
        n = next(iter(d.values()))[0]
        if len(d) == n:
            records.append("".join(d[i][1] for i in range(n)))
        else:
            logging.error(f"broadcast রেকর্ড অসম্পূর্ণ ({key}): {len(d)}/{n}")
    for rec in records:
        try:
            uid, gid, interval, running, nxt, last_id, manual, msg, photo, video, mg_c = json.loads(rec)
            uid, gid = int(uid), int(gid)
            existing = group_broadcast_data.get(uid, {}).get(gid)
            if existing is not None and not _is_pristine(existing):
                continue  # লোড চলার সময় নতুন করে সেট করা হলে সেটাই থাকবে
            mg = [{"type": _ITEM_FROM_CODE.get(t, "document"), "file_id": f} for t, f in mg_c] if mg_c else None
            data = {
                "broadcast_msg": msg, "broadcast_photo": photo, "broadcast_video": video,
                "broadcast_media_group": mg, "interval": interval, "is_running": bool(running),
                "next_broadcast_time": nxt, "last_msg_id": last_id,
            }
            if manual:
                data["manual_stop"] = True
            if not running and nxt:
                data["slot_anchor"] = nxt
                data["next_broadcast_time"] = None
            group_broadcast_data.setdefault(uid, {})[gid] = data
        except Exception:
            logging.warning(f"broadcast লাইন পড়া যায়নি: {rec[:60]}")


def _snap_ban():
    return sorted(str(u) for u in BANNED_USERS)


_SNAP = {"lang": _snap_lang, "groups": _snap_groups, "schedule": _snap_schedule, "broadcast": _snap_broadcast, "ban": _snap_ban}
def _apply_ban(lines):
    for ln in lines:
        try:
            BANNED_USERS.add(int(ln.strip()))
        except Exception:
            logging.warning(f"ban লাইন পড়া যায়নি: {ln[:60]}")


_APPLY = {"lang": _apply_lang, "groups": _apply_groups, "schedule": _apply_schedule, "broadcast": _apply_broadcast, "ban": _apply_ban}


def _build_chunks(lines):
    chunks, cur, cur_len = [], [], 0
    for ln in lines:
        add = _ulen(ln) + 1
        if cur and cur_len + add > CHUNK_LIMIT:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(ln)
        cur_len += add
    chunks.append(cur)  # ডাটা না থাকলেও অন্তত একটা মেসেজ
    return chunks


def _chunk_text(i, lines):
    return f"DATA #{i}\n" + "\n".join(lines)


def _index_text(name, chunk_ids):
    short = str(DATA_CHANNELS[name]).replace("-100", "", 1)
    links = "  ".join(f'<a href="https://t.me/c/{short}/{mid}">{i}</a>' for i, mid in enumerate(chunk_ids, 1))
    return f"📂 {name.upper()} DATA INDEX\n\n{links}\n\nIDS:" + ",".join(str(m) for m in chunk_ids)


def _is_gone(e) -> bool:
    s = str(e).lower()
    return "not found" in s or "message_id_invalid" in s or "message can't be" in s


async def persist_save(bot, name, lines):
    ch = DATA_CHANNELS[name]
    st = store_ids[name]
    chunks = _build_chunks(lines)
    ids = list(st["chunk_ids"])
    try:
        for i, chunk in enumerate(chunks):
            text = _chunk_text(i + 1, chunk)
            if i < len(ids):
                try:
                    await bot.edit_message_text(chat_id=ch, message_id=ids[i], text=text)
                except Exception as e:
                    if "not modified" in str(e).lower():
                        pass
                    elif _is_gone(e):
                        sent = await bot.send_message(chat_id=ch, text=text)
                        ids[i] = sent.message_id
                    else:
                        raise
            else:
                sent = await bot.send_message(chat_id=ch, text=text)
                ids.append(sent.message_id)
        while len(ids) > len(chunks):
            mid = ids.pop()
            try:
                await bot.delete_message(chat_id=ch, message_id=mid)
            except Exception as e:
                logging.warning(f"extra chunk delete error ({name}): {e}")
    finally:
        st["chunk_ids"] = ids

    # সূচিপত্র (পিন করা মেসেজ) — শুধু তখনই আপডেট যখন মেসেজ নম্বর বদলেছে
    if st["index_id"] is None or st["index_ids"] != ids:
        text = _index_text(name, ids)
        done = False
        if st["index_id"] is not None:
            try:
                await bot.edit_message_text(chat_id=ch, message_id=st["index_id"], text=text,
                                            parse_mode="HTML", disable_web_page_preview=True)
                done = True
            except Exception as e:
                if "not modified" in str(e).lower():
                    done = True
                elif not _is_gone(e):
                    raise
        if not done:
            sent = await bot.send_message(chat_id=ch, text=text, parse_mode="HTML",
                                          disable_web_page_preview=True)
            try:
                await bot.pin_chat_message(chat_id=ch, message_id=sent.message_id, disable_notification=True)
            except Exception as e:
                logging.error(f"pin error ({name}): {e}")
            st["index_id"] = sent.message_id
        st["index_ids"] = list(ids)

    store_saved_lines[name] = lines


_bg_tasks = set()
store_last_try = {n: None for n in DATA_CHANNELS}


def _temp_delete_bg(bot, mid):
    """Temp চ্যানেলের কপি পেছনে মুছে ফেলে (লোড থামে না)"""
    async def _run():
        try:
            await bot.delete_message(chat_id=TEMP_CHANNEL_ID, message_id=mid)
        except Exception as e:
            logging.warning(f"temp delete error: {e}")
    t = asyncio.create_task(_run())
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)


async def persist_load(bot, name):
    """চ্যানেলের পিন করা সূচিপত্র থেকে ডাটা লাইনগুলো ফেরত আনে"""
    ch = DATA_CHANNELS[name]
    st = store_ids[name]
    chat = await bot.get_chat(ch)
    pin = chat.pinned_message
    lines = []
    if pin and pin.text and "IDS:" in pin.text:
        m = re.search(r"IDS:([0-9,]*)", pin.text)
        ids = [int(x) for x in m.group(1).split(",") if x] if m else []
        for mid in ids:
            try:
                fwd = await bot.forward_message(chat_id=TEMP_CHANNEL_ID, from_chat_id=ch, message_id=mid)
            except Exception as e:
                if _is_gone(e):
                    logging.error(f"ডাটা মেসেজ পাওয়া যায়নি ({name} #{mid}): {e}")
                    continue
                raise
            text = fwd.text or ""
            _temp_delete_bg(bot, fwd.message_id)
            lines.extend(ln for ln in text.split("\n")[1:] if ln.strip())
            await asyncio.sleep(0.15)
        st["index_id"] = pin.message_id
        st["index_ids"] = list(ids)
        st["chunk_ids"] = list(ids)
    return lines


async def _persist_load_one(bot, name) -> bool:
    try:
        lines = await persist_load(bot, name)
        _APPLY[name](lines)
        store_saved_lines[name] = sorted(lines)
        store_loaded[name] = True
        logging.info(f"💾 {name} ডাটা লোড হয়েছে ({len(lines)} লাইন)")
        return True
    except Exception as e:
        logging.error(f"💾 {name} ডাটা লোড ব্যর্থ: {e}")
        return False


async def persist_load_all(bot):
    """৩টা চ্যানেল একসাথে (সমান্তরালে) লোড হয়"""
    async def _one(name):
        for _ in range(3):
            if await _persist_load_one(bot, name):
                return
            await asyncio.sleep(2)
    await asyncio.gather(*(_one(n) for n in DATA_CHANNELS))


store_min_gap = {"broadcast": 30}   # বিজ্ঞাপনের ডাটা কমপক্ষে ৩০ সেকেন্ড পরপর সেভ
store_last_save = {}


async def persist_job(context: ContextTypes.DEFAULT_TYPE):
    """কয়েক সেকেন্ড পরপর ডাটা বদলেছে কিনা দেখে, বদলালে চ্যানেলে সেভ করে"""
    bot = context.bot
    now = asyncio.get_running_loop().time()
    for name in DATA_CHANNELS:
        if not store_loaded[name]:
            # লোড না হলে সেভ করব না (পুরোনো ডাটা ঢেকে যাবে); ২০ সেকেন্ড পরপর আবার চেষ্টা
            if store_last_try[name] is None or now - store_last_try[name] >= 20:
                store_last_try[name] = now
                await _persist_load_one(bot, name)
            continue
        lines = _SNAP[name]()
        if lines == store_saved_lines[name]:
            continue
        gap = store_min_gap.get(name, 0)
        if gap and name in store_last_save and now - store_last_save[name] < gap:
            continue
        try:
            await persist_save(bot, name, lines)
            store_last_save[name] = now
            logging.info(f"💾 {name} ডাটা সেভ হয়েছে ({len(lines)} লাইন)")
        except Exception as e:
            logging.error(f"💾 {name} ডাটা সেভ ব্যর্থ: {e}")


async def restore_broadcast_jobs(application):
    """রিস্টার্টের পর চালু থাকা বিজ্ঞাপনগুলো বাকি সময় ধরে আবার চালু করে"""
    now_ts = datetime.now(timezone.utc).timestamp()
    utc_hour = datetime.now(timezone.utc).hour
    is_night_break = (utc_hour >= 16) or (utc_hour < 4)
    restored = 0
    for uid, groups in list(group_broadcast_data.items()):
        my_groups = get_user_groups(uid)
        for gid, g in list(groups.items()):
            if not g.get("is_running"):
                continue
            interval = g.get("interval")
            if (not interval) or gid not in my_groups or (gid in group_lock and group_lock[gid] != uid):
                g["is_running"] = False
                g["next_broadcast_time"] = None
                continue
            if is_night_break:
                # রাতের বিরতি — সকালে অটো চালু হবে
                g["is_running"] = False
                g["slot_anchor"] = g.get("next_broadcast_time")
                g["next_broadcast_time"] = None
                old_id = g.get("last_msg_id")
                if old_id:
                    for mid in (old_id if isinstance(old_id, list) else [old_id]):
                        try:
                            await application.bot.delete_message(chat_id=gid, message_id=mid)
                        except Exception:
                            pass
                    g["last_msg_id"] = None
                continue
            nxt = g.get("next_broadcast_time")
            if not nxt:
                nxt = now_ts + interval
            elif nxt <= now_ts:
                # বন্ধ থাকার সময় যে সময়গুলো পেরিয়ে গেছে সেগুলো বাদ, পরের সময়েই যাবে
                nxt += (int((now_ts - nxt) // interval) + 1) * interval
            first = max(nxt - now_ts, 1)
            g["next_broadcast_time"] = nxt
            group_lock[gid] = uid
            application.job_queue.run_repeating(
                broadcast_job,
                interval=interval,
                first=first,
                name=f"broadcast_{uid}_{gid}",
                data={"user_id": uid, "group_id": gid}
            )
            restored += 1
    logging.info(f"📢 {restored}টা বিজ্ঞাপন আবার চালু হয়েছে")


async def _startup_load(application):
    """পেছনে ডাটা লোড করে — বট ততক্ষণে কমান্ডের উত্তর দিতে থাকে"""
    await persist_load_all(application.bot)
    await check_missed_schedules(application)
    await restore_broadcast_jobs(application)

# ============================================
# 🛠 এডমিন প্যানেল (শুধু OWNER)
# ============================================
def _admin_panel_keyboard(uid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Broadcast", callback_data=f"adm_br_{uid}"),
            InlineKeyboardButton("📣 Group ads", callback_data=f"adm_gp_{uid}"),
        ],
        [
            InlineKeyboardButton("🚫 Ban User", callback_data=f"adm_ban_{uid}"),
            InlineKeyboardButton("✅ Unban User", callback_data=f"adm_unban_{uid}"),
        ],
        [InlineKeyboardButton(get_text(uid, "btn_main_menu"), callback_data=f"start_back_{uid}")],
    ])


def _admin_back_keyboard(uid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛠 Admin Panel", callback_data=f"adm_panel_{uid}")]])


_ADMIN_PROMPTS = {
    "br": "📢 Broadcast\n\nযে মেসেজ সবাইকে পাঠাবেন সেটা লিখে পাঠান।",
    "gp": f"📣 Group ads\n\nগ্রুপ বিজ্ঞাপনের লেখা পাঠান (চাইলে শেষে লিংক দিন)।\n✏️ সর্বোচ্চ {GP_TEXT_LIMIT} অক্ষর",
    "ban": "🚫 Ban\n\nযাকে ব্যান করবেন তার ইউজার আইডি পাঠান।",
    "unban": "✅ Unban\n\nযাকে আনব্যান করবেন তার ইউজার আইডি পাঠান।",
}


async def _handle_adm_callback(query, context, cb):
    user_id = query.from_user.id
    if user_id != OWNER_ID:
        await query.answer("🚫", show_alert=True)
        return

    action = cb[len("adm_"):].rsplit("_", 1)[0]

    if action == "panel":
        admin_waiting.pop(user_id, None)
        await query.edit_message_text(
            "🛠 Admin Panel\n\nকী করবেন?" if user_lang.get(user_id, "bn") == "en" else "🛠 এডমিন প্যানেল\n\nকী করবেন?",
            reply_markup=_admin_panel_keyboard(user_id)
        )
        return

    if action in _ADMIN_PROMPTS:
        admin_waiting[user_id] = action
        user_waiting_setmsg.pop(user_id, None)
        await query.edit_message_text(
            _ADMIN_PROMPTS[action],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, "btn_back"), callback_data=f"adm_panel_{user_id}")]])
        )
        return


async def admin_input_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GP_TEXT, GP_LINK
    user_id = update.effective_user.id
    msg = update.message
    action = admin_waiting.get(user_id)
    if msg is None or not action:
        return

    kb_back = _admin_back_keyboard(user_id)

    if not msg.text:
        await msg.reply_text("⚠️ শুধু লেখা পাঠান।", reply_markup=kb_back)
        return

    text = msg.text.strip()

    # ─── Broadcast (আগের /br এর মতো) ───
    if action == "br":
        total = len(all_bot_users)
        br_pending[OWNER_ID] = text
        admin_waiting.pop(user_id, None)

        bn_count = sum(1 for u in all_bot_users if user_lang.get(u, "bn") == "bn")
        en_count = total - bn_count
        keyboard = [
            [InlineKeyboardButton(f"✅ সবাইকে ({total})", callback_data=f"br_send_{OWNER_ID}")],
            [
                InlineKeyboardButton(f"🇧🇩 বাংলা ({bn_count})", callback_data=f"br_bn_{OWNER_ID}"),
                InlineKeyboardButton(f"🇬🇧 English ({en_count})", callback_data=f"br_en_{OWNER_ID}"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"br_cancel_{OWNER_ID}")],
        ]
        await msg.reply_text(
            f"📢 ব্রডকাস্ট প্রিভিউ\n\n"
            f"{text}\n\n"
            f"👥 মোট প্রাপক: {total} জন\n"
            f"🇧🇩 বাংলা: {bn_count} জন\n"
            f"🇬🇧 English: {en_count} জন\n\n"
            f"কাদের পাঠাবেন?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── Group ads (আগের /gp এর মতো) ───
    if action == "gp":
        body = text

        _b = body
        _w = _b.rsplit(None, 1)
        if len(_w) == 2 and (_w[1].startswith("http") or _w[1].startswith("t.me/")):
            _b = _w[0].strip()
        if _tg_len(_b) > GP_TEXT_LIMIT:
            await msg.reply_text(
                f"⚠️ Group ads এর লেখা অনেক লম্বা!\n\n📏 এখন: {_tg_len(_b)} অক্ষর\n✅ সর্বোচ্চ: {GP_TEXT_LIMIT} অক্ষর\n\nছোট করে আবার পাঠান।",
                reply_markup=kb_back
            )
            return

        GP_LINK = None

        words = body.rsplit(None, 1)
        if len(words) == 2 and (words[1].startswith("http") or words[1].startswith("t.me/")):
            GP_LINK = words[1] if words[1].startswith("http") else "https://" + words[1]
            body = words[0].strip()

        GP_TEXT = body

        GP_PENDING.clear()
        for uid, groups in group_broadcast_data.items():
            for gid, gd in groups.items():
                if gd.get("is_running"):
                    GP_PENDING.add((uid, gid))

        admin_waiting.pop(user_id, None)
        await msg.reply_text(
            f"✅ সেট হয়েছে\n"
            f"🔗 লিংক: {'আছে' if GP_LINK else 'নেই'}\n"
            f"📡 {len(GP_PENDING)} টি গ্রুপের পরের মেসেজে যাবে",
            reply_markup=kb_back
        )
        return

    # ─── Ban / Unban ───
    if action in ("ban", "unban"):
        raw = text.replace(" ", "")
        if not raw.isdigit():
            await msg.reply_text("⚠️ শুধু ইউজার আইডি (সংখ্যা) পাঠান।", reply_markup=kb_back)
            return
        target = int(raw)

        if action == "ban":
            if target == OWNER_ID:
                await msg.reply_text("⚠️ নিজেকে ব্যান করা যাবে না।", reply_markup=kb_back)
                return
            if target in BANNED_USERS:
                result = f"⚠️ {target} আগে থেকেই ব্যান আছে।"
            else:
                BANNED_USERS.add(target)
                await _handle_user_blocked(context, target, banned=True)
                user_names.pop(target, None)
                user_waiting_schedule.pop(target, None)
                user_waiting_setmsg.pop(target, None)
                user_waiting_interval.pop(target, None)
                result = f"🚫 {target} ব্যান হয়েছে, সব ডাটা মুছে গেছে।"
        else:
            if target in BANNED_USERS:
                BANNED_USERS.discard(target)
                result = f"✅ {target} আনব্যান হয়েছে।"
            else:
                result = f"⚠️ {target} ব্যান লিস্টে নেই।"

        admin_waiting.pop(user_id, None)
        await msg.reply_text(result, reply_markup=kb_back)
        return
# ============================================
# MAIN
# ============================================
async def post_init(application):
    _t = asyncio.create_task(_startup_load(application))
    _bg_tasks.add(_t)
    _t.add_done_callback(_bg_tasks.discard)
    # প্রতি ঘণ্টায় expired request clean করো
    application.job_queue.run_repeating(lambda _: asyncio.create_task(_cleanup_expired_requests()), interval=3600, first=60)
    # NEW: Clean up expired broadcast requests
    application.job_queue.run_repeating(lambda _: asyncio.create_task(_cleanup_expired_broadcast_requests()), interval=3600, first=120)


# ============================================
# Restart এর পর missed schedule চেক
# ============================================
async def check_missed_schedules(application):
    """Restart এর পর গ্রুপের সঠিক অবস্থা নিশ্চিত করো — যেকোনো সময় restart হলেও কাজ করবে।"""
    if not user_group_schedule:
        return

    now_bd = datetime.now(BD_TZ)
    now_total = now_bd.hour * 60 + now_bd.minute

    tasks = []
    for user_id, schedules in list(user_group_schedule.items()):
        for group_id, sdata in list(schedules.items()):
            off_hour = sdata.get("off_hour")
            on_hour = sdata.get("on_hour")
            if off_hour is None or on_hour is None:
                continue
            on_min = sdata.get("on_min", 0)
            off_t = off_hour * 60 + sdata.get("off_min", 0)
            on_t = on_hour * 60 + on_min

            # এখন গ্রুপ OFF থাকার কথা কিনা নির্ধারণ করো
            if off_t < on_t:
                should_be_off = off_t <= now_total < on_t
            else:
                should_be_off = now_total >= off_t or now_total < on_t

            if should_be_off:
                # গ্রুপ already locked কিনা চেক করো — locked থাকলে আবার মেসেজ পাঠাবো না
                try:
                    chat = await application.bot.get_chat(group_id)
                    already_locked = (
                        chat.permissions is not None and
                        not chat.permissions.can_send_messages
                    )
                except Exception:
                    already_locked = False

                if already_locked:
                    logging.info(f"🔄 Restart: group {group_id} already OFF — skipping.")
                else:
                    tasks.append(do_group_night_off(application.bot, group_id, on_hour, user_id, on_min))
                    logging.info(f"🔄 Restart: group {group_id} should be OFF — fixing now.")
            else:
                # গ্রুপ already unlocked কিনা চেক করো — unlocked থাকলে আবার মেসেজ পাঠাবো না
                try:
                    chat = await application.bot.get_chat(group_id)
                    already_open = (
                        chat.permissions is not None and
                        chat.permissions.can_send_messages
                    )
                except Exception:
                    already_open = False

                if already_open:
                    logging.info(f"🔄 Restart: group {group_id} already ON — skipping.")
                else:
                    tasks.append(do_group_morning_on(application.bot, group_id, user_id))
                    logging.info(f"🔄 Restart: group {group_id} should be ON — fixing now.")

    if tasks:
        await asyncio.gather(*tasks)
        logging.info("✅ Schedule state recovered after restart.")


# ══════════════════════════════════════════════════════════
# 🌐 Keep-Alive Server (Render-এ পোর্ট খোলা রাখার জন্য)
# ══════════════════════════════════════════════════════════
def run_keep_alive_server():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class PingHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()


def main():
    # Render-এর জন্য keep-alive সার্ভার
    threading.Thread(target=run_keep_alive_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ব্যান গেট — সবার আগে চলবে
    app.add_handler(TypeHandler(Update, ban_gate), group=-1)

    # Group only
    app.add_handler(CommandHandler("set", set_group, filters=filters.ChatType.GROUPS))
    # Private chat only
    app.add_handler(CommandHandler("set", set_command_private, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("off", off_notify_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("on", on_notify_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, setmsg_receive))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, setmsg_receive))
    app.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, setmsg_receive))
    app.add_handler(MessageHandler(filters.Document.VIDEO & filters.ChatType.PRIVATE, setmsg_receive))
    # বাকি সব ধরন (ভয়েস, অডিও, স্টিকার, GIF, ফাইল, ভিডিও মেসেজ ইত্যাদি)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, setmsg_receive))
    app.add_handler(ChatMemberHandler(handle_bot_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(button_callback))

# ডাটা চ্যানেলে সেভ (প্রতি ২০ সেকেন্ডে বদল দেখে)
    app.job_queue.run_repeating(persist_job, interval=5, first=10)

    # প্রতি মিনিটে শিডিউল চেক
    _sec_now = datetime.now().second
    app.job_queue.run_repeating(schedule_checker, interval=60, first=(61 - _sec_now))

    from datetime import time as dt_time
    # রাত ১১:০০ BD = ১৭:০০ UTC
    app.job_queue.run_daily(auto_broadcast_off, time=dt_time(16, 0, tzinfo=timezone.utc))
    # সকাল ১০:০০ BD = ০৪:০০ UTC
    app.job_queue.run_daily(auto_broadcast_on, time=dt_time(4, 0, tzinfo=timezone.utc))

    print("Bot started...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
