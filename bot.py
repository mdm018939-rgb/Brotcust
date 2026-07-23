import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ChatMemberHandler
)
from supabase import create_client, Client

BOT_TOKEN = "8796122248:AAH_TvWQtQk2GV-TbCqxHzmSq2VeFO6f6Ag"

OWNER_ID = 6625019627

# ============================================================
# Supabase Config (NEW - for user_lang only)
# ============================================================
SUPABASE_URL = "https://wnyhxfghmncgafashygv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndueWh4ZmdobW5jZ2FmYXNoeWd2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NzAwNTAwMiwiZXhwIjoyMDkyNTgxMDAyfQ.AJMrHPRko8SHm_bS12cQY7ZOl3RbaDDOanzEz_UsKtk"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

user_group_schedule = {}  # {user_id: {group_id: {"off_hour": 18, "on_hour": 6, "night_msg_id": None}}}
user_target_groups = {}   # {user_id: {group_id: group_title}}
all_bot_users = set()     # যে কেউ /start দিলে এখানে যোগ হবে

BD_TZ = timezone(timedelta(hours=6))

# ============================================================
# নতুন per-group broadcast data structure
# group_broadcast_data[user_id][group_id] = {
#   broadcast_msg, broadcast_photo, broadcast_video,
#   broadcast_media_group, interval, is_running,
#   next_broadcast_time, last_msg_id
# }
# ============================================================
group_broadcast_data = {}  # {user_id: {group_id: {...}}}
user_waiting_setmsg = {}   # {user_id: group_id} — কোন গ্রুপের জন্য মেসেজ অপেক্ষায়
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


# ============================================================
# ভাষার টেক্সট
# ============================================================
TEXTS = {
    "bn": {
        "welcome": "🤖 ব্রডকাস্ট বট এ\n\n✨ স্বাগতম!\n\n👇 নিচের বাটন থেকে কাজ করুন:",
        "btn_groups": "🎯 গ্রুপ লিস্ট",
        "btn_setmsg": "📝 বিজ্ঞাপন সেট",
        "btn_status": "📊 স্ট্যাটাস",
        "btn_stop": "🛑 বন্ধ করুন",
        "btn_schedule": "⏰ শিডিউল",
        "btn_help": "📖 হেল্প",
        "btn_lang": "🌐 ভাষা পরিবর্তন",
        "btn_back": "🔙 ব্যাক",
        "btn_cancel": "❌ বাতিল",
        "btn_remove": "❌ {title} বাদ দিন",
        "btn_stop_all": "🛑 All Group বন্ধ করো",
        "auto_off": "🛑 সব গ্রুপের broadcast অটো বন্ধ হয়ে গেছে।\n🌅 সকাল ১০:০০ তে আবার চালু হবে।",
        "auto_on": "🌅 সকাল ১০:০০ বাজে!\n✅ আপনার broadcast অটো চালু হয়েছে।",
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
        "schedule_current": "📛 গ্রুপ: {title}\n\n⚙️ বর্তমান শিডিউল:\n🌙 বন্ধ: রাত {off}টা\n🌅 চালু: {on}\n\nকী করতে চান?",
        "schedule_set_off": "📛 গ্রুপ: {title}\n\n🌙 কয়টায় গ্রুপ অটো বন্ধ করতে চান?",
        "schedule_del_done": "✅ শিডিউল বাদ দেওয়া হয়েছে!\n\n📛 গ্রুপ: {title}\n⚠️ এই গ্রুপ আর অটো অন/অফ হবে না।",
        "schedule_set_on": "📛 গ্রুপ: {title}\n🌙 বন্ধ: রাত {off}টা\n\n🌅 কয়টায় গ্রুপ অটো চালু করতে চান?",
        "schedule_done": "✅ শিডিউল সেট হয়েছে!\n\n📛 গ্রুপ: {title}\n🌙 বন্ধ: রাত {off}টা\n🌅 চালু: {on}",
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
        "send_media": "⚠️ টেক্সট, ছবি বা ভিডিও পাঠান।",
        "access_denied": "🛡 এক্সেস ডিনাইড\n\n⚠️ দুঃখিত, আপনার কাছে এই বটটি ব্যবহার করার অনুমতি নেই।\n📩 অনুমতি পেতে এডমিন কে আইডি পাঠান!",
        "set_in_group": "⚠️ /set কমান্ড গ্রুপে দিতে হয়!\n\n📌 কিভাবে করবেন:\n1️⃣ আপনার গ্রুপে বটকে এডমিন করুন\n2️⃣ গ্রুপে গিয়ে /set লিখুন\n3️⃣ বট কনফার্ম করবে ✅\n\n💡 এই ইনবক্সে /set কাজ করে না।",
        "not_group_admin": "❌ আপনি এই গ্রুপের এডমিন নন!\n\nশুধু এডমিনরা /set দিতে পারবে।",
        "bot_not_admin": "❌ বটকে আগে এডমিন করুন!\n\n📌 গ্রুপ সেটিংস → এডমিন → বট সিলেক্ট করুন\nতারপর আবার /set দিন।",
        "group_already_added": "⚠️ এই গ্রুপ আগেই যোগ আছে!\n\n📛 নাম: {title}\n🆔 আইডি: {gid}\n📡 মোট গ্রুপ: {count} টি",
        "group_added": "✅ গ্রুপ সফলভাবে যোগ হয়েছে!\n\n📛 নাম: {title}\n🆔 আইডি: {gid}\n📡 মোট গ্রুপ: {count} টি",
        "status_menu": "📊 স্ট্যাটাস মেনু\n\nনিচের অপশনগুলো থেকে বেছে নিন:",
        "btn_group_status": "📡 গ্রুপ স্ট্যাটাস",
        "btn_schedule_status": "⏰ শিডিউল",
        "status_no_active": "📊 বর্তমান অবস্থা\n\n🛑 কোনো গ্রুপে ব্রডকাস্ট চালু নেই!\n\n📡 মোট গ্রুপ: {count} টি\n🕒 সময়: {time}\n\n▶️ চালু করতে বিজ্ঞাপন সেট বাটন চাপুন।",
        "status_active": "📊 বর্তমান অবস্থা\n\n✅ {active} টি গ্রুপে ব্রডকাস্ট চালু\n📡 মোট গ্রুপ: {total} টি\n🕒 সময়: {time}\n\n👇 গ্রুপে ট্যাপ করুন বিস্তারিত দেখতে:",
        "schedule_none": "⏰ শিডিউল লিস্ট\n\n🕒 বর্তমান সময়: {time}\n\n⚠️ কোনো শিডিউল সেট করা নেই।",
        "schedule_list": "⏰ শিডিউল লিস্ট\n\n🕒 বর্তমান সময়: {time}",
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
        "select_schedule_group": "⚙️ গ্রুপ শিডিউল সেট করুন\n\nকোন গ্রুপের শিডিউল সেট করতে চান?",
        "ad_set_one": "✅ বিজ্ঞাপন সেট হয়েছে! {emoji}\n📛 গ্রুপ: {title}\n\n⏱ ইন্টারভাল সিলেক্ট করুন:",
        "ad_set_all": "✅ সব গ্রুপে বিজ্ঞাপন সেট হয়েছে! {emoji}\n📡 মোট: {count} টি গ্রুপ\n\n⏱ ইন্টারভাল সিলেক্ট করুন:",
        "send_ad_group": "📛 গ্রুপ: {title}\n\n📝 এখন এই গ্রুপের বিজ্ঞাপন পাঠান\n(ছবি, ভিডিও বা টেক্সট)",
        "send_ad_all": "📡 সব গ্রুপ সিলেক্ট! ({count} টি)\n\n📝 এখন বিজ্ঞাপন পাঠান\n(ছবি, ভিডিও বা টেক্সট)",
        "btn_cancel2": "❌ বাতিল",
        "btn_stop_all2": "🛑 All Group বন্ধ করো",
        "no_admin_text": "\n⛔ এডমিন নেই: {count} টি গ্রুপ\n",
        "no_admin_text2": "\n⛔ এডমিন নেই: {count} টি\n",
        "stop_header2": "🛑 {count} টি গ্রুপে ব্রডকাস্ট চালু\n\nকোন গ্রুপের ব্রডকাস্ট বন্ধ করবেন?",
        "no_broadcast2": "⚠️ কোনো গ্রুপে ব্রডকাস্ট চালু নেই!\n\n▶️ চালু করতে বিজ্ঞাপন সেট বাটন চাপুন।",
        "help_text": (
            "📖 বট ব্যবহার সম্পূর্ণ গাইড\n\n"
            "𝐒𝐭𝐞𝐩 ১ — গ্রুপ সেট করুন\n"
            "• আপনার গ্রুপে বটকে এডমিন করুন\n"
            "• গ্রুপে গিয়ে /set দিন\n"
            "• বট কনফার্ম করবে ✅\n"
            "• গ্রুপ লিস্ট বাটন দিয়ে সেট করা গ্রুপ দেখুন\n\n"
            "𝐒𝐭𝐞𝐩 ২ — বিজ্ঞাপন সেট করুন\n"
            "• বিজ্ঞাপন সেট বাটন চাপুন\n"
            "• কোন গ্রুপে পাঠাবেন সিলেক্ট করুন\n"
            "• ছবি বা টেক্সট পাঠান\n"
            "• ইন্টারভাল সিলেক্ট করুন ✅\n\n"
            "𝐒𝐭𝐞𝐩 ৩ — আলাদা গ্রুপে আলাদা বিজ্ঞাপন\n"
            "• প্রতিটা গ্রুপের আলাদা মেসেজ সেট করুন\n"
            "• আলাদা interval দিন\n"
            "• সব গ্রুপ একসাথে চলবে ✅\n\n"
            "𝐒𝐭𝐞𝐩 ৪ — broadcast নিয়ন্ত্রণ\n"
            "• স্ট্যাটাস — গ্রুপ বাটন দেখাবে, ট্যাপ করুন\n"
            "• বন্ধ করুন — নির্দিষ্ট বা সব গ্রুপ বন্ধ\n\n"
            "𝐒𝐭𝐞𝐩 ৫ — অটো অন/অফ শিডিউল\n"
            "• শিডিউল বাটন দিয়ে গ্রুপ অন/অফ সময় সেট করুন\n\n"
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
        "welcome": "🤖 Welcome to Brodcust Bot!\n\n✨ Hello!\n\n👇 Use the buttons below:",
        "btn_groups": "🎯 Group List",
        "btn_setmsg": "📝 Set Ad",
        "btn_status": "📊 Status",
        "btn_stop": "🛑 Stop",
        "btn_schedule": "⏰ Schedule",
        "btn_help": "📖 Help",
        "btn_lang": "🌐 Change Language",
        "btn_back": "🔙 Back",
        "btn_cancel": "❌ Cancel",
        "btn_remove": "❌ Remove {title}",
        "btn_stop_all": "🛑 Stop All Groups",
        "auto_off": "🛑 All group broadcasts have been automatically stopped.\n🌅 Will resume at 10:00 AM.",
        "auto_on": "🌅 Good Morning!\n✅ Your broadcast has been automatically started.",
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
        "schedule_set_off": "📛 Group: {title}\n\n🌙 What time should the group auto-stop?",
        "schedule_del_done": "✅ Schedule removed!\n\n📛 Group: {title}\n⚠️ This group will no longer auto on/off.",
        "schedule_set_on": "📛 Group: {title}\n🌙 Off: {off}\n\n🌅 What time should the group auto-start?",
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
        "send_media": "⚠️ Please send text, photo or video.",
        "access_denied": "🛡 Access Denied\n\n⚠️ Sorry, you do not have permission to use this bot.\n📩 Send your ID to the admin to get access!",
        "set_in_group": "⚠️ /set command must be used in a group!\n\n📌 How to do it:\n1️⃣ Make the bot admin in your group\n2️⃣ Go to the group and type /set\n3️⃣ Bot will confirm ✅\n\n💡 /set does not work in this inbox.",
        "not_group_admin": "❌ You are not an admin of this group!\n\nOnly admins can use /set.",
        "bot_not_admin": "❌ Please make the bot admin first!\n\n📌 Group Settings → Admin → Select Bot\nThen type /set again.",
        "group_already_added": "⚠️ This group is already added!\n\n📛 Name: {title}\n🆔 ID: {gid}\n📡 Total groups: {count}",
        "group_added": "✅ Group added successfully!\n\n📛 Name: {title}\n🆔 ID: {gid}\n📡 Total groups: {count}",
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
        "select_schedule_group": "⚙️ Set Group Schedule\n\nWhich group do you want to schedule?",
        "ad_set_one": "✅ Ad has been set! {emoji}\n📛 Group: {title}\n\n⏱ Select interval:",
        "ad_set_all": "✅ Ad set for all groups! {emoji}\n📡 Total: {count} groups\n\n⏱ Select interval:",
        "send_ad_group": "📛 Group: {title}\n\n📝 Now send the ad for this group\n(photo, video or text)",
        "send_ad_all": "📡 All groups selected! ({count})\n\n📝 Now send the ad\n(photo, video or text)",
        "btn_cancel2": "❌ Cancel",
        "btn_stop_all2": "🛑 Stop All Groups",
        "no_admin_text": "\n⛔ No admin: {count} groups\n",
        "no_admin_text2": "\n⛔ No admin: {count}\n",
        "stop_header2": "🛑 {count} group(s) broadcasting\n\nWhich group do you want to stop?",
        "no_broadcast2": "⚠️ No broadcast is running!\n\n▶️ Press Set Ad to start.",
        "help_text": (
            "📖 Complete Bot Usage Guide\n\n"
            "𝐒𝐭𝐞𝐩 1 — Set a Group\n"
            "• Make the bot admin in your group\n"
            "• Go to the group and type /set\n"
            "• Bot will confirm ✅\n"
            "• Use Group List button to see set groups\n\n"
            "𝐒𝐭𝐞𝐩 2 — Set an Ad\n"
            "• Press Set Ad button\n"
            "• Select which group to send to\n"
            "• Send photo or text\n"
            "• Select interval ✅\n\n"
            "𝐒𝐭𝐞𝐩 3 — Different Ads for Different Groups\n"
            "• Set separate messages for each group\n"
            "• Set different intervals\n"
            "• All groups run simultaneously ✅\n\n"
            "𝐒𝐭𝐞𝐩 4 — Control Broadcast\n"
            "• Status — shows group buttons, tap to view\n"
            "• Stop — stop specific or all groups\n\n"
            "𝐒𝐭𝐞𝐩 5 — Auto On/Off Schedule\n"
            "• Use Schedule button to set group on/off times\n\n"
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
def format_time_english(hour: int) -> str:
    """Convert hour (0-23) to AM/PM format"""
    if hour == 0:
        return "12 AM"
    elif hour < 12:
        return f"{hour} AM"
    elif hour == 12:
        return "12 PM"
    else:
        return f"{hour - 12} PM"

def format_time_bangla(hour: int) -> str:
    """Convert hour (0-23) to Bengali format (রাত/সকাল)"""
    if hour >= 20 or hour <= 4:
        return f"রাত {hour % 12 if hour % 12 != 0 else 12}টা"
    else:
        return f"সকাল {hour}টা"

def format_schedule_time(user_id: int, hour: int) -> str:
    """Format time based on user's language"""
    lang = user_lang.get(user_id, "bn")
    if lang == "en":
        return format_time_english(hour)
    else:
        return format_time_bangla(hour)


logging.basicConfig(level=logging.INFO)


def is_allowed(user_id):
    return True


def get_user_groups(user_id):
    if user_id not in user_target_groups:
        user_target_groups[user_id] = {}
    return user_target_groups[user_id]


# ============================================
# NEW - Supabase user_lang persistence functions
# ============================================
async def load_user_lang_from_supabase():
    """Supabase থেকে সব user_lang লোড করো"""
    try:
        result = await asyncio.to_thread(
            lambda: supabase.table("user_lang").select("*").execute()
        )
        if result.data:
            global user_lang, all_bot_users
            for row in result.data:
                user_id = row["user_id"]
                lang = row["lang"]
                user_lang[user_id] = lang
                all_bot_users.add(user_id)
            logging.info(f"✅ Loaded {len(result.data)} user_lang entries from Supabase")
    except Exception as e:
        logging.error(f"Failed to load user_lang from Supabase: {e}")

async def upsert_user_lang(user_id: int, lang: str):
    """Supabase-এ user_lang upsert করো (non-blocking)"""
    try:
        await asyncio.to_thread(
            lambda: supabase.table("user_lang").upsert({
                "user_id": user_id,
                "lang": lang
            }).execute()
        )
    except Exception as e:
        logging.error(f"Failed to upsert user_lang for {user_id}: {e}")


# ============================================
# Supabase Config (OLD - for full data save, KEPT FOR BACKWARD COMPATIBILITY)
# ============================================
# Note: The old supabase_request and save_data/load_data functions are kept
# for compatibility with existing code that might call them.
# However, they are NOT used for the new user_lang persistence.
# The new system uses the supabase client directly with the user_lang table only.

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
    keyboard.append([InlineKeyboardButton("⚡ Powered By Mamun", url="https://t.me/mrincome9")])
    return InlineKeyboardMarkup(keyboard)


def get_start_text(user_id):
    """Start মেনুর text"""
    return get_text(user_id, "welcome")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await access_denied(update)
        return

    user_id = update.effective_user.id

    # নতুন user — আগে ভাষা সিলেক্ট
    if user_id not in all_bot_users:
        all_bot_users.add(user_id)
        # Owner কে নোটিফাই করো
        user = update.effective_user
        name = user.full_name or str(user_id)
        username = f"@{user.username}" if user.username else "username নেই"
        try:
            msg = "👤 নতুন user!\n\n🆔 ID: " + str(user_id) + "\n📛 নাম: " + name + "\n🔗 " + username
            await context.bot.send_message(chat_id=OWNER_ID, text=msg)
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
        await update.message.reply_text(
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
        await update.message.reply_text(
            get_text(user_id, "group_already_added").format(title=title, gid=gid, count=len(get_user_groups(user_id)))
        )
        return

    get_user_groups(user_id)[gid] = title

    await update.message.reply_text(
        get_text(user_id, "group_added").format(title=title, gid=gid, count=len(get_user_groups(user_id)))
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

    if len(items) == 1:
        item = items[0]
        if item["type"] == "photo":
            gdata["broadcast_photo"] = item["file_id"]
            gdata["broadcast_video"] = None
        else:
            gdata["broadcast_video"] = item["file_id"]
            gdata["broadcast_photo"] = None
        gdata["broadcast_media_group"] = None
        gdata["broadcast_msg"] = caption
    else:
        gdata["broadcast_media_group"] = items
        gdata["broadcast_msg"] = caption
        gdata["broadcast_photo"] = None
        gdata["broadcast_video"] = None

    chat_id = buf.get("chat_id")
    if not chat_id:
        return

    # interval সিলেক্ট দেখাও
    my_groups = get_user_groups(user_id)
    g_title = my_groups.get(group_id, str(group_id))
    type_emoji = "📸" if gdata.get("broadcast_photo") else "🎥" if gdata.get("broadcast_video") else "📸📸"
    keyboard = _interval_keyboard(user_id, group_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text=get_text(user_id, "ad_set_one").format(emoji=type_emoji, title=g_title),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


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

    for gid in my_groups:
        gdata = get_group_data(user_id, gid)
        if len(items) == 1:
            item = items[0]
            if item["type"] == "photo":
                gdata["broadcast_photo"] = item["file_id"]
                gdata["broadcast_video"] = None
            else:
                gdata["broadcast_video"] = item["file_id"]
                gdata["broadcast_photo"] = None
            gdata["broadcast_media_group"] = None
            gdata["broadcast_msg"] = caption
        else:
            gdata["broadcast_media_group"] = items
            gdata["broadcast_msg"] = caption
            gdata["broadcast_photo"] = None
            gdata["broadcast_video"] = None

    if user_id in user_waiting_setmsg:
        del user_waiting_setmsg[user_id]

    if not chat_id:
        return

    type_emoji = "📸📸" if len(items) > 1 else ("📸" if items and items[0]["type"] == "photo" else "🎥")
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
        text=get_text(user_id, "ad_set_all").format(emoji=type_emoji, count=len(my_groups)),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def _interval_keyboard(user_id, group_id):
    return [
        [
            InlineKeyboardButton(get_text(user_id, "btn_15min"), callback_data=f"intv_{user_id}_{group_id}_15"),
            InlineKeyboardButton(get_text(user_id, "btn_30min"), callback_data=f"intv_{user_id}_{group_id}_30"),
        ],
        [
            InlineKeyboardButton(get_text(user_id, "btn_45min"), callback_data=f"intv_{user_id}_{group_id}_45"),
            InlineKeyboardButton(get_text(user_id, "btn_60min"), callback_data=f"intv_{user_id}_{group_id}_60"),
        ],
    ]


async def setmsg_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message


    if user_id not in user_waiting_setmsg:
        return

    group_id = user_waiting_setmsg[user_id]
    msg = update.message
    my_groups = get_user_groups(user_id)

    # ✅ All Group মোড
    if group_id == "all":
        # Media Group (একাধিক ছবি/ভিডিও) — All Group এ সাপোর্ট
        if msg.media_group_id:
            buf_key = f"{user_id}_all"
            buf = _media_group_buffer.get(buf_key)
            if buf and buf["media_group_id"] == msg.media_group_id:
                if msg.photo:
                    buf["items"].append({"type": "photo", "file_id": msg.photo[-1].file_id})
                elif msg.video:
                    buf["items"].append({"type": "video", "file_id": msg.video.file_id})
                if msg.caption:
                    buf["caption"] = msg.caption
            else:
                items = []
                if msg.photo:
                    items.append({"type": "photo", "file_id": msg.photo[-1].file_id})
                elif msg.video:
                    items.append({"type": "video", "file_id": msg.video.file_id})
                _media_group_buffer[buf_key] = {
                    "media_group_id": msg.media_group_id,
                    "items": items,
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
            gdata = get_group_data(user_id, gid)
            if msg.photo:
                gdata["broadcast_photo"] = msg.photo[-1].file_id
                gdata["broadcast_video"] = None
                gdata["broadcast_media_group"] = None
                gdata["broadcast_msg"] = msg.caption or ""
                content_ok = True
            elif msg.video:
                gdata["broadcast_video"] = msg.video.file_id
                gdata["broadcast_photo"] = None
                gdata["broadcast_media_group"] = None
                gdata["broadcast_msg"] = msg.caption or ""
                content_ok = True
            elif msg.text:
                gdata["broadcast_msg"] = msg.text
                gdata["broadcast_photo"] = None
                gdata["broadcast_video"] = None
                gdata["broadcast_media_group"] = None
                content_ok = True

        if not content_ok:
            await msg.reply_text(get_text(user_id, "send_media"))
            return

        del user_waiting_setmsg[user_id]

        type_emoji = "📸" if msg.photo else "🎥" if msg.video else "📝"
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
        await msg.reply_text(
            get_text(user_id, "ad_set_all").format(emoji=type_emoji, count=len(my_groups)),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── নির্দিষ্ট একটি গ্রুপ ───
    gdata = get_group_data(user_id, group_id)
    g_title = my_groups.get(group_id, str(group_id))

    # Media Group
    if msg.media_group_id:
        buf_key = f"{user_id}_{group_id}"
        buf = _media_group_buffer.get(buf_key)
        if buf and buf["media_group_id"] == msg.media_group_id:
            if msg.photo:
                buf["items"].append({"type": "photo", "file_id": msg.photo[-1].file_id})
            elif msg.video:
                buf["items"].append({"type": "video", "file_id": msg.video.file_id})
            if msg.caption:
                buf["caption"] = msg.caption
        else:
            items = []
            if msg.photo:
                items.append({"type": "photo", "file_id": msg.photo[-1].file_id})
            elif msg.video:
                items.append({"type": "video", "file_id": msg.video.file_id})
            _media_group_buffer[buf_key] = {
                "media_group_id": msg.media_group_id,
                "items": items,
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

    # Single Photo
    if msg.photo:
        gdata["broadcast_photo"] = msg.photo[-1].file_id
        gdata["broadcast_video"] = None
        gdata["broadcast_media_group"] = None
        gdata["broadcast_msg"] = msg.caption or ""
    # Single Video
    elif msg.video:
        gdata["broadcast_video"] = msg.video.file_id
        gdata["broadcast_photo"] = None
        gdata["broadcast_media_group"] = None
        gdata["broadcast_msg"] = msg.caption or ""
    # Text
    elif msg.text:
        gdata["broadcast_msg"] = msg.text
        gdata["broadcast_photo"] = None
        gdata["broadcast_video"] = None
        gdata["broadcast_media_group"] = None
    else:
        await update.message.reply_text(get_text(user_id, "send_media"))
        return

    del user_waiting_setmsg[user_id]

    type_emoji = "📸" if gdata.get("broadcast_photo") else "🎥" if gdata.get("broadcast_video") else "📝"
    keyboard = _interval_keyboard(user_id, group_id)
    await update.message.reply_text(
        get_text(user_id, "ad_set_one").format(emoji=type_emoji, title=g_title),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


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

async def _check_broadcast_lock_and_request(context: ContextTypes.DEFAULT_TYPE, user_id: int, group_id: int, group_title: str) -> bool:
    """
    ব্রডকাস্ট লক চেক করে। লক থাকলে রিকুয়েস্ট অপশন দেখায়।
    রিটার্ন: True = ব্রডকাস্ট চালু হতে পারে, False = ব্লক করা হয়েছে
    """
    # যদি লক না থাকে, অথবা লকের owner এই ইউজার নিজেই
    if group_id not in group_lock or group_lock[group_id] == user_id:
        return True
    
    owner_id = group_lock[group_id]
    owner_name = await _get_user_name(owner_id, context)
    
    # চেক করো আগের রিকুয়েস্ট পেন্ডিং আছে কিনা
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
            # সেন্ডারকে মেসেজ দাও
            await context.bot.send_message(
                chat_id=user_id,
                text=get_text(user_id, "broadcast_request_already_pending").format(countdown=countdown),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, "btn_back"), callback_data=f"start_back_{user_id}")]])
            )
            return False
        else:
            # মেয়াদ শেষ — পুরনো রিকুয়েস্ট মুছে দাও
            broadcast_requests.pop(existing_pending, None)
    
    # লক দেখাও + রিকুয়েস্ট বাটন
    await context.bot.send_message(
        chat_id=user_id,
        text=get_text(user_id, "broadcast_locked").format(owner_name=owner_name, group_title=group_title),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
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
        # সেন্ডারকে কনফার্মেশন
        await context.bot.send_message(
            chat_id=from_user_id,
            text=get_text(from_user_id, "broadcast_request_sent").format(owner_name=await _get_user_name(owner_id, context))
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
    try:
        await asyncio.to_thread(
            lambda: supabase.table("user_lang").delete().eq("user_id", user_id).execute()
        )
    except Exception as e:
        logging.error(f"Failed to delete user_lang from Supabase for {user_id}: {e}")
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
    try:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(
                f"🚫 একজন user বট block করেছে!\n\n"
                f"🆔 User ID: {user_id}\n"
                f"🗑 সব ডেটা মুছে দেওয়া হয়েছে।"
            )
        )
    except Exception:
        pass


# ============================================
# Callback Handler
# ============================================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    await query.answer()
    cb = query.data

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
            )
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
        pending_type = context.user_data.get("pending_type")

        if pending_type == "photo":
            for gid in my_groups:
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
                get_text(owner_id, "ad_set_all").format(emoji="📸", count=len(my_groups)),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        user_waiting_setmsg[owner_id] = "all"
        keyboard = [[InlineKeyboardButton(get_text(owner_id, "btn_cancel2"), callback_data=f"setmsg_cancel_{owner_id}")]]
        await query.edit_message_text(
            get_text(owner_id, "send_ad_all").format(count=len(my_groups)),
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
            gdata = get_group_data(owner_id, gid)
            has_content = (
                gdata.get("broadcast_msg") or
                gdata.get("broadcast_photo") or
                gdata.get("broadcast_video") or
                gdata.get("broadcast_media_group")
            )
            if not has_content:
                continue

            # NEW: Check broadcast lock first
            if not await _check_broadcast_lock_and_request(context, owner_id, gid, my_groups.get(gid, str(gid))):
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
        if not await _check_broadcast_lock_and_request(context, owner_id, group_id, g_title):
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
        if not await _check_broadcast_lock_and_request(context, owner_id, group_id, g_title):
            return

        gdata["interval"] = seconds

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

        content_type = get_text(owner_id, "content_text")
        if gdata.get("broadcast_media_group"):
            content_type = get_text(owner_id, "content_album")
        elif gdata.get("broadcast_photo"):
            content_type = get_text(owner_id, "content_photo")
        elif gdata.get("broadcast_video"):
            content_type = get_text(owner_id, "content_video")

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
            off_label = format_schedule_time(owner_id, off_h)
            on_label = format_schedule_time(owner_id, on_h)
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
            keyboard = [
                [
                    InlineKeyboardButton(get_text(owner_id, "btn_night_9"), callback_data=f"offgp_off_{owner_id}_{gid}_21"),
                    InlineKeyboardButton(get_text(owner_id, "btn_night_10"), callback_data=f"offgp_off_{owner_id}_{gid}_22"),
                ],
                [
                    InlineKeyboardButton(get_text(owner_id, "btn_night_11"), callback_data=f"offgp_off_{owner_id}_{gid}_23"),
                    InlineKeyboardButton(get_text(owner_id, "btn_night_12"), callback_data=f"offgp_off_{owner_id}_{gid}_0"),
                ],
                [
                    InlineKeyboardButton(get_text(owner_id, "btn_night_1"), callback_data=f"offgp_off_{owner_id}_{gid}_1"),
                    InlineKeyboardButton(get_text(owner_id, "btn_night_2"), callback_data=f"offgp_off_{owner_id}_{gid}_2"),
                ],
                [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_back_{owner_id}")],
            ]
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
        keyboard = [
            [
                InlineKeyboardButton(get_text(owner_id, "btn_night_9"), callback_data=f"offgp_off_{owner_id}_{gid}_21"),
                InlineKeyboardButton(get_text(owner_id, "btn_night_10"), callback_data=f"offgp_off_{owner_id}_{gid}_22"),
            ],
            [
                InlineKeyboardButton(get_text(owner_id, "btn_night_11"), callback_data=f"offgp_off_{owner_id}_{gid}_23"),
                InlineKeyboardButton(get_text(owner_id, "btn_night_12"), callback_data=f"offgp_off_{owner_id}_{gid}_0"),
            ],
            [
                InlineKeyboardButton(get_text(owner_id, "btn_night_1"), callback_data=f"offgp_off_{owner_id}_{gid}_1"),
                InlineKeyboardButton(get_text(owner_id, "btn_night_2"), callback_data=f"offgp_off_{owner_id}_{gid}_2"),
            ],
            [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_grp_{owner_id}_{gid}")],
        ]
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
        keyboard = [
            [
                InlineKeyboardButton(get_text(owner_id, "btn_morning_6"), callback_data=f"offgp_on_{owner_id}_{gid}_{off_hour_bd}_6"),
                InlineKeyboardButton(get_text(owner_id, "btn_morning_7"), callback_data=f"offgp_on_{owner_id}_{gid}_{off_hour_bd}_7"),
            ],
            [
                InlineKeyboardButton(get_text(owner_id, "btn_morning_8"), callback_data=f"offgp_on_{owner_id}_{gid}_{off_hour_bd}_8"),
                InlineKeyboardButton(get_text(owner_id, "btn_morning_9"), callback_data=f"offgp_on_{owner_id}_{gid}_{off_hour_bd}_9"),
            ],
            [
                InlineKeyboardButton(get_text(owner_id, "btn_morning_10"), callback_data=f"offgp_on_{owner_id}_{gid}_{off_hour_bd}_10"),
                InlineKeyboardButton(get_text(owner_id, "btn_morning_11"), callback_data=f"offgp_on_{owner_id}_{gid}_{off_hour_bd}_11"),
            ],
            [InlineKeyboardButton(get_text(owner_id, "btn_back"), callback_data=f"offgp_grp_{owner_id}_{gid}")],
        ]
        await query.edit_message_text(
            get_text(owner_id, "schedule_set_on").format(title=g_title, off=format_schedule_time(owner_id, off_hour_bd)),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── offgp_on — সকালের সময় সিলেক্ট ───
    if cb.startswith("offgp_on_"):
        parts = cb.replace("offgp_on_", "").split("_")
        owner_id = int(parts[0])
        gid = int(parts[1])
        off_hour_bd = int(parts[2])
        on_hour_bd = int(parts[3])
        if user_id != owner_id:
            await query.answer(get_text(query.from_user.id, "not_your_group"), show_alert=True)
            return
        if owner_id not in user_group_schedule:
            user_group_schedule[owner_id] = {}
        user_group_schedule[owner_id][gid] = {
            "off_hour": off_hour_bd,
            "on_hour": on_hour_bd,
            "night_msg_id": None,
        }
        my_groups = get_user_groups(owner_id)
        g_title = my_groups.get(gid, str(gid))
        off_label = format_schedule_time(owner_id, off_hour_bd)
        on_label = format_schedule_time(owner_id, on_hour_bd)
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
        # NEW: Save to Supabase
        await upsert_user_lang(owner_id, lang)
        await query.edit_message_text(
            get_text(owner_id, "welcome"),
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
        title = my_groups.get(gid, str(gid))

        # কতক্ষণ পরে অন/অফ হবে হিসাব
        current_h = now_bd.hour
        current_m = now_bd.minute

        # off পর্যন্ত বাকি মিনিট
        off_total = off_h * 60
        on_total = on_h * 60
        now_total = current_h * 60 + current_m

        # রাত বন্ধ আছে কিনা চেক
        if off_h > on_h:
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
async def do_group_night_off(bot, group_id: int, on_hour_bd: int, user_id: int):
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

        on_label = format_schedule_time(user_id, on_hour_bd)
        sent = await bot.send_message(
            chat_id=group_id,
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
                f"তাই গ্রুপটি অফ 🔴\n"
                f"আবার {on_label} খোলা হবে। 🌅"
            )
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


# ============================================
# গ্রুপ অটো অন
# ============================================
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
        await bot.send_message(
            chat_id=group_id,
            text=(
                "🌅✨ 𝐆𝐨𝐨𝐝 𝐌𝐨𝐫𝐧𝐢𝐧𝐠 ✨🌅\n\n"
                "🎉 আমাদের গ্রুপটি খোলা হয়েছে!\n"
            )
        )
    except Exception as e:
        logging.error(f"Morning on error group {group_id}: {e}")


# ============================================
# শিডিউল চেকার
# ============================================
async def schedule_checker(context: ContextTypes.DEFAULT_TYPE):
    now_bd = datetime.now(BD_TZ)
    current_hour = now_bd.hour
    current_minute = now_bd.minute

    if current_minute != 0:
        return

    tasks = []
    for user_id, schedules in list(user_group_schedule.items()):
        for group_id, sdata in list(schedules.items()):
            off_h_utc = sdata.get("off_hour")
            on_h_utc = sdata.get("on_hour")
            if off_h_utc is None or on_h_utc is None:
                continue
            if current_hour == off_h_utc:
                tasks.append(do_group_night_off(context.bot, group_id, on_h_utc, user_id))
            elif current_hour == on_h_utc:
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
# send_broadcast_to_group — একটি গ্রুপে পাঠাও
# ============================================
async def send_broadcast_to_group(context: ContextTypes.DEFAULT_TYPE, user_id: int, group_id: int):
    from telegram import InputMediaPhoto, InputMediaVideo
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

        # Album
        if media_group:
            media_list = []
            for i, item in enumerate(media_group):
                caption_text = msg if i == 0 else None
                if item["type"] == "photo":
                    media_list.append(InputMediaPhoto(media=item["file_id"], caption=caption_text))
                else:
                    media_list.append(InputMediaVideo(media=item["file_id"], caption=caption_text))
            sent_list = await context.bot.send_media_group(chat_id=group_id, media=media_list)
            gdata["last_msg_id"] = [s.message_id for s in sent_list]

        # Single Photo
        elif photo:
            sent = await context.bot.send_photo(chat_id=group_id, photo=photo, caption=msg or None)
            gdata["last_msg_id"] = sent.message_id

        # Single Video
        elif video:
            sent = await context.bot.send_video(chat_id=group_id, video=video, caption=msg or None)
            gdata["last_msg_id"] = sent.message_id

        # Text
        else:
            sent = await context.bot.send_message(chat_id=group_id, text=msg)
            gdata["last_msg_id"] = sent.message_id

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
            if stopped and user_id not in notified:
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
                if not gdata.get("is_running") and has_content and gdata.get("interval"):
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
                    gdata["next_broadcast_time"] = datetime.now(timezone.utc).timestamp() + interval
                    context.application.job_queue.run_repeating(
                        broadcast_job,
                        interval=interval,
                        first=interval,
                        name=f"broadcast_{user_id}_{gid}",
                        data={"user_id": user_id, "group_id": gid}
                    )
                    restarted = True

            if restarted:
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

    if my_chat_member.chat.type not in ["group", "supergroup"]:
        return

    old_status = my_chat_member.old_chat_member.status
    new_status = my_chat_member.new_chat_member.status

    # ─── বট ADD হলে ───
    if old_status == "left" and new_status in ["member", "administrator"]:
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
        keyboard = [
    [
        InlineKeyboardButton("🌷 Support", url="https://t.me/teemxofficial"),
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

    keyboard = [
        [
            InlineKeyboardButton("✅ Next", callback_data=f"br_send_{OWNER_ID}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"br_cancel_{OWNER_ID}"),
        ]
    ]
    await update.message.reply_text(
        f"📢 ব্রডকাস্ট প্রিভিউ\n\n"
        f"{msg_text}\n\n"
        f"👥 মোট প্রাপক: {total} জন\n"
        f"পাঠাতে চাইলে Next চাপুন।",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


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

    if cb.startswith("br_send_"):
        owner_id = int(cb[len("br_send_"):])
        if query.from_user.id != owner_id:
            await query.answer("🚫", show_alert=True)
            return
        msg_text = br_pending.pop(owner_id, None)
        if not msg_text:
            await query.edit_message_text("⚠️ মেসেজ পাওয়া যায়নি। আবার চেষ্টা করুন।")
            return True

        await query.edit_message_text("📤 পাঠানো হচ্ছে...")

        all_users = set(all_bot_users)  # loop এ set বদলালে error হবে, তাই copy
        success = 0
        failed = []

        for uid in all_users:
            try:
                await context.bot.send_message(chat_id=uid, text=msg_text)
                success += 1
            except Exception as e:
                err_str = str(e).lower()
                if "forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str:
                    await _handle_user_blocked(context, uid)
                failed.append(uid)

        report = (
            f"📊 ব্রডকাস্ট রিপোর্ট\n\n"
            f"✅ সফল: {success} জন\n"
            f"❌ ব্যর্থ: {len(failed)} জন"
        )
        if failed:
            report += "\n\n❌ যায়নি:\n"
            for uid in failed:
                report += f"• {uid}\n"

        await context.bot.send_message(chat_id=owner_id, text=report)
        return True

    return False


# ============================================
# MAIN
# ============================================
async def post_init(application):
    # NEW: Load user_lang from Supabase
    await load_user_lang_from_supabase()
    await check_missed_schedules(application)
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
    current_hour = now_bd.hour

    tasks = []
    for user_id, schedules in list(user_group_schedule.items()):
        for group_id, sdata in list(schedules.items()):
            off_hour = sdata.get("off_hour")
            on_hour = sdata.get("on_hour")
            if off_hour is None or on_hour is None:
                continue

            # এখন গ্রুপ OFF থাকার কথা কিনা নির্ধারণ করো
            if off_hour < on_hour:
                should_be_off = off_hour <= current_hour < on_hour
            else:
                should_be_off = current_hour >= off_hour or current_hour < on_hour

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
                    tasks.append(do_group_night_off(application.bot, group_id, on_hour, user_id))
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


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Group only
    app.add_handler(CommandHandler("set", set_group, filters=filters.ChatType.GROUPS))
    # Private chat only
    app.add_handler(CommandHandler("set", set_command_private, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("br", br_command, filters=filters.ChatType.PRIVATE))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, setmsg_receive))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, setmsg_receive))
    app.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, setmsg_receive))
    app.add_handler(MessageHandler(filters.Document.VIDEO & filters.ChatType.PRIVATE, setmsg_receive))
    app.add_handler(ChatMemberHandler(handle_bot_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(button_callback))

    # প্রতি মিনিটে শিডিউল চেক
    app.job_queue.run_repeating(schedule_checker, interval=60, first=10)

    from datetime import time as dt_time
    # রাত ১১:০০ BD = ১৭:০০ UTC
    app.job_queue.run_daily(auto_broadcast_off, time=dt_time(16, 0, tzinfo=timezone.utc))
    # সকাল ১০:০০ BD = ০৪:০০ UTC
    app.job_queue.run_daily(auto_broadcast_on, time=dt_time(4, 0, tzinfo=timezone.utc))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()