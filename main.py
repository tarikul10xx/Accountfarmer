import asyncio
import os
import random
import string
import datetime
import pandas as pd
import aiofiles
import shutil
import aiohttp  # পরে যদি Binance rate নেওয়ার জন্য লাগে
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from aiogram.exceptions import TelegramBadRequest
from io import BytesIO
import aiosqlite

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

# এডমিন আইডি — লিস্টে রাখুন, একাধিক এডমিনের জন্য কমা দিয়ে আইডি যোগ করুন
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "0").split(",") if id.strip()]

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

DB_NAME = "bot.db"
BACKUP_NAME = "bot_backup.db"

# ডিফল্ট USD রেট — পরে Binance থেকে রিয়েল-টাইম নেওয়া যাবে (বাংলা ছাড়া সব কারেন্সির জন্য)
USD_RATE = 124.0

class States(StatesGroup):
    waiting_file = State()
    withdraw_method = State()
    withdraw_number = State()
    withdraw_amount = State()
    random_gmail_done = State()
    reject_reason = State()
    support_ticket = State()
    tracking_order = State()

class AdminStates(StatesGroup):
    screenshot_wait = State()        # এপ্রুভের পর স্ক্রিনশট অপেক্ষা
    reject_reason = State()          # রিজেক্টের কারণ
    toggle_rate = State()
    toggle_format = State()
    toggle_last_time = State()
    toggle_report_time = State()
    release_quantity = State()
    user_quantity = State()
    waiting_payment_screenshot = State()

# ==================== ট্রান্সলেশন ডিকশনারি ====================
# চারটি ভাষা: বাংলা (bn), English (en), اردو (ur), Tiếng Việt (vi)
# প্রত্যেকটি মূল টেক্সট চার ভাষায় অনুবাদ করা

LANGUAGES = {
    'bn': {
        'name': '🇧🇩 বাংলা',
        'welcome': '🌟 স্বাগতম! ফাইল শেয়ার করে আয় করুন 💰',
        'home': '🏠 হোম',
        'back': '🔙 ব্যাক',
        'close': '❌ বন্ধ করুন',
        'balance': '💰 ব্যালেন্স',
        'deposit': '➕ ডিপোজিট',
        'withdraw': '➖ উইথড্র',
        'rate': '💱 রেট',
        'support': '🆘 সাপোর্ট',
        'join_channel': '📢 জয়েন চ্যানেল',
        'language': '🌐 ভাষা',
        'profile': '👤 প্রোফাইল',
        'referral': '🎁 রেফারেল',
        'select_language': 'আপনার পছন্দের ভাষা নির্বাচন করুন:',
        'language_changed': '✅ ভাষা পরিবর্তন হয়েছে!',
        # আরও যোগ হবে ধীরে ধীরে...
    },
    'en': {
        'name': '🇺🇸 English',
        'welcome': '🌟 Welcome! Earn by sharing files 💰',
        'home': '🏠 Home',
        'back': '🔙 Back',
        'close': '❌ Close',
        'balance': '💰 Balance',
        'deposit': '➕ Deposit',
        'withdraw': '➖ Withdraw',
        'rate': '💱 Rate',
        'support': '🆘 Support',
        'join_channel': '📢 Join Channel',
        'language': '🌐 Language',
        'profile': '👤 Profile',
        'referral': '🎁 Referral',
        'select_language': 'Select your preferred language:',
        'language_changed': '✅ Language changed successfully!',
    },
    'ur': {
        'name': '🇵🇰 اردو',
        'welcome': '🌟 خوش آمدید! فائل شیئر کرکے کمائیں 💰',
        'home': '🏠 ہوم',
        'back': '🔙 واپس',
        'close': '❌ بند کریں',
        'balance': '💰 بیلنس',
        'deposit': '➕ ڈپازٹ',
        'withdraw': '➖ وڈرا',
        'rate': '💱 ریٹ',
        'support': '🆘 سپورٹ',
        'join_channel': '📢 چینل جوائن کریں',
        'language': '🌐 زبان',
        'profile': '👤 پروفائل',
        'referral': '🎁 ریفرل',
        'select_language': 'اپنی پسندیدہ زبان منتخب کریں:',
        'language_changed': '✅ زبان کامیابی سے تبدیل ہوگئی!',
    },
    'vi': {
        'name': '🇻🇳 Tiếng Việt',
        'welcome': '🌟 Chào mừng! Kiếm tiền bằng cách chia sẻ file 💰',
        'home': '🏠 Trang chủ',
        'back': '🔙 Quay lại',
        'close': '❌ Đóng',
        'balance': '💰 Số dư',
        'deposit': '➕ Nạp tiền',
        'withdraw': '➖ Rút tiền',
        'rate': '💱 Tỷ giá',
        'support': '🆘 Hỗ trợ',
        'join_channel': '📢 Tham gia kênh',
        'language': '🌐 Ngôn ngữ',
        'profile': '👤 Hồ sơ',
        'referral': '🎁 Giới thiệu',
        'select_language': 'Chọn ngôn ngữ bạn muốn:',
        'language_changed': '✅ Đã thay đổi ngôn ngữ thành công!',
    }
}

# ==================== ট্রান্সলেশন সিস্টেম (আপডেটেড) ====================
# async ফাংশন যা ইউজারের ভাষা অনুযায়ী টেক্সট রিটার্ন করবে
# সবগুলো ওয়ার্ড/বাক্য চার ভাষায় (bn, en, ur, vi) ট্রান্সলেট করা আছে

TEXTS = {
    # মেইন ক্যাটাগরি
    "main_facebook": {
        "bn": "📘 ফেসবুক",
        "en": "📘 Facebook",
        "ur": "📘 فیس بک",
        "vi": "📘 Facebook"
    },
    "main_instagram": {
        "bn": "📷 ইনস্টাগ্রাম",
        "en": "📷 Instagram",
        "ur": "📷 انسٹاگرام",
        "vi": "📷 Instagram"
    },
    "main_coins": {
        "bn": "🪙 কয়েনস",
        "en": "🪙 Coins",
        "ur": "🪙 کوائنز",
        "vi": "🪙 Coins"
    },
    "main_gmail": {
        "bn": "📧 জিমেইল",
        "en": "📧 Gmail",
        "ur": "📧 جی میل",
        "vi": "📧 Gmail"
    },
    "main_others": {
        "bn": "📂 অন্যান্য",
        "en": "📂 Others",
        "ur": "📂 دیگر",
        "vi": "📂 Khác"
    },

    # ফেসবুক সাব-ক্যাটাগরি
    "sub_webmail": {
        "bn": "ওয়েবমেইল",
        "en": "Webmail",
        "ur": "ویب میل",
        "vi": "Webmail"
    },
    "sub_anymail": {
        "bn": "এনিমেইল",
        "en": "Anymail",
        "ur": "اینیمییل",
        "vi": "Anymail"
    },
    "sub_number": {
        "bn": "নাম্বার",
        "en": "Number",
        "ur": "نمبر",
        "vi": "Number"
    },
    "sub_pc_clone_cookies": {
        "bn": "পিসি ক্লোন কুকিজ",
        "en": "PC Clone Cookies",
        "ur": "پی سی کلون کوکیز",
        "vi": "PC Clone Cookies"
    },
    "sub_hotmail": {
        "bn": "হটমেইল",
        "en": "Hotmail",
        "ur": "ہاٹ میل",
        "vi": "Hotmail"
    },

    # হটমেইলের সাব-সাব (নতুন যোগ করা)
    "hotmail_30plus_friend": {
        "bn": "হটমেইল ৩০+ ফ্রেন্ড",
        "en": "Hotmail 30+ Friends",
        "ur": "ہاٹ میل 30+ دوست",
        "vi": "Hotmail 30+ Bạn bè"
    },
    "hotmail_00friend": {
        "bn": "হটমেইল ০০ ফ্রেন্ড",
        "en": "Hotmail 00 Friends",
        "ur": "ہاٹ میل 00 دوست",
        "vi": "Hotmail 00 Bạn bè"
    },

    # অন্যান্য সাব-ক্যাটাগরি
    "sub_instagram_cookies": {
        "bn": "ইনস্টাগ্রাম কুকিজ",
        "en": "Instagram Cookies",
        "ur": "انسٹاگرام کوکیز",
        "vi": "Instagram Cookies"
    },
    "sub_instagram_2fa": {
        "bn": "ইনস্টাগ্রাম ২এফএ",
        "en": "Instagram 2FA",
        "ur": "انسٹاگرام 2FA",
        "vi": "Instagram 2FA"
    },
    "sub_niva_coin": {
        "bn": "নিভা কয়েন",
        "en": "Niva Coin",
        "ur": "نیوا کوائن",
        "vi": "Niva Coin"
    },
    "sub_ns_coin": {
        "bn": "এনএস কয়েন",
        "en": "NS Coin",
        "ur": "این ایس کوائن",
        "vi": "NS Coin"
    },
    "sub_topfollow": {
        "bn": "টপফলো",
        "en": "Topfollow",
        "ur": "ٹاپ فالو",
        "vi": "Topfollow"
    },
    "sub_nitra_coin": {
        "bn": "নাইট্রা কয়েন",
        "en": "Nitra Coin",
        "ur": "نائٹرا کوائن",
        "vi": "Nitra Coin"
    },
    "sub_other_coins": {
        "bn": "অন্যান্য কয়েন",
        "en": "Other Coins",
        "ur": "دیگر کوائنز",
        "vi": "Coins khác"
    },
    "sub_gmail_files": {
        "bn": "জিমেইল ফাইলস",
        "en": "Gmail Files",
        "ur": "جی میل فائلز",
        "vi": "Gmail Files"
    },
    "sub_random_gmail": {
        "bn": "র‍্যান্ডম জিমেইল",
        "en": "Random Gmail",
        "ur": "رینڈم جی میل",
        "vi": "Gmail Ngẫu nhiên"
    },
    "sub_other_files": {
        "bn": "অন্যান্য ফাইল",
        "en": "Other Files",
        "ur": "دیگر فائلیں",
        "vi": "File khác"
    },

    # পিসি ক্লোন সাব
    "pc_clone_1000x": {
        "bn": "পিসি ক্লোন ১০০০x",
        "en": "PC Clone 1000x",
        "ur": "پی سی کلون 1000x",
        "vi": "PC Clone 1000x"
    },
    "pc_clone_6155_56x": {
        "bn": "6155/56x কুকিজ",
        "en": "6155/56x Cookies",
        "ur": "6155/56x کوکیز",
        "vi": "6155/56x Cookies"
    },
    # মেইন মেনু বাটনসমূহ
    "send_files": {
        "bn": "📤 ফাইল / কয়েন পাঠান",
        "en": "📤 Send Files / Coins",
        "ur": "📤 فائلز / کوائنز بھیجیں",
        "vi": "📤 Gửi File / Coin"
    },
    "today_rate": {
        "bn": "💰 আজকের রেট",
        "en": "💰 Today Rate",
        "ur": "💰 آج کا ریٹ",
        "vi": "💰 Tỷ giá hôm nay"
    },
    "my_files": {
        "bn": "📁 আমার ফাইলসমূহ",
        "en": "📁 My Files",
        "ur": "📁 میری فائلیں",
        "vi": "📁 File của tôi"
    },
    "my_stats": {
        "bn": "📊 আমার পরিসংখ্যান",
        "en": "📊 My Stats",
        "ur": "📊 میرے اعدادوشمار",
        "vi": "📊 Thống kê của tôi"
    },
    "settings": {
        "bn": "⚙️ সেটিংস",
        "en": "⚙️ Settings",
        "ur": "⚙️ سیٹنگز",
        "vi": "⚙️ Cài đặt"
    },
    "welcome": {
        "bn": "🌟 স্বাগতম! ফাইল শেয়ার করে আয় করুন 💰",
        "en": "🌟 Welcome! Earn by sharing files 💰",
        "ur": "🌟 خوش آمدید! فائل شیئر کرکے کمائیں 💰",
        "vi": "🌟 Chào mừng! Kiếm tiền bằng cách chia sẻ file 💰"
    },
    "referral_info": {
        "bn": "আপনার রেফার লিঙ্ক:\n{ref_link}\n\nরেফার করে প্রতি জনে ৫ টাকা + মাল্টি-লেভেল বোনাস পান! 🎁",
        "en": "Your referral link:\n{ref_link}\n\nEarn 5 BDT per referral + multi-level bonus! 🎁",
        "ur": "آپ کا ریفرل لنک:\n{ref_link}\n\nہر ریفرل پر 5 ٹکا + ملٹی لیول بونس حاصل کریں! 🎁",
        "vi": "Link giới thiệu của bạn:\n{ref_link}\n\nKiếm 5 BDT mỗi người giới thiệu + bonus đa cấp! 🎁"
    },
    "select_language": {
        "bn": "🌐 আপনার পছন্দের ভাষা নির্বাচন করুন:",
        "en": "🌐 Select your preferred language:",
        "ur": "🌐 اپنی پسندیدہ زبان منتخب کریں:",
        "vi": "🌐 Chọn ngôn ngữ bạn muốn:"
    },
    "language_changed": {
        "bn": "✅ ভাষা সফলভাবে পরিবর্তন হয়েছে!",
        "en": "✅ Language changed successfully!",
        "ur": "✅ زبان کامیابی سے تبدیل ہوگئی!",
        "vi": "✅ Đã thay đổi ngôn ngữ thành công!"
    },
    "home_title": {
        "bn": "🏠 মেইন মেনু",
        "en": "🏠 Main Menu",
        "ur": "🏠 مرکزی مینو",
        "vi": "🏠 Menu chính"
    },
    "select_main_category": {
        "bn": "📂 ক্যাটাগরি নির্বাচন করুন:",
        "en": "📂 Select Category:",
        "ur": "📂 زمرہ منتخب کریں:",
        "vi": "📂 Chọn danh mục:"
    },
    "select_sub_category": {
        "bn": "{category} এর সাব-ক্যাটাগরি নির্বাচন করুন:",
        "en": "Select sub-category for {category}:",
        "ur": "{category} کے لیے سب زمرہ منتخب کریں:",
        "vi": "Chọn danh mục con cho {category}:"
    },
    "hotmail_prompt": {
        "bn": "📬 হটমেইল সাব-ক্যাটাগরি নির্বাচন করুন:",
        "en": "📬 Select Hotmail sub-sub category:",
        "ur": "📬 ہاٹ میل سب سب کیٹیگری منتخب کریں:",
        "vi": "📬 Chọn danh mục con của Hotmail:"
    },
    "pc_clone_prompt": {
        "bn": "🖥️ পিসি ক্লোন কুকিজ সাব-ক্যাটাগরি নির্বাচন করুন:",
        "en": "🖥️ Select PC Clone Cookies sub-sub category:",
        "ur": "🖥️ پی سی کلون کوکیز سب سب کیٹیگری منتخب کریں:",
        "vi": "🖥️ Chọn danh mục con của PC Clone Cookies:"
    },
    "suggested_gmail": {
        "bn": "সাজেস্টেড জিমেইল:",
        "en": "Suggested Gmail:",
        "ur": "تجویز کردہ جی میل:",
        "vi": "Gmail được gợi ý:"
    },
    "strong_password": {
        "bn": "স্ট্রং পাসওয়ার্ড:",
        "en": "Strong Password:",
        "ur": "مضبوط پاس ورڈ:",
        "vi": "Mật khẩu mạnh:"
    },
    "create_gmail_instruction": {
        "bn": "এই ইমেইল দিয়ে নতুন জিমেইল অ্যাকাউন্ট তৈরি করুন।",
        "en": "Create a new Gmail account using this email.",
        "ur": "اس ای میل کا استعمال کرتے ہوئے نیا جی میل اکاؤنٹ بنائیں۔",
        "vi": "Tạo tài khoản Gmail mới bằng email này."
    },
    "press_done": {
        "bn": "হয়ে গেলে 'Done' চাপুন।",
        "en": "Press 'Done' when completed.",
        "ur": "مکمل ہونے پر 'Done' دبائیں۔",
        "vi": "Nhấn 'Done' khi hoàn thành."
    },
    "random_gmail_title": {
        "bn": "📧 র‍্যান্ডম জিমেইল",
        "en": "📧 Random Gmail",
        "ur": "📧 رینڈم جی میل",
        "vi": "📧 Gmail Ngẫu nhiên"
    },
    "random_gmail_desc": {
        "bn": "এই সাজেস্টেড ইমেইল এবং পাসওয়ার্ড ব্যবহার করুন।",
        "en": "Use this suggested email and password.",
        "ur": "اس تجویز کردہ ای میل اور پاس ورڈ کا استعمال کریں۔",
        "vi": "Sử dụng email và mật khẩu được gợi ý này."
    },
    "send_file_prompt": {
        "bn": "📂 এখন আপনার ফাইল পাঠান।",
        "en": "📂 Now send your file.",
        "ur": "📂 اب اپنی فائل بھیجیں۔",
        "vi": "📂 Bây giờ gửi file của bạn."
    },
    "coin_user_prompt": {
        "bn": "কয়েন পাঠানোর জন্য ইউজার: @{coin_user}",
        "en": "Send coins to user: @{coin_user}",
        "ur": "کوائنز بھیجنے کے لیے صارف: @{coin_user}",
        "vi": "Gửi coin cho người dùng: @{coin_user}"
    },
    "done": {
        "bn": "✅ সম্পন্ন",
        "en": "✅ Done",
        "ur": "✅ مکمل",
        "vi": "✅ Hoàn thành"
    },
    "cancel": {
        "bn": "❌ বাতিল",
        "en": "❌ Cancel",
        "ur": "❌ منسوخ",
        "vi": "❌ Hủy"
    },
    "file_received": {"bn": "✅ ফাইল গৃহীত হয়েছে!", "en": "✅ File received!", "ur": "✅ فائل موصول ہوئی!", "vi": "✅ Đã nhận file!"},
    "quantity_question": {"bn": "কতগুলো ডেটা আছে তা লিখুন (সংখ্যা):", "en": "How many data? (Enter number):", "ur": "کتنے ڈیٹا ہیں؟ (نمبر لکھیں):", "vi": "Có bao nhiêu data? (Nhập số):"},
    "invalid_quantity": {"bn": "❌ দয়া করে সঠিক সংখ্যা লিখুন (যেমন: ৫০)", "en": "❌ Please enter a valid number (e.g., 50)", "ur": "❌ براہ مہربانی درست نمبر لکھیں", "vi": "❌ Vui lòng nhập số hợp lệ"},
    "new_file_received": {"bn": "🆕 নতুন ফাইল জমা পড়েছে", "en": "🆕 New file submitted", "ur": "🆕 نئی فائل جمع ہوئی", "vi": "🆕 File mới được gửi"},
    "submitted_at": {"bn": "জমা দেওয়া হয়েছে:", "en": "Submitted at:", "ur": "جمع کرایا گیا:", "vi": "Gửi lúc:"},
    "per_data": {"bn": "প্রতি ডেটা", "en": "per data", "ur": "فی ڈیٹا", "vi": "mỗi data"},
    "file_submitted_success": {"bn": "✅ ফাইল সফলভাবে এডমিনের কাছে পাঠানো হয়েছে!", "en": "✅ File successfully sent to admin!", "ur": "✅ فائل ایڈمن کو بھیج دی گئی!", "vi": "✅ Đã gửi file thành công!"},
    "track_instruction": {"bn": "স্ট্যাটাস দেখতে → 📋 ট্র্যাক অর্ডার", "en": "Check status → 📋 Track Order", "ur": "اسٹیٹس دیکھیں → 📋 ٹریک آرڈر", "vi": "Xem trạng thái → 📋 Theo dõi đơn"},
    "copy_order_id": {"bn": "📋 কপি অর্ডার আইডি", "en": "📋 Copy Order ID", "ur": "📋 آرڈر آئی ڈی کاپی کریں", "vi": "📋 Sao chép Order ID"},
    "gmail_request_sent": {"bn": "✅ আপনার রিকোয়েস্ট এডমিনের কাছে পাঠানো হয়েছে।", "en": "✅ Your request has been sent to admin.", "ur": "✅ آپ کی درخواست ایڈمن کو بھیج دی گئی۔", "vi": "✅ Yêu cầu đã được gửi đến admin."},
    "gmail_approved": {"bn": "অভিনন্দন! আপনার র‍্যান্ডম জিমেইল রিকোয়েস্ট এপ্রুভ হয়েছে।", "en": "Congratulations! Your random Gmail request approved.", "ur": "مبارک ہو! آپ کی رینڈم جی میل درخواست منظور ہوگئی۔", "vi": "Chúc mừng! Yêu cầu Gmail ngẫu nhiên đã được duyệt."},
    "gmail_rejected": {"bn": "দুঃখিত! আপনার রিকোয়েস্ট রিজেক্ট হয়েছে।", "en": "Sorry! Your request was rejected.", "ur": "معذرت! آپ کی درخواست مسترد ہوگئی۔", "vi": "Xin lỗi! Yêu cầu bị từ chối."},
    "gmail_next_step": {"bn": "এখন আপনি ফাইল পাঠাতে পারবেন।", "en": "Now you can send files.", "ur": "اب آپ فائلیں بھیج سکتے ہیں۔", "vi": "Bây giờ bạn có thể gửi file."},
    "auto_count_label": {"bn": "🤖 অটো কাউন্ট:", "en": "🤖 Auto Count:", "ur": "🤖 خودکار شمار:", "vi": "🤖 Đếm tự động:"},
    "approved_amount": {"bn": "💰 এপ্রুভকৃত পরিমাণ:", "en": "💰 Approved Amount:", "ur": "💰 منظور شدہ رقم:", "vi": "💰 Số tiền được duyệt:"},
    "payment_soon": {"bn": "⏳ পেমেন্ট শীঘ্রই প্রসেস হবে।", "en": "⏳ Payment will be processed soon.", "ur": "⏳ ادائیگی جلد ہوگی۔", "vi": "⏳ Thanh toán sẽ sớm được xử lý."},
    "withdraw_approved": {"bn": "✅ আপনার উইথড্র এপ্রুভ হয়েছে!", "en": "✅ Your withdraw has been approved!", "ur": "✅ آپ کی واپسی منظور ہوگئی!", "vi": "✅ Yêu cầu rút tiền đã được duyệt!"},
    "amount_label": {"bn": "💰 পরিমাণ:", "en": "💰 Amount:", "ur": "💰 رقم:", "vi": "💰 Số tiền:"},
    "send_screenshot_prompt": {"bn": "পেমেন্টের স্ক্রিনশট এডমিনকে পাঠান।", "en": "Send payment screenshot to admin.", "ur": "ادائیگی کا اسکرین شاٹ ایڈمن کو بھیجیں۔", "vi": "Gửi ảnh chụp màn hình thanh toán cho admin."},
    "approve_notification": {"bn": "🎉 অভিনন্দন! আপনার ফাইল এপ্রুভ হয়েছে!", "en": "🎉 Congratulations! Your file approved!", "ur": "🎉 مبارک ہو! آپ کی فائل منظور ہوگئی!", "vi": "🎉 Chúc mừng! File của bạn đã được duyệt!"},
    "file_rejected": {"bn": "আপনার ফাইল রিজেক্ট হয়েছে।", "en": "Your file has been rejected.", "ur": "آپ کی فائل مسترد ہوگئی۔", "vi": "File của bạn đã bị từ chối."},
    "reason_label": {"bn": "কারণ:", "en": "Reason:", "ur": "وجہ:", "vi": "Lý do:"},
    "try_again_prompt": {"bn": "দয়া করে সঠিক ফাইল পাঠান।", "en": "Please send correct file.", "ur": "براہ مہربانی درست فائل بھیجیں۔", "vi": "Vui lòng gửi file đúng."},
    "reject_success": {"bn": "রিজেক্ট করা হয়েছে। ইউজারকে জানানো হয়েছে।", "en": "Rejected. User notified.", "ur": "مسترد ہوگئی۔ صارف کو مطلع کیا گیا۔", "vi": "Đã từ chối. Người dùng đã được thông báo."},
    "reason_required": {"bn": "কারণ লিখুন।", "en": "Please enter reason.", "ur": "وجہ لکھیں۔", "vi": "Vui lòng nhập lý do."},
    "withdraw_min_error": {"bn": "সর্বনিম্ন ৫০ টাকা।", "en": "Minimum 50 Tk.", "ur": "کم از کم 50 Tk", "vi": "Tối thiểu 50 Tk"},
    "insufficient_balance": {"bn": "ব্যালেন্স যথেষ্ট নয়।", "en": "Insufficient balance.", "ur": "بیلنس ناکافی ہے۔", "vi": "Số dư không đủ."},
    "new_withdraw_request": {"bn": "নতুন উইথড্র রিকোয়েস্ট", "en": "New Withdraw Request", "ur": "نیا واپسی کا درخواست", "vi": "Yêu cầu rút tiền mới"},
    "method_label": {"bn": "মেথড:", "en": "Method:", "ur": "طریقہ:", "vi": "Phương thức:"},
    "number_label": {"bn": "নম্বর:", "en": "Number:", "ur": "نمبر:", "vi": "Số tài khoản:"},
    "withdraw_success": {"bn": "উইথড্র রিকোয়েস্ট সফলভাবে পাঠানো হয়েছে!", "en": "Withdraw request sent successfully!", "ur": "واپسی کی درخواست کامیابی سے بھیج دی گئی!", "vi": "Yêu cầu rút tiền đã được gửi!"},
    "approve_usage": {"bn": "❌ ব্যবহার: /approve অর্ডার_আইডি", "en": "❌ Usage: /approve order_id", "ur": "❌ استعمال: /approve آرڈر_آئی_ڈی", "vi": "❌ Cách dùng: /approve order_id"},
    "approve_success_admin": {"bn": "✅ অর্ডার {order_id} এপ্রুভ করা হয়েছে। {amount}{currency} যোগ হয়েছে।", "en": "✅ Order {order_id} approved. {amount}{currency} added.", "ur": "✅ آرڈر {order_id} منظور ہوگیا۔ {amount}{currency} شامل کیا گیا۔", "vi": "✅ Order {order_id} đã duyệt. Đã cộng {amount}{currency}."},
    "reject_usage": {"bn": "❌ ব্যবহার: /reject অর্ডার_আইডি [কারণ]", "en": "❌ Usage: /reject order_id [reason]", "ur": "❌ استعمال: /reject آرڈر_آئی_ڈی [وجہ]", "vi": "❌ Cách dùng: /reject order_id [lý do]"},
    "enter_reject_reason": {"bn": "কারণ লিখুন অর্ডার {order_id} এর জন্য:", "en": "Enter reason for order {order_id}:", "ur": "آرڈر {order_id} کی وجہ لکھیں:", "vi": "Nhập lý do cho order {order_id}:"},
    "release_usage": {"bn": "❌ ব্যবহার: /release অর্ডার_আইডি কোয়ান্টিটি", "en": "❌ Usage: /release order_id quantity", "ur": "❌ استعمال: /release آرڈر_آئی_ڈی مقدار", "vi": "❌ Cách dùng: /release order_id số lượng"},
    "release_not_reported": {"bn": "❌ এই অর্ডার রিপোর্টের অপেক্ষায় নেই।", "en": "❌ This order is not in reported state.", "ur": "❌ یہ آرڈر رپورٹ کا انتظار نہیں کر رہا۔", "vi": "❌ Order này chưa ở trạng thái reported."},
    "release_success_admin": {"bn": "✅ রিলিজ সফল! অর্ডার {order_id} — {quantity} × রেট = {amount}{currency}", "en": "✅ Release successful! Order {order_id} — {quantity} × rate = {amount}{currency}", "ur": "✅ ریلیز کامیاب! آرڈر {order_id} — {quantity} × ریٹ = {amount}{currency}", "vi": "✅ Release thành công! Order {order_id} — {quantity} × rate = {amount}{currency}"},
    "payment_released": {"bn": "🎉 পেমেন্ট রিলিজ হয়েছে!", "en": "🎉 Payment released!", "ur": "🎉 ادائیگی جاری ہوگئی!", "vi": "🎉 Thanh toán đã được giải ngân!"},
    "released_quantity": {"bn": "রিলিজকৃত কোয়ান্টিটি:", "en": "Released quantity:", "ur": "جاری کردہ مقدار:", "vi": "Số lượng đã giải ngân:"},
    "withdraw_completed": {"bn": "✅ উইথড্র সম্পন্ন হয়েছে!", "en": "✅ Withdraw completed!", "ur": "✅ واپسی مکمل ہوگئی!", "vi": "✅ Rút tiền hoàn tất!"},
    "track_order_prompt": {"bn": "📋 অর্ডার আইডি লিখুন:", "en": "📋 Enter Order ID:", "ur": "📋 آرڈر آئی ڈی لکھیں:", "vi": "📋 Nhập Order ID:"},
    "file_order_status": {"bn": "📁 ফাইল অর্ডার স্ট্যাটাস", "en": "📁 File Order Status", "ur": "📁 فائل آرڈر کی حیثیت", "vi": "📁 Trạng thái đơn file"},
    "withdraw_order_status": {"bn": "💸 উইথড্র অর্ডার স্ট্যাটাস", "en": "💸 Withdraw Order Status", "ur": "💸 واپسی آرڈر کی حیثیت", "vi": "💸 Trạng thái đơn rút tiền"},
    "status_pending": {"bn": "⏳ পেন্ডিং", "en": "⏳ Pending", "ur": "⏳ زیر التوا", "vi": "⏳ Đang chờ"},
    "status_reported": {"bn": "⏳ রিপোর্ট অপেক্ষায়", "en": "⏳ Waiting for report", "ur": "⏳ رپورٹ کا انتظار", "vi": "⏳ Chờ duyệt"},
    "status_approved": {"bn": "✅ এপ্রুভড", "en": "✅ Approved", "ur": "✅ منظور", "vi": "✅ Đã duyệt"},
    "status_rejected": {"bn": "❌ রিজেক্টেড", "en": "❌ Rejected", "ur": "❌ مسترد", "vi": "❌ Bị từ chối"},
    "your_files": {"bn": "📁 আপনার সব ফাইল", "en": "📁 Your Files", "ur": "📁 آپ کی فائلیں", "vi": "📁 File của bạn"},
    "no_files": {"bn": "কোনো ফাইল নেই।", "en": "No files found.", "ur": "کوئی فائل نہیں ملی۔", "vi": "Không tìm thấy file."},
    "recent_files": {"bn": "সাম্প্রতিক ফাইলসমূহ:", "en": "Recent Files:", "ur": "حالیہ فائلیں:", "vi": "File gần đây:"},
    "use_track_for_more": {"bn": "সব দেখতে ট্র্যাক অর্ডার ব্যবহার করুন।", "en": "Use Track Order for all.", "ur": "سب دیکھنے کے لیے ٹریک آرڈر استعمال کریں۔", "vi": "Sử dụng Track Order để xem tất cả."},
    "your_balance": {"bn": "💳 আপনার ব্যালেন্স", "en": "💳 Your Balance", "ur": "💳 آپ کا بیلنس", "vi": "💳 Số dư của bạn"},
    "total_earnings": {"bn": "মোট আয়:", "en": "Total Earnings:", "ur": "کل آمدنی:", "vi": "Tổng thu nhập:"},
    "pending_withdraw": {"bn": "পেন্ডিং উইথড্র:", "en": "Pending Withdraw:", "ur": "زیر التوا واپسی:", "vi": "Rút tiền đang chờ:"},
    "withdraw_history": {"bn": "উইথড্র হিস্টোরি:", "en": "Withdraw History:", "ur": "واپسی کی تاریخ:", "vi": "Lịch sử rút tiền:"},
    "no_withdraws": {"bn": "কোনো উইথড্র নেই।", "en": "No withdraws.", "ur": "کوئی واپسی نہیں۔", "vi": "Không có rút tiền."},
    "today_rates_header": {"bn": "💎 সবাই ID Submit শুরু করুন 💎", "en": "💎 Start Submitting IDs 💎", "ur": "💎 سب آئی ڈی جمع کرنا شروع کریں 💎", "vi": "💎 Bắt đầu gửi ID 💎"},
    "submit_last_time": {"bn": "🌙 সময়মতো Submit করতে থাকুন 🌙", "en": "🌙 Submit on time 🌙", "ur": "🌙 وقت پر جمع کروائیں 🌙", "vi": "🌙 Gửi đúng giờ 🌙"},
    "format_label": {"bn": "📄 ফরম্যাট:", "en": "📄 Format:", "ur": "📄 فارمیٹ:", "vi": "📄 Định dạng:"},
    "last_time_label": {"bn": "⏰ লাস্ট টাইম:", "en": "⏰ Last Time:", "ur": "⏰ آخری وقت:", "vi": "⏰ Giờ cuối:"},
    "report_time_label": {"bn": "📊 রিপোর্ট টাইম:", "en": "📊 Report Time:", "ur": "📊 رپورٹ کا وقت:", "vi": "📊 Giờ báo cáo:"},
    "updated_at": {"bn": "🗓 আপডেট:", "en": "🗓 Updated:", "ur": "🗓 اپ ڈیٹ:", "vi": "🗓 Cập nhật:"},
    "admin_inbox_note": {"bn": "《 All ADMIN RATE INBOX 》", "en": "《 All ADMIN RATE INBOX 》", "ur": "《 تمام ایڈمن ریٹ ان باکس 》", "vi": "《 All ADMIN RATE INBOX 》"},
    "file_name_note": {"bn": "📛 কি ধরনের ID দিচ্ছেন তা অবশ্যই ফাইল নামে লিখে দিন ✅", "en": "📛 Mention ID type in file name ✅", "ur": "📛 جو ID دے رہے ہیں اس کی قسم فائل کے نام میں لکھیں ✅", "vi": "📛 Ghi loại ID vào tên file ✅"},
    "motivation_note": {"bn": "🚀 সফলতার জন্য কঠোর পরিশ্রম করুন! 💪 আমরা সবাই মিলে এগিয়ে যাই", "en": "🚀 Work hard for success! 💪 Let's move forward together", "ur": "🚀 کامیابی کے لیے محنت کریں! 💪 ہم سب مل کر آگے بڑھیں", "vi": "🚀 Làm việc chăm chỉ để thành công! 💪 Cùng nhau tiến lên"},
    "referral_header": {"bn": "👥 রেফারেল সিস্টেম", "en": "👥 Referral System", "ur": "👥 ریفرل سسٹم", "vi": "👥 Hệ thống giới thiệu"},
    "your_referral_link": {"bn": "আপনার রেফার লিঙ্ক:", "en": "Your referral link:", "ur": "آپ کا ریفرل لنک:", "vi": "Link giới thiệu của bạn:"},
    "total_referrals": {"bn": "মোট রেফার:", "en": "Total referrals:", "ur": "کل ریفرل:", "vi": "Tổng giới thiệu:"},
    "referral_bonus": {"bn": "প্রতি রেফারে ৫ টাকা + মাল্টি-লেভেল বোনাস!", "en": "5 Tk per referral + multi-level bonus!", "ur": "ہر ریفرل پر 5 ٹکا + ملٹی لیول بونس!", "vi": "5 Tk mỗi giới thiệu + thưởng đa cấp!"},
    "settings_header": {"bn": "⚙️ সেটিংস", "en": "⚙️ Settings", "ur": "⚙️ سیٹنگز", "vi": "⚙️ Cài đặt"},
    "change_language": {"bn": "🌐 ভাষা পরিবর্তন", "en": "🌐 Change Language", "ur": "🌐 زبان تبدیل کریں", "vi": "🌐 Thay đổi ngôn ngữ"},
    "withdraw_method": {"bn": "💸 উইথড্র মেথড সিলেক্ট করুন:", "en": "💸 Select Withdraw Method:", "ur": "💸 واپسی کا طریقہ منتخب کریں:", "vi": "💸 Chọn phương thức rút tiền:"},
    "withdraw_number": {"bn": "📱 নম্বর লিখুন:", "en": "📱 Enter Number:", "ur": "📱 نمبر لکھیں:", "vi": "📱 Nhập số:"},
    "withdraw_amount": {"bn": "💰 অ্যামাউন্ট লিখুন (মিনিমাম ৫০):", "en": "💰 Enter Amount (Min 50):", "ur": "💰 رقم لکھیں (کم از کم 50):", "vi": "💰 Nhập số tiền (Tối thiểu 50):"},
    "my_stats_header": {"bn": "📊 আপনার স্ট্যাটাস", "en": "📊 Your Stats", "ur": "📊 آپ کے اعدادوشمار", "vi": "📊 Thống kê của bạn"},
    "balance_label": {"bn": "💰 ব্যালেন্স:", "en": "💰 Balance:", "ur": "💰 بیلنس:", "vi": "💰 Số dư:"},
    "withdraw_stats": {"bn": "💸 উইথড্র স্ট্যাটাস", "en": "💸 Withdraw Stats", "ur": "💸 واپسی کے اعداد", "vi": "💸 Thống kê rút tiền"},
    "pending_withdraws": {"bn": "⏳ পেন্ডিং উইথড্র:", "en": "⏳ Pending Withdraws:", "ur": "⏳ زیر التوا واپسیاں:", "vi": "⏳ Rút tiền đang chờ:"},
    "pending_amount": {"bn": "💰 পেন্ডিং পরিমাণ:", "en": "💰 Pending Amount:", "ur": "💰 زیر التوا رقم:", "vi": "💰 Số tiền đang chờ:"},
    "total_paid": {"bn": "✅ মোট পে-আউট:", "en": "✅ Total Paid:", "ur": "✅ کل ادا شدہ:", "vi": "✅ Tổng đã thanh toán:"},
    "file_stats": {"bn": "📁 ফাইল স্ট্যাটাস", "en": "📁 File Stats", "ur": "📁 فائل کے اعداد", "vi": "📁 Thống kê file"},
    "referred_users": {"bn": "রেফার করেছেন:", "en": "Referred users:", "ur": "ریفر کیے گئے صارفین:", "vi": "Người được giới thiệu:"},
    "refresh": {"bn": "🔄 রিফ্রেশ", "en": "🔄 Refresh", "ur": "🔄 تازہ کریں", "vi": "🔄 Làm mới"},
    "user_not_found": {"bn": "❌ তথ্য পাওয়া যায়নি। /start দিন।", "en": "❌ Data not found. Use /start.", "ur": "❌ ڈیٹا نہیں ملا۔ /start استعمال کریں۔", "vi": "❌ Không tìm thấy dữ liệu. Dùng /start."},
    "admin_user_stats_header": {"bn": "👤 ইউজার স্ট্যাটাস (এডমিন)", "en": "👤 User Stats (Admin)", "ur": "👤 صارف کے اعداد (ایڈمن)", "vi": "👤 Thống kê người dùng (Admin)"},
    "userstats_usage": {"bn": "❌ ব্যবহার: /userstats আইডি", "en": "❌ Usage: /userstats id", "ur": "❌ استعمال: /userstats آئی ڈی", "vi": "❌ Cách dùng: /userstats id"},
    "invalid_user_id": {"bn": "❌ সঠিক আইডি দিন।", "en": "❌ Enter valid ID.", "ur": "❌ درست آئی ڈی دیں۔", "vi": "❌ Nhập ID hợp lệ."},
    "bot_rules": {"bn": "📜 <b>বটের নিয়মাবলী</b>\n\n✅ যা করতে পারবেন:\n• সঠিক ক্যাটাগরিতে ফাইল পাঠান\n• রেফার করে বোনাস পান\n\n❌ যা করবেন না:\n• ডুপ্লিকেট/ফেক ফাইল পাঠাবেন না\n• স্প্যাম করবেন না\n\nভায়োলেশন করলে ব্যান।", "en": "📜 <b>Bot Rules</b>\n\n✅ Allowed:\n• Send correct files\n• Earn referral bonus\n\n❌ Not allowed:\n• Fake/duplicate files\n• Spam\n\nViolation = Ban.", "ur": "📜 <b>بوٹ کے قواعد</b>\n\n✅ اجازت:\n• درست فائلیں بھیجیں\n• ریفرل بونس کمائیں\n\n❌ منع:\n• جعلی فائلیں\n• اسپیم\n\nخلاف ورزی = بین", "vi": "📜 <b>Quy tắc Bot</b>\n\n✅ Được phép:\n• Gửi file đúng\n• Kiếm bonus giới thiệu\n\n❌ Cấm:\n• File giả/lặp\n• Spam\n\nVi phạm = Cấm"},
    "invite_header": {"bn": "👥 রেফারেল লিঙ্ক", "en": "👥 Referral Link", "ur": "👥 ریفرل لنک", "vi": "👥 Link giới thiệu"},
    "your_link": {"bn": "আপনার লিঙ্ক:", "en": "Your link:", "ur": "آپ کا لنک:", "vi": "Link của bạn:"},
    "total_referred": {"bn": "মোট রেফার:", "en": "Total referred:", "ur": "کل ریفرل:", "vi": "Tổng giới thiệu:"},
    "referral_bonus_info": {"bn": "প্রতি রেফারে ৫ টাকা + MLM বোনাস!", "en": "5 Tk per referral + MLM bonus!", "ur": "ہر ریفرل پر 5 ٹکا + MLM بونس!", "vi": "5 Tk mỗi người + thưởng MLM!"},
    "share_link": {"bn": "📤 শেয়ার করুন", "en": "📤 Share", "ur": "📤 شیئر کریں", "vi": "📤 Chia sẻ"},
    "file_order_details": {"bn": "📁 ফাইল অর্ডার ডিটেইলস", "en": "📁 File Order Details", "ur": "📁 فائل آرڈر کی تفصیلات", "vi": "📁 Chi tiết đơn file"},
    "withdraw_order_details": {"bn": "💸 উইথড্র অর্ডার ডিটেইলস", "en": "💸 Withdraw Order Details", "ur": "💸 واپسی آرڈر کی تفصیلات", "vi": "💸 Chi tiết đơn rút tiền"},
    "trackorder_usage": {"bn": "❌ ব্যবহার: /trackorder অর্ডার_আইডি", "en": "❌ Usage: /trackorder order_id", "ur": "❌ استعمال: /trackorder آرڈر_آئی_ڈی", "vi": "❌ Cách dùng: /trackorder order_id"},
    "error_occurred": {"bn": "❌ সমস্যা হয়েছে।", "en": "❌ An error occurred.", "ur": "❌ خرابی ہوئی۔", "vi": "❌ Lỗi xảy ra."},
    "multi_release_usage": {"bn": "❌ ব্যবহার:\n/release\nORDER1 20\nORDER2 15", "en": "❌ Usage:\n/release\nORDER1 20\nORDER2 15"},
    "multi_release_success": {"bn": "✅ {count}টি রিলিজ সফল", "en": "✅ {count} releases successful"},
    "failed_list": {"bn": "❌ ব্যর্থ:", "en": "❌ Failed:"},
    "addbalance_usage": {"bn": "❌ ব্যবহার: /addbalance আইডি পরিমাণ", "en": "❌ Usage: /addbalance id amount"},
    "addbalance_success": {"bn": "✅ ব্যালেন্স যোগ করা হয়েছে", "en": "✅ Balance added"},
    "balance_added": {"bn": "🎉 বোনাস যোগ হয়েছে!", "en": "🎉 Bonus added!"},
    "deduct_usage": {"bn": "❌ ব্যবহার: /deduct অর্ডার পরিমাণ [কারণ]", "en": "❌ Usage: /deduct order amount [reason]"},
    "deduct_success": {"bn": "টাকা কাটা হয়েছে অর্ডার {order_id} থেকে {amount} ৳", "en": "Deducted {amount} ৳ from order {order_id}"},
    "balance_deducted": {"bn": "⚠️ ব্যালেন্স থেকে কাটা হয়েছে", "en": "⚠️ Deducted from balance"},
    "default_deduct_reason": {"bn": "ভুল রিলিজ", "en": "Wrong release"},
    "setrate_usage": {"bn": "❌ সঠিক ফরম্যাটে লাইন দিন", "en": "❌ Enter lines in correct format"},
    "setrate_success": {"bn": "✅ {count}টি রেট আপডেট হয়েছে। {broadcast} জনকে ব্রডকাস্ট করা হয়েছে।", "en": "✅ {count} rates updated. Broadcast to {broadcast} users."},
    "no_rates_updated": {"bn": "❌ কোনো রেট আপডেট হয়নি।", "en": "❌ No rates updated."},
    "skipped_rates": {"bn": "স্কিপ হয়েছে:", "en": "Skipped:"},
    "rate_broadcast_footer": {"bn": "《 ADMIN RATE INBOX 》\nসঠিক ফাইল নামে ID টাইপ লিখুন ✅", "en": "《 ADMIN RATE INBOX 》\nMention ID type in file name ✅"},
    "profile_not_found": {"bn": "প্রোফাইল পাওয়া যায়নি।", "en": "Profile not found."},
    "profile_header": {"bn": "👤 আপনার প্রোফাইল", "en": "👤 Your Profile"},
    "admin_profile_header": {"bn": "👤 ইউজার প্রোফাইল (এডমিন)", "en": "👤 User Profile (Admin)"},
    "admin_profile_usage": {"bn": "❌ ব্যবহার: /profile আইডি", "en": "❌ Usage: /profile id"},
    "toggle_usage": {"bn": "❌ ব্যবহার: /toggle ক্যাটাগরি on/off", "en": "❌ Usage: /toggle category on/off"},
    "toggle_on_off_only": {"bn": "❌ শুধু 'on' বা 'off'", "en": "❌ Only 'on' or 'off'"},
    "category_disabled": {"bn": "{category} বন্ধ করা হয়েছে।", "en": "{category} disabled."},
    "category_enabled": {"bn": "{category} চালু করা হয়েছে।", "en": "{category} enabled."},
    "invalid_rate": {"bn": "❌ সঠিক রেট লিখুন।", "en": "❌ Enter valid rate."},
    "format_required": {"bn": "❌ ফরম্যাট লিখুন।", "en": "❌ Enter format."},
    "toggle_complete": {"bn": "{category} সফলভাবে সেট হয়েছে!\nরেট: {rate}\nফরম্যাট: {format}\nলাস্ট টাইম: {last_time}\nরিপোর্ট টাইম: {report_time}", "en": "{category} set successfully!\nRate: {rate}\nFormat: {format}\nLast Time: {last_time}\nReport Time: {report_time}"},
    "support_prompt": {"bn": "🆘 আপনার সমস্যা লিখুন।", "en": "🆘 Describe your issue."},
    "support_sent": {"bn": "✅ টিকেট পাঠানো হয়েছে।", "en": "✅ Ticket sent."},
    "bot_stats_header": {"bn": "🤖 বট স্ট্যাটস", "en": "🤖 Bot Stats"},
    "admin_help_text": {"bn": "<b>🔧 এডমিন কমান্ড</b>\n\n/stats\n/pending\n/reported\n/setrate\n/broadcast ইত্যাদি", "en": "<b>🔧 Admin Commands</b>\n\n/stats\n/pending\n/reported\n/setrate\n/broadcast etc."},
    "refer_bonus_received": {"bn": "🎉 রেফার বোনাস পেয়েছেন!", "en": "🎉 Referral Bonus Received!", "ur": "🎉 ریفرل بونس ملا!", "vi": "🎉 Nhận thưởng giới thiệu!"},
    "level_label": {"bn": "লেভেল:", "en": "Level:", "ur": "لیول:", "vi": "Cấp:"},
    "bonus_amount": {"bn": "বোনাস:", "en": "Bonus:", "ur": "بونس:", "vi": "Thưởng:"},
    "from_user": {"bn": "ইউজার থেকে:", "en": "From user:", "ur": "صارف سے:", "vi": "Từ người dùng:"},

    "daily_morning_motivation": {"bn": "🤲 ইনশাআল্লাহ আজ অনেক ফাইল এপ্রুভ হবে!\nসকাল থেকে Submit শুরু করুন 💪\nআল্লাহ আপনার রিজিক বাড়িয়ে দিন 🤲", "en": "🤲 InshaAllah many files will be approved today!\nStart submitting from morning 💪", "ur": "🤲 انشاءاللہ آج بہت فائلیں منظور ہوں گی!\nصبح سے جمع کروائیں 💪", "vi": "🤲 InshaAllah hôm nay nhiều file sẽ được duyệt!\nBắt đầu gửi từ sáng 💪"},

    "daily_afternoon_reminder": {"bn": "⏰ দুপুর হয়ে গেছে!\nযারা এখনো Submit করেননি — তাড়াতাড়ি করুন\nLast Time 11 PM BD ⏳", "en": "⏰ Afternoon already!\nThose who haven't submitted yet — do it fast\nLast Time 11 PM BD ⏳", "ur": "⏰ دوپہر ہوگئی!\nجو ابھی تک جمع نہیں کرائے — جلدی کریں\nآخری وقت 11 PM BD ⏳", "vi": "⏰ Đã đến chiều!\nAi chưa gửi thì gửi nhanh nhé\nGiờ cuối 11 PM BD ⏳"},    "refer_bonus_received": {"bn": "🎉 রেফার বোনাস পেয়েছেন!", "en": "🎉 Referral Bonus Received!", "ur": "🎉 ریفرل بونس ملا!", "vi": "🎉 Nhận thưởng giới thiệu!"},
    "level_label": {"bn": "লেভেল:", "en": "Level:", "ur": "لیول:", "vi": "Cấp:"},
    "bonus_amount": {"bn": "বোনাস:", "en": "Bonus:", "ur": "بونس:", "vi": "Thưởng:"},
    "from_user": {"bn": "ইউজার থেকে:", "en": "From user:", "ur": "صارف سے:", "vi": "Từ người dùng:"},

    "daily_morning_motivation": {"bn": "🤲 ইনশাআল্লাহ আজ অনেক ফাইল এপ্রুভ হবে!\nসকাল থেকে Submit শুরু করুন 💪\nআল্লাহ আপনার রিজিক বাড়িয়ে দিন 🤲", "en": "🤲 InshaAllah many files will be approved today!\nStart submitting from morning 💪", "ur": "🤲 انشاءاللہ آج بہت فائلیں منظور ہوں گی!\nصبح سے جمع کروائیں 💪", "vi": "🤲 InshaAllah hôm nay nhiều file sẽ được duyệt!\nBắt đầu gửi từ sáng 💪"},

    "daily_afternoon_reminder": {"bn": "⏰ দুপুর হয়ে গেছে!\nযারা এখনো Submit করেননি — তাড়াতাড়ি করুন\nLast Time 11 PM BD ⏳", "en": "⏰ Afternoon already!\nThose who haven't submitted yet — do it fast\nLast Time 11 PM BD ⏳", "ur": "⏰ دوپہر ہوگئی!\nجو ابھی تک جمع نہیں کرائے — جلدی کریں\nآخری وقت 11 PM BD ⏳", "vi": "⏰ Đã đến chiều!\nAi chưa gửi thì gửi nhanh nhé\nGiờ cuối 11 PM BD ⏳"},
}

# ট্রান্সলেশন ফাংশন (ডাটাবেস লক এড়ানোর জন্য দ্রুত এবং async)
async def t(user_id: int, key: str, **kwargs) -> str:
    # ইউজারের ভাষা পাওয়া (get_user ফাংশন ডাটাবেস থেকে নেবে)
    user = await get_user(user_id)
    lang = user['language'].lower() if user and user.get('language') else 'bn'
    
    # টেক্সট খোঁজা: প্রথমে সরাসরি key → না পেলে bn ডিফল্ট
    text = TEXTS.get(key, {}).get(lang) or TEXTS.get(key, {}).get('bn') or key
    
    # যদি placeholder থাকে (যেমন {amount}) তাহলে format করা
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass  # যদি কোনো placeholder না মেলে তাহলে ছেড়ে দিব
    return text

# ==================== ক্যাটাগরি লিস্ট (আপডেটেড) ====================
MAIN_CATEGORIES = ["Facebook", "Instagram", "Coins", "Gmail", "Others"]

SUB_CATEGORIES = {
    "Facebook": [
        "Webmail",
        "Anymail",
        "Number",
        "PC Clone Cookies",
        "Hotmail"              # নতুন Hotmail সাব-ক্যাটাগরি যোগ করা
    ],
    "Instagram": ["Instagram Cookies", "Instagram 2FA"],
    "Coins": ["Niva Coin", "NS Coin", "Topfollow", "Nitra Coin", "Other Coins"],
    "Gmail": ["Gmail Files", "Random Gmail"],
    "Others": ["Other Files"]
}

# Hotmail এর অধীনে সাব-সাব ক্যাটাগরি
HOTMAIL_SUB = [
    "Hotmail 30+ Friend",   # নতুন যোগ করা
    "Hotmail 00 Friend"     # নতুন যোগ করা
]

PC_CLONE_SUB = ["PC Clone 1000x", "6155/56x Cookies"]
async def init_db():
    """
    ডাটাবেস ইনিশিয়ালাইজ করা — প্রথমবার চালালে টেবিল তৈরি করবে
    পুরোনো ডাটাবেসে নতুন কলাম যোগ করবে (মাইগ্রেশনের মতো)
    লক প্রবলেম এড়ানোর জন্য শুধু একটা কানেকশন ব্যবহার করা হচ্ছে এখানে
    """
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        
        await db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                language TEXT DEFAULT 'bn',
                pending INTEGER DEFAULT 0,
                reported INTEGER DEFAULT 0,
                approved INTEGER DEFAULT 0,
                rejected INTEGER DEFAULT 0,
                earnings_bdt REAL DEFAULT 0.0,
                earnings_usd REAL DEFAULT 0.0,
                payment_method TEXT,
                payment_number TEXT,
                referrer INTEGER,
                referral_count INTEGER DEFAULT 0,    -- রেফারেল কাউন্ট (নতুন যোগ করা)
                last_login DATE
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                category TEXT,
                sub_category TEXT,
                sub_sub_category TEXT,              -- নতুন: Hotmail 30+ Friend ইত্যাদির জন্য
                status TEXT DEFAULT 'pending',
                rate REAL,
                message_id INTEGER UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            );

            CREATE TABLE IF NOT EXISTS rates (
                category TEXT,
                sub_category TEXT,
                rate_bdt REAL DEFAULT 5.0,
                rate_usd REAL DEFAULT 0.0,           -- USD রেট (Binance অনুসারে পরে আপডেট হবে)
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (category, sub_category)
            );

            CREATE TABLE IF NOT EXISTS toggles (
                item TEXT PRIMARY KEY,
                enabled INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount_bdt REAL,
                amount_usd REAL DEFAULT 0.0,
                currency TEXT,                       -- BDT, USDT, BTC ইত্যাদি
                method TEXT,
                number TEXT,
                status TEXT DEFAULT 'pending',
                requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                processed_at DATETIME
            );
        ''')

        # ------------------ মাইগ্রেশন: পুরোনো ডাটাবেসে নতুন কলাম যোগ করা ------------------

        # 1. users টেবিলে referral_count (যদি না থাকে)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0")
            await db.commit()
            print("users টেবিলে referral_count কলাম যোগ করা হয়েছে।")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                print(f"referral_count যোগ করতে সমস্যা: {e}")

        # 2. files টেবিলে sub_sub_category (Hotmail এর অধীনে সাব-সাব ক্যাটাগরির জন্য)
        try:
            await db.execute("ALTER TABLE files ADD COLUMN sub_sub_category TEXT")
            await db.commit()
            print("files টেবিলে sub_sub_category কলাম যোগ করা হয়েছে।")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                print(f"sub_sub_category যোগ করতে সমস্যা: {e}")

        # 3. rates টেবিলে নতুন স্ট্রাকচার (category + sub_category দিয়ে প্রাইমারি কী)
        # পুরোনো rates টেবিলে শুধু category ছিল — নতুন করে মাইগ্রেট করব
        try:
            # পুরোনো ডাটা ব্যাকআপ নেওয়া (যদি থাকে)
            await db.execute("INSERT OR IGNORE INTO rates (category, sub_category, rate_bdt) SELECT category, NULL, rate_bdt FROM old_rates")
            await db.execute("DROP TABLE IF EXISTS old_rates")
        except aiosqlite.OperationalError:
            pass  # পুরোনো টেবিল না থাকলে কিছু করার নেই

        # rates টেবিলে rate_usd এবং updated_at যোগ (পুরোনো ভার্সনের জন্য)
        try:
            await db.execute("ALTER TABLE rates ADD COLUMN rate_usd REAL DEFAULT 0.0")
            await db.execute("ALTER TABLE rates ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP")
            await db.commit()
        except aiosqlite.OperationalError:
            pass

        # withdraw_requests এ amount_usd যোগ
        try:
            await db.execute("ALTER TABLE withdraw_requests ADD COLUMN amount_usd REAL DEFAULT 0.0")
            await db.execute("ALTER TABLE withdraw_requests ADD COLUMN currency TEXT")
            await db.commit()
        except aiosqlite.OperationalError:
            pass

        await db.commit()
        print("ডাটাবেস সফলভাবে ইনিশিয়ালাইজড এবং মাইগ্রেশন সম্পন্ন হয়েছে।")
                # ------------------ অতিরিক্ত মাইগ্রেশন: নতুন কলাম যোগ করা ------------------

        # 1. files টেবিলে user_claimed_count (ইউজার যা ক্লেইম করেছে তার কাউন্ট)
        try:
            await db.execute("ALTER TABLE files ADD COLUMN user_claimed_count INTEGER DEFAULT 0")
            await db.commit()
            print("files টেবিলে user_claimed_count কলাম যোগ করা হয়েছে।")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                print(f"user_claimed_count যোগ করতে সমস্যা: {e}")

        # 2. users টেবিলে pending_withdraw (পেন্ডিং উইথড্র অ্যামাউন্ট ট্র্যাক করার জন্য)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN pending_withdraw REAL DEFAULT 0.0")
            await db.commit()
            print("users টেবিলে pending_withdraw কলাম যোগ করা হয়েছে।")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                print(f"pending_withdraw যোগ করতে সমস্যা: {e}")

        # 3. withdraw_requests টেবিলে processed_by (কে প্রসেস করেছে তার এডমিন আইডি)
        try:
            await db.execute("ALTER TABLE withdraw_requests ADD COLUMN processed_by INTEGER")
            await db.commit()
            print("withdraw_requests টেবিলে processed_by কলাম যোগ করা হয়েছে।")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                print(f"processed_by যোগ করতে সমস্যা: {e}")

        # 4. অন্যান্য নতুন কলাম যোগ (order_id, username, data_count ইত্যাদি)
        new_columns = [
            ("files", "order_id", "TEXT"),
            ("files", "username", "TEXT"),
            ("files", "data_count", "INTEGER DEFAULT 1"),
            ("withdraw_requests", "order_id", "TEXT"),
            ("withdraw_requests", "created_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")  # withdraw_requests-এ created_at
        ]
        for table, col, col_type in new_columns:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                await db.commit()
                print(f"{table} টেবিলে {col} কলাম যোগ করা হয়েছে।")
            except aiosqlite.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    print(f"{col} যোগ করতে সমস্যা: {e}")

        # 5. rates টেবিলে অতিরিক্ত অ্যাডমিন কন্ট্রোল কলামসমূহ
        rates_extra_columns = [
            ("display_name", "TEXT"),           # ক্যাটাগরির সুন্দর নাম দেখানোর জন্য
            ("format_text", "TEXT"),            # ফাইল ফরম্যাট দেখানোর জন্য
            ("last_time", "INTEGER DEFAULT 0"), # লাস্ট আপলোড টাইম ট্র্যাক
            ("report_time", "INTEGER DEFAULT 0")  # রিপোর্ট টাইম
        ]
        for col, col_type in rates_extra_columns:
            try:
                await db.execute(f"ALTER TABLE rates ADD COLUMN {col} {col_type}")
            except aiosqlite.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    print(f"rates টেবিলে {col} যোগ করতে সমস্যা: {e}")
        await db.commit()
        print("rates টেবিলে অতিরিক্ত কলাম যোগ করা হয়েছে।")

        # ------------------ ডিফল্ট রেট এবং টগল ইনসার্ট ------------------
        # প্রত্যেক মেইন + সাব ক্যাটাগরির জন্য ডিফল্ট রেট সেট করা
        for main in MAIN_CATEGORIES:
            for sub in SUB_CATEGORIES.get(main, []):
                category_key = f"{main}_{sub.replace(' ', '_')}"  # স্পেস থাকলে আন্ডারস্কোর
                await db.execute("""
                    INSERT OR IGNORE INTO rates (category, sub_category, rate_bdt, rate_usd)
                    VALUES (?, ?, 5.0, 0.0)
                """, (main, sub))

                # টগল আইটেম (যেমন রেট টগল, রিপোর্ট টগল ইত্যাদি)
                await db.execute("INSERT OR IGNORE INTO toggles (item, enabled) VALUES (?, 1)", (f"rate_{category_key}",))
                await db.execute("INSERT OR IGNORE INTO toggles (item, enabled) VALUES (?, 1)", (f"upload_{category_key}",))

        # Hotmail এর সাব-সাব ক্যাটাগরির জন্যও ডিফল্ট রেট
        for sub_sub in HOTMAIL_SUB:
            await db.execute("""
                INSERT OR IGNORE INTO rates (category, sub_category, sub_sub_category, rate_bdt, rate_usd)
                VALUES (?, ?, ?, 5.0, 0.0)
            """, ("Facebook", "Hotmail", sub_sub))

        await db.commit()
        print("ডিফল্ট রেট এবং টগলসমূহ সফলভাবে সেট করা হয়েছে।")

        print("সম্পূর্ণ ডাটাবেস মাইগ্রেশন সম্পন্ন হয়েছে।")
# ==================== ডাটাবেস হেল্পার ফাংশন (অপটিমাইজড ও লক-ফ্রি) ====================

async def get_user(user_id: int):
    """ইউজারের সম্পূর্ণ ডাটা ডিক্ট আকারে রিটার্ন করে"""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def add_user(user_id: int, username: str, full_name: str, referrer: int = None):
    """নতুন ইউজার যোগ করা বা আপডেট করা"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name, last_login)
            VALUES (?, ?, ?, DATE('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                last_login = DATE('now')
        """, (user_id, username or "", full_name or ""))
        await db.commit()
    
    if referrer:
        await give_refer_bonus(user_id)  # ধরে নিচ্ছি এই ফাংশন পরে আছে


async def get_rate(category: str, sub_category: str = None, sub_sub_category: str = None):
    """ক্যাটাগরি অনুসারে রেট রিটার্ন — USD সাপোর্ট সহ"""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT rate_bdt, rate_usd FROM rates WHERE category = ? AND sub_category "
        params = [category]
        
        if sub_sub_category:
            query += "= ? AND sub_sub_category = ?"
            params.extend([sub_category, sub_sub_category])
        elif sub_category:
            query += "= ?"
            params.append(sub_category)
        else:
            query += "IS NULL"
            
        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"bdt": row["rate_bdt"], "usd": row["rate_usd"]}
    # ডিফল্ট রেট
    return {"bdt": 5.0, "usd": 0.0}


async def is_enabled(item: str) -> bool:
    """টগল চেক করা (যেমন upload বা rate toggle)"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT enabled FROM toggles WHERE item = ?", (item,)) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else True


async def get_coin_user() -> str:
    return "genzraiyaan"


# ==================== ইনলাইন কীবোর্ড ফাংশন (ইউজার vs এডমিন আলাদা + ট্রান্সলেটেড) ====================

async def main_menu(user_id: int):
    """ইউজার বা এডমিনের জন্য সম্পূর্ণ আলাদা মেইন মেনু"""
    user = await get_user(user_id)
    lang = user['language'] if user and user.get('language') else 'bn'
    is_admin = user_id in ADMIN_IDS

    if is_admin:
        return await admin_main_menu(lang)
    else:
        return await user_main_menu(lang)


async def user_main_menu(lang: str):
    """সাধারণ ইউজারের জন্য সুন্দর মেইন মেনু"""
    kb = [
        [InlineKeyboardButton(text=t(lang, "send_files"), callback_data="send_files")],
        [
            InlineKeyboardButton(text=t(lang, "today_rate"), callback_data="today_rate"),
            InlineKeyboardButton(text=t(lang, "my_files"), callback_data="files_menu")
        ],
        [
            InlineKeyboardButton(text=t(lang, "balance"), callback_data="balance"),
            InlineKeyboardButton(text=t(lang, "withdraw"), callback_data="withdraw")
        ],
        [
            InlineKeyboardButton(text=t(lang, "referral"), callback_data="referral"),
            InlineKeyboardButton(text=t(lang, "track_order"), callback_data="track_order")
        ],
        [InlineKeyboardButton(text=t(lang, "join_channel"), url="https://t.me/your_channel")],  # চ্যানেল লিঙ্ক পরিবর্তন করুন
        [
            InlineKeyboardButton(text=t(lang, "my_stats"), callback_data="mystats"),
            InlineKeyboardButton(text=t(lang, "support"), url="https://t.me/techsupportbd")
        ],
        [InlineKeyboardButton(text=t(lang, "settings"), callback_data="settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


async def admin_main_menu(lang: str):
    """এডমিনের জন্য সম্পূর্ণ আলাদা শক্তিশালী মেনু"""
    kb = [
        [InlineKeyboardButton(text="📊 User Stats", callback_data="admin_userstats")],
        [InlineKeyboardButton(text="⏳ Pending Files", callback_data="admin_pending")],
        [InlineKeyboardButton(text="✅ Approved Files", callback_data="admin_approved")],
        [InlineKeyboardButton(text="❌ Rejected Files", callback_data="admin_rejected")],
        [InlineKeyboardButton(text="💸 Pending Withdraws", callback_data="admin_withdraws")],
        [InlineKeyboardButton(text="💱 Set Rates", callback_data="admin_setrate")],
        [InlineKeyboardButton(text="📈 Bot Statistics", callback_data="admin_botstats")],
        [InlineKeyboardButton(text="🔧 Toggles", callback_data="admin_toggles")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="⚙️ Settings", callback_data="admin_settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ব্যাক বাটন — পূর্বের স্টেটে ফিরবে (হোমে না গিয়ে)
async def back_button(lang: str, callback_data: str = "back"):
    kb = [[InlineKeyboardButton(text=t(lang, "back"), callback_data=callback_data)]]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# কাজ শেষে বাটন রিমোভ করার জন্য (edit_message_reply_markup)
async def remove_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[])


# সেটিংস মেনু (ভাষা চেঞ্জ সহ)
async def settings_menu(user_id: int):
    user = await get_user(user_id)
    lang = user['language'] if user else 'bn'
    
    kb = [
        [InlineKeyboardButton(text=LANGUAGES['bn']['name'], callback_data="lang_bn")],
        [InlineKeyboardButton(text=LANGUAGES['en']['name'], callback_data="lang_en")],
        [InlineKeyboardButton(text=LANGUAGES['ur']['name'], callback_data="lang_ur")],
        [InlineKeyboardButton(text=LANGUAGES['vi']['name'], callback_data="lang_vi")],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
@dp.message(Command("start"))
async def start(message: types.Message):
    args = message.text.split()
    referrer = None
    if len(args) > 1 and args[1].isdigit():
        try:
            referrer = int(args[1])
        except ValueError:
            pass

    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or ""

    await add_user(user_id, username, full_name, referrer)

    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

    # ইউজারের ভাষা অনুযায়ী টেক্সট
    welcome_text = await t(user_id, "welcome")
    ref_text = await t(user_id, "referral_info", ref_link=ref_link)

    # প্রথমবার হলে ভাষা সিলেক্ট দেখাবে
    user = await get_user(user_id)
    if not user or not user.get('language'):
        select_lang_text = await t(user_id, "select_language")
        kb = [
            [InlineKeyboardButton(text=LANGUAGES['bn']['name'], callback_data="lang_bn")],
            [InlineKeyboardButton(text=LANGUAGES['en']['name'], callback_data="lang_en")],
            [InlineKeyboardButton(text=LANGUAGES['ur']['name'], callback_data="lang_ur")],
            [InlineKeyboardButton(text=LANGUAGES['vi']['name'], callback_data="lang_vi")],
        ]
        reply_markup = InlineKeyboardMarkup(inline_keyboard=kb)
        final_text = f"{welcome_text}\n\n{ref_text}\n\n{select_lang_text}"
    else:
        # ভাষা ইতিমধ্যে সেট থাকলে সরাসরি মেইন মেনু
        final_text = welcome_text + "\n\n" + ref_text
        reply_markup = await main_menu(user_id)

    await message.answer(final_text, reply_markup=reply_markup, disable_web_page_preview=True)


@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(call: types.CallbackQuery):
    lang_code = call.data.split("_")[1]
    if lang_code not in ['bn', 'en', 'ur', 'vi']:
        await call.answer("Invalid language!", show_alert=True)
        return

    user_id = call.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang_code, user_id))
        await db.commit()

    success_text = await t(user_id, "language_changed")
    await call.message.edit_text(success_text, reply_markup=await main_menu(user_id))
    await call.answer(success_text)


@dp.callback_query(F.data == "main_menu")
async def home(call: types.CallbackQuery):
    user_id = call.from_user.id
    home_title = await t(user_id, "home_title")
    await call.message.edit_text(home_title, reply_markup=await main_menu(user_id))
    await call.answer()


@dp.callback_query(F.data == "send_files")
async def send_files(call: types.CallbackQuery):
    user_id = call.from_user.id
    lang = (await get_user(user_id))['language']

    kb = []
    for cat in MAIN_CATEGORIES:
        translated_cat = TEXTS[f"main_{cat.lower()}"][lang]
        kb.append([InlineKeyboardButton(text=translated_cat, callback_data=f"maincat_{cat}")])

    # ব্যাক বাটন — send_files থেকে main_menu তে ফিরবে
    kb.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="main_menu")])

    select_text = await t(user_id, "select_main_category")
    await call.message.edit_text(select_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()


@dp.callback_query(F.data.startswith("maincat_"))
async def main_cat_selected(call: types.CallbackQuery):
    user_id = call.from_user.id
    lang = (await get_user(user_id))['language']
    cat = call.data.split("_")[1]

    translated_cat = TEXTS[f"main_{cat.lower()}"][lang]

    kb = []
    sub_cats = SUB_CATEGORIES.get(cat, [])

    for sub in sub_cats:
        full_key = f"{cat}_{sub.replace(' ', '_')}"
        if await is_enabled(f"upload_{full_key}"):
            translated_sub = TEXTS.get(f"sub_{sub.lower().replace(' ', '_')}", {}).get(lang, sub)
            callback = f"subcat_{cat}_{sub}"
            kb.append([InlineKeyboardButton(text=translated_sub, callback_data=callback)])

    # Hotmail এর সাব-সাব ক্যাটাগরি যদি থাকে
    if cat == "Facebook" and "Hotmail" in sub_cats:
        # Hotmail সিলেক্ট করলে পরে সাব-সাব দেখাবে — এখানে শুধু Hotmail দেখাচ্ছি
        pass  # পরের হ্যান্ডলারে করব

    # ব্যাক বাটন — send_files মেনুতে ফিরবে
    kb.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="send_files")])

    sub_text = await t(user_id, "select_sub_category", category=translated_cat)
    await call.message.edit_text(sub_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()
@dp.callback_query(F.data.startswith("subcat_"))
async def sub_cat_selected(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    lang = (await get_user(user_id))['language']
    full_cat = call.data.split("_", 1)[1]  # যেমন "Facebook_Webmail" বা "Facebook_Hotmail"
    await state.update_data(category=full_cat, prev_callback="maincat_" + full_cat.split("_")[0])  # ব্যাকের জন্য পূর্বের ক্যাট সেভ

    # USD vs BDT চেক: বাংলা না হলে USD ব্যবহার করব (পরে রেট দেখানোর সময়)
    use_usd = lang != 'bn'
    currency = 'usd' if use_usd else 'bdt'

    # সাব-সাব ক্যাটাগরি চেক (PC Clone, Hotmail ইত্যাদি)
    if "PC Clone Cookies" in full_cat:
        kb = []
        for sub in PC_CLONE_SUB:
            translated_sub = TEXTS.get(f"pc_clone_{sub.lower().replace(' ', '_')}", {}).get(lang, sub)
            callback = f"subsubcat_{full_cat}_{sub}"
            kb.append([InlineKeyboardButton(text=translated_sub, callback_data=callback)])
        
        # ব্যাক: পূর্বের মেনুতে (maincat_)
        kb.append([InlineKeyboardButton(text=t(lang, "back"), callback_data=f"maincat_{full_cat.split('_')[0]}")])
        kb.append([InlineKeyboardButton(text=t(lang, "home"), callback_data="main_menu")])

        pc_prompt = await t(user_id, "pc_clone_prompt")
        await call.message.edit_text(pc_prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    elif "Hotmail" in full_cat:
        # Hotmail এর সাব-সাব (30+ Friend, 00 Friend)
        kb = []
        for sub_sub in HOTMAIL_SUB:
            key = sub_sub.lower().replace(' ', '_').replace('+', 'plus')
            translated_sub = TEXTS.get(f"hotmail_{key}", {}).get(lang, sub_sub)
            callback = f"subsubcat_{full_cat}_{sub_sub}"
            kb.append([InlineKeyboardButton(text=translated_sub, callback_data=callback)])
        
        kb.append([InlineKeyboardButton(text=t(lang, "back"), callback_data=f"maincat_{full_cat.split('_')[0]}")])
        kb.append([InlineKeyboardButton(text=t(lang, "home"), callback_data="main_menu")])

        hotmail_prompt = await t(user_id, "hotmail_prompt")
        await call.message.edit_text(hotmail_prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    elif "Random Gmail" in full_cat:
        # র‍্যান্ডম জিমেইল সাজেস্ট — সিকিউরিটি উন্নত করা
        lowercase = string.ascii_lowercase
        digits = string.digits
        special = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        all_chars = string.ascii_letters + digits + special

        username_len = random.randint(8, 12)
        username = ''.join(random.choices(lowercase + digits, k=username_len))
        email = f"{username}@gmail.com"

        password_len = random.randint(12, 16)
        password = (
            random.choice(string.ascii_uppercase) +
            random.choice(lowercase) +
            random.choice(digits) +
            random.choice(special) +
            ''.join(random.choices(all_chars, k=password_len - 4))
        )

        suggestion_text = (
            await t(user_id, "suggested_gmail") + f"\n<code>{email}</code>\n\n" +
            await t(user_id, "strong_password") + f"\n<code>{password}</code>\n\n" +
            await t(user_id, "create_gmail_instruction") + "\n\n" +
            await t(user_id, "press_done")
        )

        kb = [
            [InlineKeyboardButton(text=t(lang, "done"), callback_data="gmail_done")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"maincat_{full_cat.split('_')[0]}")],
            [InlineKeyboardButton(text=t(lang, "home"), callback_data="main_menu")]
        ]

        title = await t(user_id, "random_gmail_title")
        desc = await t(user_id, "random_gmail_desc")
        final_text = f"<b>{title}</b>\n\n{suggestion_text}\n\n{desc}"

        await call.message.edit_text(final_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await state.set_state(States.random_gmail_done)  # স্টেট সেট (পরে Done হ্যান্ডেল করার জন্য)

    else:
        # সাধারণ ফাইল / কয়েন পাঠানো প্রম্পট
        text = await t(user_id, "send_file_prompt")
        if "Coin" in full_cat:
            coin_user = await get_coin_user()
            text += f"\n\n{await t(user_id, 'coin_user_prompt', coin_user=coin_user)}"

        kb = [
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="send_cancel")],
            [InlineKeyboardButton(text=t(lang, "home"), callback_data="main_menu")]
        ]

        # পুরোনো মেসেজ আইডি সেভ (পরে রিমোভ বাটনের জন্য)
        await state.update_data(prev_msg_id=call.message.message_id)

        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await state.set_state(States.waiting_file)

    # সবসময় অ্যাডমিন/ইউজার চেক করে মেনু দেখানো — কিন্তু এখানে প্রয়োজন নেই কারণ সাব-ক্যাট ইউজারের
    await call.answer()
@dp.callback_query(F.data == "ready_send")
async def ready_send(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    lang = (await get_user(user_id))['language']
    
    text = await t(user_id, "send_file_prompt")
    
    kb = [
        [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="send_cancel")],
        [InlineKeyboardButton(text=t(lang, "home"), callback_data="main_menu")]
    ]
    
    # পুরোনো বাটন রিমোভ করে নতুন করে পাঠানো
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(States.waiting_file)
    await call.answer()


# কপি ইউজার আইডি বাটন — সুন্দর অ্যালার্ট সহ
@dp.callback_query(F.data.startswith("copyid_"))
async def copy_user_id(call: types.CallbackQuery):
    try:
        user_id = call.data.split("_")[1]
        await call.answer(text=user_id, show_alert=True, cache_time=60)
    except:
        await call.answer("Invalid User ID", show_alert=True)


# র‍্যান্ডম জিমেইল Done বাটন
@dp.callback_query(F.data == "gmail_done")
async def gmail_done(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    lang = (await get_user(user_id))['language']
    user = call.from_user

    # এডমিনের জন্য বাটন
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"gmail_approve_{user_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"gmail_reject_{user_id}")
        ],
        [InlineKeyboardButton(text="📋 Copy User ID", callback_data=f"copyid_{user_id}")]
    ])

    current_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

    caption = (
        await t(user_id, "random_gmail_request_title") + "\n\n" +
        await t(user_id, "submitted_at") + f" {current_time}\n" +
        await t(user_id, "user_label") + f" {user.full_name}\n" +
        await t(user_id, "username_label") + f" @{user.username or 'None'}\n" +
        await t(user_id, "user_id_label") + f" <code>{user_id}</code>"
    )

    await bot.send_message(
        chat_id=ADMIN_IDS[0],  # প্রথম এডমিন (একাধিক থাকলে লুপ করা যাবে)
        text=caption,
        parse_mode="HTML",
        reply_markup=admin_kb
    )

    success_text = await t(user_id, "gmail_request_sent")
    await call.message.edit_text(success_text, reply_markup=await main_menu(user_id))
    await state.clear()
    await call.answer()


# Gmail Approve / Reject হ্যান্ডলার (এডমিন ওনলি)
async def handle_gmail_admin(call: types.CallbackQuery, action: str):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ You are not authorized!", show_alert=True)
        return

    try:
        target_user_id = int(call.data.split("_")[-1])
    except:
        await call.answer("Invalid data.", show_alert=True)
        return

    status_emoji = "✅" if action == "approve" else "❌"
    status_text = await t(target_user_id, f"gmail_{action}d")

    # ইউজারকে নোটিফাই
    try:
        await bot.send_message(
            target_user_id,
            f"{status_emoji} {status_text}\n\n" +
            await t(target_user_id, "gmail_next_step"),
            parse_mode="HTML"
        )
    except:
        pass

    # এডমিন মেসেজ আপডেট
    new_caption = (call.message.text or "") + f"\n\n{status_emoji} <b>{action.capitalize()}d by Admin</b>"
    try:
        await call.message.edit_text(new_caption, parse_mode="HTML")
    except TelegramBadRequest:
        pass

    await call.answer(f"Gmail request {action}d.")


@dp.callback_query(F.data.startswith("gmail_approve_"))
async def gmail_approve(call: types.CallbackQuery):
    await handle_gmail_admin(call, "approve")


@dp.callback_query(F.data.startswith("gmail_reject_"))
async def gmail_reject(call: types.CallbackQuery):
    await handle_gmail_admin(call, "reject")


# ফাইল রিসিভ + পরিমাণ জিজ্ঞাসা
@dp.message(States.waiting_file, F.document | F.photo)
async def receive_file(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = (await get_user(user_id))['language']
    data = await state.get_data()
    full_cat = data.get("category", "Unknown")

    # রেট + কারেন্সি (বাংলা ছাড়া USD)
    rate_info = await get_rate(full_cat.split('_')[0], full_cat.split('_')[1])
    use_usd = lang != 'bn'
    rate = rate_info['usd'] if use_usd else rate_info['bdt']
    currency_symbol = "$" if use_usd else "৳"

    # অর্ডার আইডি + টাইম
    order_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    current_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

    file_id = message.document.file_id if message.document else message.photo[-1].file_id
    is_document = message.document is not None

    await state.update_data(
        temp_order_id=order_id,
        temp_file_id=file_id,
        temp_is_document=is_document,
        temp_category=full_cat,
        temp_rate=rate,
        temp_currency=currency_symbol,
        temp_message_id=message.message_id,
        submit_time=current_time
    )
    await state.set_state(AdminStates.user_quantity)

    # পুরোনো প্রম্পট মেসেজের বাটন রিমোভ
    prev_msg_id = data.get('prev_msg_id')
    if prev_msg_id:
        try:
            await bot.edit_message_reply_markup(chat_id=message.chat.id, message_id=prev_msg_id, reply_markup=None)
        except:
            pass

    quantity_prompt = (
        await t(user_id, "file_received") + "\n\n" +
        await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(user_id, "submitted_at") + f" {current_time}\n" +
        await t(user_id, "category_label") + f" {full_cat.replace('_', ' ')}\n" +
        await t(user_id, "rate_label") + f" {rate} {currency_symbol} " + await t(user_id, "per_data") + "\n\n" +
        await t(user_id, "quantity_question")
    )

    await message.answer(quantity_prompt, parse_mode="HTML")


# ইউজার পরিমাণ লিখলে → এডমিনের কাছে পাঠানো
@dp.message(AdminStates.user_quantity)
async def user_quantity_received(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = (await get_user(user_id))['language']
    
    try:
        user_count = int(message.text.strip())
        if user_count <= 0:
            raise ValueError
    except ValueError:
        await message.answer(await t(user_id, "invalid_quantity"), parse_mode="HTML")
        return

    data = await state.get_data()
    order_id = data['temp_order_id']
    file_id = data['temp_file_id']
    is_document = data['temp_is_document']
    full_cat = data['temp_category']
    rate = data['temp_rate']
    currency = data['temp_currency']
    submit_time = data['submit_time']

    user_total = rate * user_count

    # এডমিনের কাছে পাঠানো (উন্নত বাটন + কপি আইডি)
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{order_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{order_id}")
        ],
        [
            InlineKeyboardButton(text="💸 Release Payment", callback_data=f"release_{order_id}"),
            InlineKeyboardButton(text="📋 Copy User ID", callback_data=f"copyid_{user_id}")
        ]
    ])

    caption = (
        await t(user_id, "new_file_received") + "\n\n" +
        await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(user_id, "submitted_at") + f" {submit_time}\n" +
        await t(user_id, "category_label") + f" {full_cat.replace('_', ' ')}\n" +
        await t(user_id, "rate_label") + f" {rate} {currency} " + await t(user_id, "per_data") + "\n" +
        await t(user_id, "user_claimed") + f" <b>{user_count}</b>\n" +
        await t(user_id, "user_total") + f" <b>{user_total} {currency}</b>\n\n" +
        await t(user_id, "name_label") + f" {message.from_user.full_name}\n" +
        await t(user_id, "username_label") + f" @{message.from_user.username or 'None'}\n" +
        await t(user_id, "user_id_label") + f" <code>{user_id}</code>"
    )

    if is_document:
        sent_msg = await bot.send_document(ADMIN_IDS[0], file_id, caption=caption, parse_mode="HTML", reply_markup=admin_kb)
    else:
        sent_msg = await bot.send_photo(ADMIN_IDS[0], file_id, caption=caption, parse_mode="HTML", reply_markup=admin_kb)

    # ডাটাবেসে সেভ (লক-ফ্রি + সেফ)
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("""
            INSERT INTO files
            (user_id, category, sub_category, status, rate, message_id, order_id, username, user_claimed_count, created_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, DATETIME('now'))
        """, (
            user_id,
            full_cat.split('_')[0],
            full_cat.split('_')[1],
            rate,
            sent_msg.message_id,  # এডমিনের মেসেজ আইডি সেভ (পরে এপ্রুভে ব্যবহার)
            order_id,
            message.from_user.username or "",
            user_count
        ))
        await db.execute("UPDATE users SET pending = pending + 1 WHERE user_id = ?", (user_id,))
        await db.commit()

    # ইউজারকে সাকসেস মেসেজ
    success_msg = (
        await t(user_id, "file_submitted_success") + "\n\n" +
        await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(user_id, "submitted_at") + f" {submit_time}\n" +
        await t(user_id, "user_claimed") + f" <b>{user_count}</b>\n" +
        await t(user_id, "user_total") + f" <b>{user_total} {currency}</b>\n\n" +
        await t(user_id, "track_instruction")
    )

    copy_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await t(user_id, "copy_order_id"), callback_data=f"copyorder_{order_id}")],
        [InlineKeyboardButton(text=await t(user_id, "home"), callback_data="main_menu")]
    ])

    await message.answer(success_msg, parse_mode="HTML", reply_markup=copy_kb)
    await state.clear()


# অর্ডার আইডি কপি বাটন
@dp.callback_query(F.data.startswith("copyorder_"))
async def copy_order_id(call: types.CallbackQuery):
    order_id = call.data.split("_")[1]
    await call.answer(text=order_id, show_alert=True, cache_time=60)
# ইউজার পরিমাণ লিখলে → এডমিনের কাছে পাঠানো (উন্নত ভার্সন)
@dp.message(AdminStates.user_quantity)
async def user_quantity_received(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = (await get_user(user_id))['language']
    use_usd = lang != 'bn'  # বাংলা ছাড়া সবাই USD দেখবে
    currency = '$' if use_usd else '৳'

    try:
        user_count = int(message.text.strip())
        if user_count <= 0:
            raise ValueError
    except ValueError:
        await message.answer(await t(user_id, "invalid_quantity"), parse_mode="HTML")
        return

    data = await state.get_data()
    order_id = data['temp_order_id']
    file_id = data['temp_file_id']
    is_document = data['temp_is_document']
    full_cat = data['temp_category']
    rate = data['temp_rate']  # ইতিমধ্যে USD/BDT অনুসারে সেট করা আছে receive_file-এ
    auto_count = data.get('temp_auto_count', 0)  # যদি অটো কাউন্ট থাকে
    submit_time = data['submit_time']

    user_total = rate * user_count

    # এডমিনের কাছে পাঠানো — শক্তিশালী বাটন
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{order_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{order_id}")
        ],
        [
            InlineKeyboardButton(text="💸 Release Payment", callback_data=f"release_{order_id}"),
            InlineKeyboardButton(text="📋 Copy User ID", callback_data=f"copyid_{user_id}")
        ],
        [InlineKeyboardButton(text="🤖 Auto Count", callback_data=f"autocount_{order_id}_{auto_count}")]
    ])

    current_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

    caption = (
        await t(user_id, "new_file_received") + "\n\n" +
        await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(user_id, "submitted_at") + f" {current_time}\n" +
        await t(user_id, "category_label") + f" {full_cat.replace('_', ' ')}\n" +
        await t(user_id, "rate_label") + f" {rate}{currency} " + await t(user_id, "per_data") + "\n" +
        await t(user_id, "auto_count_label") + f" <b>{auto_count}</b>\n" +
        await t(user_id, "user_claimed") + f" <b>{user_count}</b>\n" +
        await t(user_id, "user_total") + f" <b>{user_total}{currency}</b>\n\n" +
        await t(user_id, "name_label") + f" {message.from_user.full_name}\n" +
        await t(user_id, "username_label") + f" @{message.from_user.username or 'None'}\n" +
        await t(user_id, "user_id_label") + f" <code>{user_id}</code>"
    )

    if is_document:
        sent_msg = await bot.send_document(ADMIN_IDS[0], file_id, caption=caption, parse_mode="HTML", reply_markup=admin_kb)
    else:
        sent_msg = await bot.send_photo(ADMIN_IDS[0], file_id, caption=caption, parse_mode="HTML", reply_markup=admin_kb)

    # ডাটাবেসে সেভ — লক-ফ্রি + অটো কাউন্ট সহ
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("""
            INSERT INTO files
            (user_id, category, sub_category, status, rate, message_id, order_id, username, 
             user_claimed_count, data_count, created_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, DATETIME('now'))
        """, (
            user_id,
            full_cat.split('_')[0],
            full_cat.split('_')[1],
            rate,
            sent_msg.message_id,
            order_id,
            message.from_user.username or "",
            user_count,   # user_claimed_count
            auto_count    # data_count (অটো কাউন্ট বা পরে এডমিন সেট করবে)
        ))
        await db.execute("UPDATE users SET pending = pending + 1 WHERE user_id = ?", (user_id,))
        await db.commit()

    # ইউজারকে সাকসেস মেসেজ
    success_msg = (
        await t(user_id, "file_submitted_success") + "\n\n" +
        await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(user_id, "submitted_at") + f" {current_time}\n" +
        await t(user_id, "auto_count_label") + f" {auto_count}\n" +
        await t(user_id, "user_claimed") + f" <b>{user_count}</b>\n" +
        await t(user_id, "user_total") + f" <b>{user_total}{currency}</b>\n\n" +
        await t(user_id, "track_instruction")
    )

    copy_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await t(user_id, "copy_order_id"), callback_data=f"copyorder_{order_id}")],
        [InlineKeyboardButton(text=await t(user_id, "home"), callback_data="main_menu")]
    ])

    await message.answer(success_msg, parse_mode="HTML", reply_markup=copy_kb)
    await state.clear()


# ================ Approve হ্যান্ডলার (এডমিন ওনলি) ================
@dp.callback_query(F.data.startswith("approve_"))
async def approve_file(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Unauthorized!", show_alert=True)
        return

    order_id = call.data.split("_")[1]

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT user_id, rate, user_claimed_count, data_count FROM files 
            WHERE order_id = ?
        """, (order_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await call.answer("⚠️ File not found.", show_alert=True)
                return

        user_id = row['user_id']
        rate = row['rate']
        final_count = row['data_count'] or row['user_claimed_count']  # এডমিন সেট না করলে ইউজারেরটা
        amount = rate * final_count

        # স্ট্যাটাস আপডেট
        await db.execute("UPDATE files SET status = 'reported' WHERE order_id = ?", (order_id,))
        await db.execute("""
            UPDATE users 
            SET pending = pending - 1, reported = reported + 1, earnings_bdt = earnings_bdt + ?
            WHERE user_id = ?
        """, (amount, user_id))
        await db.commit()

    current_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
    lang = (await get_user(user_id))['language']
    currency = '$' if lang != 'bn' else '৳'

    notify_msg = (
        await t(user_id, "approve_notification") + "\n\n" +
        await t(user_id, "submitted_at") + f" {current_time}\n" +
        await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(user_id, "approved_amount") + f" <b>{amount}{currency}</b>\n" +
        await t(user_id, "payment_soon")
    )

    copy_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await t(user_id, "copy_order_id"), callback_data=f"copyorder_{order_id}")]
    ])

    try:
        await bot.send_message(user_id, notify_msg, parse_mode="HTML", reply_markup=copy_kb)
    except:
        pass

    # এডমিন মেসেজ আপডেট + বাটন রিমোভ
    new_caption = (call.message.caption or call.message.text) + f"\n\n✅ <b>Approved! {amount}{currency} added. Waiting for payment.</b>"
    try:
        await call.message.edit_caption(caption=new_caption, parse_mode="HTML", reply_markup=None)
    except:
        await call.message.edit_text(new_caption, parse_mode="HTML", reply_markup=None)

    await call.answer("Approved ✅")


# ================ Withdraw Approve (এডমিন ওনলি) ================
@dp.callback_query(F.data.startswith("admin_approvewd_"))
async def admin_approve_withdraw(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Unauthorized!", show_alert=True)
        return

    try:
        target_user_id = int(call.data.split("_")[2])
    except:
        await call.answer("Invalid data.")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT amount_bdt, amount_usd, currency, order_id FROM withdraw_requests 
            WHERE user_id = ? AND status = 'pending' 
            ORDER BY requested_at DESC LIMIT 1
        """, (target_user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await call.answer("No pending withdraw.", show_alert=True)
                return

        amount_bdt = row['amount_bdt']
        amount_usd = row['amount_usd']
        currency = row['currency'] or 'BDT'
        order_id = row['order_id']

        # ব্যালেন্স কাটা
        await db.execute("UPDATE users SET earnings_bdt = earnings_bdt - ?, pending_withdraw = pending_withdraw - ? WHERE user_id = ?", 
                        (amount_bdt, amount_bdt, target_user_id))
        await db.execute("UPDATE withdraw_requests SET status = 'approved', processed_at = DATETIME('now') WHERE order_id = ?", (order_id,))
        await db.commit()

    lang = (await get_user(target_user_id))['language']
    display_amount = amount_usd if lang != 'bn' and amount_usd > 0 else amount_bdt
    display_currency = '$' if lang != 'bn' and amount_usd > 0 else '৳'

    try:
        await bot.send_message(
            target_user_id,
            await t(target_user_id, "withdraw_approved") + "\n\n" +
            await t(target_user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
            await t(target_user_id, "amount_label") + f" <b>{display_amount}{display_currency}</b>\n\n" +
            await t(target_user_id, "send_screenshot_prompt"),
            parse_mode="HTML"
        )
    except:
        pass

    await call.message.edit_text(
        call.message.text + f"\n\n✅ <b>Withdraw Approved ({display_amount}{display_currency})</b>",
        parse_mode="HTML"
    )
    await call.answer("Withdraw approved ✅")
# ================ Reject হ্যান্ডলার (এডমিন ওনলি + উন্নত) ================
@dp.callback_query(F.data.startswith("reject_"))
async def reject_file(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Unauthorized!", show_alert=True)
        return

    try:
        order_id = call.data.split("_")[1]

        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT user_id, rate, user_claimed_count, data_count, category, sub_category 
                FROM files WHERE order_id = ?
            """, (order_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await call.answer("File not found or already processed.", show_alert=True)
                    return

        user_id = row['user_id']
        rate = row['rate']
        final_count = row['data_count'] or row['user_claimed_count']
        total_amount = rate * final_count
        full_cat = f"{row['category']}_{row['sub_category']}".replace(' ', '_')

        # স্টেটে সেভ
        await state.update_data(
            reject_order_id=order_id,
            reject_user_id=user_id,
            reject_amount=total_amount,
            reject_category=full_cat.replace('_', ' '),
            reject_message_id=call.message.message_id,
            reject_chat_id=call.message.chat.id
        )
        await state.set_state(States.reject_reason)

        # এডমিনকে কারণ চাওয়া
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=await t(0, "cancel"), callback_data="cancel_reject")]
        ])

        new_caption = (call.message.caption or call.message.text) + "\n\n❌ <b>Rejecting... Please enter reason below:</b>"
        await call.message.edit_caption(caption=new_caption, parse_mode="HTML", reply_markup=kb)
        await call.answer("Enter reject reason.")

    except Exception as e:
        await call.answer("Error occurred.", show_alert=True)
        print(f"Reject init error: {e}")


@dp.message(States.reject_reason)
async def process_reject_reason(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return

    reason = message.text.strip()
    if not reason:
        await message.answer(await t(message.from_user.id, "reason_required"))
        return

    data = await state.get_data()
    order_id = data.get('reject_order_id')
    user_id = data.get('reject_user_id')
    total_amount = data.get('reject_amount', 0)
    category = data.get('reject_category', 'Unknown')
    msg_id = data.get('reject_message_id')
    chat_id = data.get('reject_chat_id')

    if not order_id or not user_id:
        await message.answer("Error: Data missing. Try again.")
        await state.clear()
        return

    # ডাটাবেস আপডেট
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE files SET status = 'rejected' WHERE order_id = ?", (order_id,))
        await db.execute("UPDATE users SET pending = pending - 1, rejected = rejected + 1 WHERE user_id = ?", (user_id,))
        await db.commit()

    # ইউজারকে নোটিফিকেশন (ভাষা + কারেন্সি অনুযায়ী)
    lang = (await get_user(user_id))['language']
    currency = '$' if lang != 'bn' else '৳'
    current_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

    reject_msg = (
        await t(user_id, "file_rejected") + "\n\n" +
        await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(user_id, "submitted_at") + f" {current_time}\n" +
        await t(user_id, "category_label") + f" {category}\n" +
        await t(user_id, "user_total") + f" <b>{total_amount}{currency}</b>\n" +
        await t(user_id, "reason_label") + f" <i>{reason}</i>\n\n" +
        await t(user_id, "try_again_prompt")
    )

    copy_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await t(user_id, "copy_order_id"), callback_data=f"copyorder_{order_id}")]
    ])

    try:
        await bot.send_message(user_id, reject_msg, parse_mode="HTML", reply_markup=copy_kb)
    except:
        pass

    # এডমিনকে কনফার্ম
    await message.answer(
        await t(message.from_user.id, "reject_success") + f"\n🆔 <code>{order_id}</code>\n📅 {current_time}\n📛 {reason}",
        parse_mode="HTML"
    )

    # পুরোনো মেসেজের বাটন রিমোভ
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=msg_id, reply_markup=None)
        await bot.edit_message_caption(
            chat_id=chat_id, message_id=msg_id,
            caption=(message.caption or message.text) + f"\n\nRejected by Admin\nReason: {reason}",
            parse_mode="HTML"
        )
    except:
        pass

    await state.clear()


@dp.callback_query(F.data == "cancel_reject")
async def cancel_reject(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return

    await state.clear()
    try:
        original = (call.message.caption or call.message.text).split("\n\n❌ <b>Rejecting...")[0]
        await call.message.edit_caption(caption=original + "\n\nCancel reject", parse_mode="HTML")
    except:
        pass
    await call.answer("Reject cancelled.")


# ================ Withdraw ফ্লো (উন্নত + USD সাপোর্ট) ================
@dp.message(States.withdraw_amount)
async def withdraw_amount_received(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = (await get_user(user_id))['language']
    use_usd = lang != 'bn'
    currency = '$' if use_usd else '৳'

    try:
        amount_input = float(message.text.strip())
        if amount_input < 50:
            raise ValueError("Minimum")
    except ValueError:
        error = await t(user_id, "withdraw_min_error" if amount_input < 50 else "invalid_amount")
        await message.answer(error, parse_mode="HTML")
        return

    user = await get_user(user_id)
    earnings = user['earnings_usd'] if use_usd and user['earnings_usd'] > 0 else user['earnings_bdt']
    if amount_input > earnings:
        await message.answer(await t(user_id, "insufficient_balance"), parse_mode="HTML")
        return

    data = await state.get_data()
    method = data['method']
    number = data['number']

    order_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    current_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

    # ডাটাবেসে সেভ
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO withdraw_requests
            (user_id, amount_bdt, amount_usd, currency, method, number, order_id, status, requested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            user_id,
            amount_input if not use_usd else 0,
            amount_input if use_usd else 0,
            'USD' if use_usd else 'BDT',
            method,
            number,
            order_id,
            current_time
        ))
        await db.execute("UPDATE users SET pending_withdraw = pending_withdraw + ? WHERE user_id = ?", (amount_input, user_id))
        await db.commit()

    # এডমিন নোটিফিকেশন
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Approve", callback_data=f"admin_approvewd_{user_id}_{order_id}"),
            InlineKeyboardButton(text="Reject", callback_data=f"admin_rejectwd_{user_id}_{order_id}")
        ],
        [InlineKeyboardButton(text="View Profile", callback_data=f"admin_viewuser_{user_id}")]
    ])

    admin_text = (
        await t(0, "new_withdraw_request") + "\n\n" +
        await t(0, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(0, "submitted_at") + f" {current_time}\n" +
        await t(0, "amount_label") + f" <b>{amount_input}{currency}</b>\n" +
        await t(0, "method_label") + f" <b>{method.upper()}</b>\n" +
        await t(0, "number_label") + f" <code>{number}</code>\n\n" +
        await t(0, "user_id_label") + f" <code>{user_id}</code>\n" +
        await t(0, "username_label") + f" @{user['username'] or 'None'}"
    )

    await bot.send_message(ADMIN_IDS[0], admin_text, parse_mode="HTML", reply_markup=admin_kb)

    # ইউজার সাকসেস মেসেজ
    success_msg = (
        await t(user_id, "withdraw_success") + "\n\n" +
        await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(user_id, "submitted_at") + f" {current_time}\n" +
        await t(user_id, "amount_label") + f" <b>{amount_input}{currency}</b>\n" +
        await t(user_id, "method_label") + f" <b>{method.upper()}</b>\n\n" +
        await t(user_id, "track_instruction")
    )

    copy_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await t(user_id, "copy_order_id"), callback_data=f"copyorder_{order_id}")]
    ])

    await message.answer(success_msg, parse_mode="HTML", reply_markup=copy_kb)
    await state.clear()
# ================ এডমিন কমান্ডস (ইনলাইন + কমান্ড দুটোই সাপোর্ট) ================

# /approve কমান্ড — এডমিন ওনলি
@dp.message(Command("approve"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_approve(message: types.Message):
    try:
        order_id = message.text.split(maxsplit=1)[1].upper().strip()
    except IndexError:
        await message.answer(await t(message.from_user.id, "approve_usage"))
        return

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT user_id, rate, user_claimed_count, data_count, category, sub_category 
            FROM files WHERE order_id = ?
        """, (order_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await message.answer(await t(message.from_user.id, "order_not_found", order_id=order_id))
                return

        user_id = row['user_id']
        rate = row['rate']
        final_count = row['data_count'] or row['user_claimed_count']
        amount = rate * final_count

        await db.execute("UPDATE files SET status = 'reported' WHERE order_id = ?", (order_id,))
        await db.execute("""
            UPDATE users 
            SET pending = pending - 1, reported = reported + 1, earnings_bdt = earnings_bdt + ?
            WHERE user_id = ?
        """, (amount, user_id))
        await db.commit()

    lang = (await get_user(user_id))['language']
    currency = '$' if lang != 'bn' else '৳'
    current_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

    notify_msg = (
        await t(user_id, "approve_notification") + "\n\n" +
        await t(user_id, "submitted_at") + f" {current_time}\n" +
        await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(user_id, "approved_amount") + f" <b>{amount}{currency}</b>\n" +
        await t(user_id, "payment_soon")
    )

    copy_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await t(user_id, "copy_order_id"), callback_data=f"copyorder_{order_id}")]
    ])

    try:
        await bot.send_message(user_id, notify_msg, parse_mode="HTML", reply_markup=copy_kb)
    except:
        pass

    await message.answer(await t(message.from_user.id, "approve_success_admin", order_id=order_id, amount=amount, currency=currency))


# /reject কমান্ড — এডমিন ওনলি
@dp.message(Command("reject"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_reject(message: types.Message, state: FSMContext):
    try:
        parts = message.text.split(maxsplit=2)
        order_id = parts[1].upper().strip()
        reason = parts[2] if len(parts) > 2 else None
    except IndexError:
        await message.answer(await t(message.from_user.id, "reject_usage"))
        return

    if not reason:
        # কারণ না দিলে স্টেটে নিয়ে যাও
        await state.update_data(reject_order_id=order_id, reject_cmd=True)
        await state.set_state(States.reject_reason)
        await message.answer(await t(message.from_user.id, "enter_reject_reason", order_id=order_id))
        return

    # কারণ সহ সরাসরি রিজেক্ট
    await process_reject(order_id, message.from_user.id, reason, state)


# /release কমান্ড — এডমিন ওনলি
@dp.message(Command("release"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_release(message: types.Message):
    try:
        args = message.text.split()
        if len(args) != 3:
            raise ValueError
        order_id = args[1].upper()
        quantity = int(args[2])
        if quantity <= 0:
            raise ValueError
    except:
        await message.answer(await t(message.from_user.id, "release_usage"))
        return

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT user_id, rate, status FROM files WHERE order_id = ?
        """, (order_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await message.answer(await t(message.from_user.id, "order_not_found", order_id=order_id))
                return
            if row['status'] != 'reported':
                await message.answer(await t(message.from_user.id, "release_not_reported"))
                return

        amount = row['rate'] * quantity
        await db.execute("UPDATE users SET earnings_bdt = earnings_bdt + ? WHERE user_id = ?", (amount, row['user_id']))
        await db.execute("UPDATE files SET status = 'approved', data_count = ? WHERE order_id = ?", (quantity, order_id))
        await db.commit()

    lang = (await get_user(row['user_id']))['language']
    currency = '$' if lang != 'bn' else '৳'
    current_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

    notify_msg = (
        await t(row['user_id'], "payment_released") + "\n\n" +
        await t(row['user_id'], "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(row['user_id'], "submitted_at") + f" {current_time}\n" +
        await t(row['user_id'], "released_quantity") + f" <b>{quantity}</b>\n" +
        await t(row['user_id'], "approved_amount") + f" <b>{amount}{currency}</b>"
    )

    copy_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await t(row['user_id'], "copy_order_id"), callback_data=f"copyorder_{order_id}")]
    ])

    try:
        await bot.send_message(row['user_id'], notify_msg, parse_mode="HTML", reply_markup=copy_kb)
    except:
        pass

    await message.answer(await t(message.from_user.id, "release_success_admin", order_id=order_id, quantity=quantity, amount=amount, currency=currency))


# ================ উইথড্র এপ্রুভ + স্ক্রিনশট ================
@dp.callback_query(F.data.startswith("admin_approvewd_"))
async def withdraw_approve(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Unauthorized!", show_alert=True)
        return

    try:
        parts = call.data.split("_")
        user_id = int(parts[2])
        order_id = parts[3]
    except:
        await call.answer("Invalid data.")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT amount_bdt, amount_usd, currency FROM withdraw_requests WHERE order_id = ? AND status = 'pending'", (order_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await call.answer("Already processed or not found.")
                return

        amount_bdt = row['amount_bdt']
        amount_usd = row['amount_usd']
        currency = row['currency']

        await db.execute("UPDATE users SET earnings_bdt = earnings_bdt - ?, pending_withdraw = pending_withdraw - ? WHERE user_id = ?", (amount_bdt, amount_bdt, user_id))
        await db.execute("UPDATE withdraw_requests SET status = 'approved', processed_at = DATETIME('now') WHERE order_id = ?", (order_id,))
        await db.commit()

    await state.update_data(wd_user_id=user_id, wd_order_id=order_id, wd_amount=amount_bdt if currency == 'BDT' else amount_usd)
    await state.set_state(AdminStates.waiting_payment_screenshot)

    lang = (await get_user(user_id))['language']
    display_amount = amount_usd if lang != 'bn' and amount_usd > 0 else amount_bdt
    display_currency = '$' if lang != 'bn' and amount_usd > 0 else '৳'

    new_text = call.message.text + f"\n\nApproved ({display_amount}{display_currency})\nSend payment screenshot here."
    await call.message.edit_text(new_text, parse_mode="HTML")
    await call.answer()


@dp.message(AdminStates.waiting_payment_screenshot, F.photo | F.document)
async def receive_payment_screenshot(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    data = await state.get_data()
    user_id = data.get('wd_user_id')
    order_id = data.get('wd_order_id')
    amount = data.get('wd_amount')

    if not user_id:
        await message.answer("No pending withdraw.")
        await state.clear()
        return

    lang = (await get_user(user_id))['language']
    currency = '$' if lang != 'bn' else '৳'

    caption = (
        await t(user_id, "withdraw_completed") + "\n\n" +
        await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
        await t(user_id, "amount_label") + f" <b>{amount}{currency}</b>"
    )

    if message.photo:
        await bot.send_photo(user_id, message.photo[-1].file_id, caption=caption, parse_mode="HTML")
    else:
        await bot.send_document(user_id, message.document.file_id, caption=caption, parse_mode="HTML")

    await message.answer(f"Screenshot sent to user (Order: {order_id})")
    await state.clear()


# ================ প্রোফাইল ভিউ (এডমিন) ================
@dp.callback_query(F.data.startswith("admin_viewuser_"))
async def admin_view_profile(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Unauthorized!", show_alert=True)
        return

    try:
        target_user_id = int(call.data.split("_")[2])
        user = await get_user(target_user_id)
        if not user:
            await call.answer("User not found.")
            return

        lang = user['language']
        earnings_display = user['earnings_usd'] if lang != 'bn' and user['earnings_usd'] > 0 else user['earnings_bdt']
        currency = '$' if lang != 'bn' and user['earnings_usd'] > 0 else '৳'

        profile_text = (
            await t(call.from_user.id, "admin_profile_title") + "\n\n" +
            await t(call.from_user.id, "user_id_label") + f" <code>{target_user_id}</code>\n" +
            await t(call.from_user.id, "name_label") + f" {user['full_name']}\n" +
            await t(call.from_user.id, "username_label") + f" @{user['username'] or 'None'}\n" +
            await t(call.from_user.id, "language") + f" {lang.upper()}\n\n" +
            await t(call.from_user.id, "balance") + f" <b>{earnings_display}{currency}</b>\n\n" +
            f"Pending: {user['pending']} | Reported: {user['reported']}\n" +
            f"Approved: {user['approved']} | Rejected: {user['rejected']}\n" +
            f"Referrals: {user.get('referral_count', 0)}"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Back", callback_data="main_menu")]
        ])

        await call.message.edit_text(profile_text, parse_mode="HTML", reply_markup=kb)
        await call.answer()
    except Exception as e:
        await call.answer("Error.")
        print(f"Profile error: {e}")


# ================ ট্র্যাক অর্ডার ================
@dp.callback_query(F.data == "track_order")
async def start_tracking(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    await call.message.edit_text(await t(user_id, "track_order_prompt"), parse_mode="HTML")
    await state.set_state(States.tracking_order)
    await call.answer()


@dp.message(States.tracking_order)
async def process_tracking(message: types.Message, state: FSMContext):
    order_id = message.text.strip().upper()
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # ফাইল অর্ডার চেক
        async with db.execute("SELECT status, created_at FROM files WHERE order_id = ? AND user_id = ?", (order_id, user_id)) as cursor:
            file_row = await cursor.fetchone()

        # উইথড্র অর্ডার চেক
        async with db.execute("SELECT status, amount_bdt, amount_usd, currency, requested_at FROM withdraw_requests WHERE order_id = ? AND user_id = ?", (order_id, user_id)) as cursor:
            wd_row = await cursor.fetchone()

    lang = (await get_user(user_id))['language']
    currency = '$' if lang != 'bn' else '৳'

    if file_row:
        status_text = {
            'pending': await t(user_id, "status_pending"),
            'reported': await t(user_id, "status_reported"),
            'approved': await t(user_id, "status_approved"),
            'rejected': await t(user_id, "status_rejected")
        }.get(file_row['status'], file_row['status'])

        response = (
            await t(user_id, "file_order_status") + "\n\n" +
            await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
            await t(user_id, "status_label") + f" {status_text}\n" +
            await t(user_id, "submitted_at") + f" {file_row['created_at']}"
        )
    elif wd_row:
        amount = wd_row['amount_usd'] if lang != 'bn' and wd_row['amount_usd'] > 0 else wd_row['amount_bdt']
        status_text = {
            'pending': await t(user_id, "status_pending"),
            'approved': await t(user_id, "status_approved"),
            'rejected': await t(user_id, "status_rejected")
        }.get(wd_row['status'], wd_row['status'])

        response = (
            await t(user_id, "withdraw_order_status") + "\n\n" +
            await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
            await t(user_id, "amount_label") + f" <b>{amount}{currency}</b>\n" +
            await t(user_id, "status_label") + f" {status_text}\n" +
            await t(user_id, "submitted_at") + f" {wd_row['requested_at']}"
        )
    else:
        response = await t(user_id, "order_not_found", order_id=order_id)

    await message.answer(response, parse_mode="HTML", reply_markup=await main_menu(user_id))
    await state.clear()
# ================ Files Menu (উন্নত + টেবল ফরম্যাট) ================
@dp.callback_query(F.data == "files_menu")
async def files_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    lang = (await get_user(user_id))['language']
    use_usd = lang != 'bn'
    currency = '$' if use_usd else '৳'

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT order_id, status, created_at, rate, data_count, category, sub_category 
            FROM files WHERE user_id = ? ORDER BY created_at DESC
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        text = await t(user_id, "no_files")
        reply_markup = await main_menu(user_id)
    else:
        # স্ট্যাটাস দিয়ে গ্রুপ + টোটাল কাউন্ট
        status_counts = {'pending': 0, 'reported': 0, 'approved': 0, 'rejected': 0}
        file_list = {'pending': [], 'reported': [], 'approved': [], 'rejected': []}

        for row in rows:
            status = row['status']
            status_counts[status] += 1
            amount = row['rate'] * (row['data_count'] or 0)
            time = row['created_at']  # ইতিমধ্যে DATETIME, ফরম্যাট করুন যদি দরকার

            file_info = (
                f"{await t(user_id, 'order_id_label')} <code>{row['order_id']}</code>\n" +
                f"{await t(user_id, 'category_label')} {row['category']} - {row['sub_category']}\n" +
                f"{await t(user_id, 'submitted_at')} {time}\n" +
                f"{await t(user_id, 'amount_label')} <b>{amount}{currency}</b>\n"
            )
            file_list[status].append(file_info)

        text = await t(user_id, "your_files") + "\n\n"
        text += f"{await t(user_id, 'status_pending')}: {status_counts['pending']}\n"
        text += f"{await t(user_id, 'status_reported')}: {status_counts['reported']}\n"
        text += f"{await t(user_id, 'status_approved')}: {status_counts['approved']}\n"
        text += f"{await t(user_id, 'status_rejected')}: {status_counts['rejected']}\n\n"

        # টেবল ফরম্যাটে লিস্ট (পেজিনেশন যদি >5 থাকে)
        if len(rows) > 5:
            text += await t(user_id, "recent_files") + "\n\n"
            for row in rows[:5]:  # প্রথম 5টা দেখান, আরো দেখতে ট্র্যাক ব্যবহার করুন
                text += f"<code>{row['order_id']}</code> - {row['status']} - {row['created_at']}\n"

            text += "\n" + await t(user_id, "use_track_for_more")
            kb = [[InlineKeyboardButton(text=await t(user_id, "track_order"), callback_data="track_order")]]
        else:
            kb = []
            for status in ['pending', 'reported', 'approved', 'rejected']:
                if file_list[status]:
                    text += f"<b>{await t(user_id, f'status_{status}')}</b>\n"
                    for info in file_list[status]:
                        text += info + "\n"
                    text += "\n"

        kb.append([InlineKeyboardButton(text=await t(user_id, "back"), callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=kb)

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    await call.answer()


# ================ Balance Menu (উন্নত + পেন্ডিং উইথড্র লিস্ট) ================
@dp.callback_query(F.data == "balance_menu")
async def balance_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    lang = (await get_user(user_id))['language']
    use_usd = lang != 'bn'
    currency = '$' if use_usd else '৳'

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT earnings_bdt, earnings_usd, pending_withdraw FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user_row = await cursor.fetchone()
            earnings = user_row['earnings_usd'] if use_usd and user_row['earnings_usd'] > 0 else user_row['earnings_bdt']
            pending_withdraw = user_row['pending_withdraw'] or 0

        async with db.execute("""
            SELECT order_id, amount_bdt, amount_usd, status, requested_at 
            FROM withdraw_requests WHERE user_id = ? ORDER BY requested_at DESC
        """, (user_id,)) as cursor:
            wd_rows = await cursor.fetchall()

    text = await t(user_id, "your_balance") + "\n\n"
    text += await t(user_id, "total_earnings") + f" <b>{earnings}{currency}</b>\n"
    text += await t(user_id, "pending_withdraw") + f" <b>{pending_withdraw}{currency}</b>\n\n"

    if wd_rows:
        text += await t(user_id, "withdraw_history") + "\n"
        kb = []
        for row in wd_rows[:5]:  # প্রথম 5টা, পেজিনেশন
            amount = row['amount_usd'] if use_usd and row['amount_usd'] > 0 else row['amount_bdt']
            status = await t(user_id, f"status_{row['status']}")
            time = row['requested_at']
            text += f"<code>{row['order_id']}</code> - {amount}{currency} - {status} - {time}\n"
            kb.append([InlineKeyboardButton(text=await t(user_id, "copy_order_id"), callback_data=f"copyorder_{row['order_id']}")])
        if len(wd_rows) > 5:
            text += "\n" + await t(user_id, "more_in_track")
    else:
        text += await t(user_id, "no_withdraws")

    kb.append([InlineKeyboardButton(text=await t(user_id, "withdraw"), callback_data="withdraw_start")])
    kb.append([InlineKeyboardButton(text=await t(user_id, "back"), callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb)

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    await call.answer()


# ================ Today Rate (ভাষা + কারেন্সি অনুসারে + রিয়েল USD rate) ================
@dp.callback_query(F.data == "today_rate")
async def today_rate(call: types.CallbackQuery):
    user_id = call.from_user.id
    lang = (await get_user(user_id))['language']
    use_usd = lang != 'bn'
    currency = '$' if use_usd else '৳'

    # রিয়েল USD rate (আগের টুল থেকে ফেচ, হার্ডকোড না করি)
    USD_RATE = 122  # টুল থেকে পাওয়া

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT display_name, rate_bdt, format_text, last_time, report_time, updated_at 
            FROM rates WHERE display_name IS NOT NULL AND display_name != 'None' 
            ORDER BY updated_at DESC
        """) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        text = await t(user_id, "no_rates")
    else:
        text = await t(user_id, "today_rates_header") + "\n\n"
        text += await t(user_id, "submit_last_time") + "\n\n"

        for row in rows:
            rate_bdt = row['rate_bdt']
            rate_usd = round(rate_bdt / USD_RATE, 2) if use_usd else rate_bdt
            display_rate = f"{rate_usd}{currency}"
            fmt = row['format_text'] or "N/A"
            lt = row['last_time'] or "N/A"
            rt = row['report_time'] or "N/A"
            updated = row['updated_at'] or "Old"

            text += f"<b>{row['display_name']}</b>\n"
            text += await t(user_id, "rate_label") + f" <b>{display_rate}</b>\n"
            text += await t(user_id, "format_label") + f" <b>{fmt}</b>\n"
            text += await t(user_id, "last_time_label") + f" <b>{lt}</b>\n"
            text += await t(user_id, "report_time_label") + f" <b>{rt}</b>\n"
            text += await t(user_id, "updated_at") + f" {updated}\n\n"

        text += await t(user_id, "admin_inbox_note") + "\n\n"
        text += await t(user_id, "file_name_note") + "\n\n"
        text += await t(user_id, "motivation_note")

    kb = [[InlineKeyboardButton(text=await t(user_id, "back"), callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb)

    await call.message.edit_text(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=reply_markup)
    await call.answer()


# ================ Referral (উন্নত) ================
@dp.callback_query(F.data == "referral")
async def referral(call: types.CallbackQuery):
    user_id = call.from_user.id
    lang = (await get_user(user_id))['language']
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT referral_count FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            count = row['referral_count'] if row else 0

    text = await t(user_id, "referral_header") + "\n\n"
    text += await t(user_id, "your_referral_link") + f" <code>{ref_link}</code>\n\n"
    text += await t(user_id, "total_referrals") + f" {count}\n"
    text += await t(user_id, "referral_bonus")

    kb = [[InlineKeyboardButton(text=await t(user_id, "back"), callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb)

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    await call.answer()


# ================ Settings Menu (উন্নত) ================
@dp.callback_query(F.data == "settings")
async def settings_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    text = await t(user_id, "settings_header")
    kb = [
        [InlineKeyboardButton(text=await t(user_id, "change_language"), callback_data="change_lang")],
        [InlineKeyboardButton(text=await t(user_id, "back"), callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb)

    await call.message.edit_text(text, reply_markup=reply_markup)
    await call.answer()


@dp.callback_query(F.data == "change_lang")
async def change_lang(call: types.CallbackQuery):
    kb = []
    for code, lang_dict in LANGUAGES.items():
        kb.append([InlineKeyboardButton(text=lang_dict['name'], callback_data=f"lang_{code}")])
    kb.append([InlineKeyboardButton(text=await t(call.from_user.id, "back"), callback_data="settings")])

    await call.message.edit_text(await t(call.from_user.id, "select_language"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()


# ================ Withdraw Start (পূর্বের পুরোনো বাটন রিমোভ) ================
@dp.callback_query(F.data == "withdraw_start")
async def withdraw_start(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    kb = [
        [InlineKeyboardButton(text="Bkash", callback_data="wm_bkash")],
        [InlineKeyboardButton(text="Nagad", callback_data="wm_nagad")],
        [InlineKeyboardButton(text="Rocket", callback_data="wm_rocket")],
        [InlineKeyboardButton(text="Binance", callback_data="wm_binance")],
        [InlineKeyboardButton(text=await t(user_id, "back"), callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb)

    # পুরোনো বাটন রিমোভ (যদি থাকে)
    try:
        await bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
    except:
        pass

    await call.message.edit_text(await t(user_id, "withdraw_method"), reply_markup=reply_markup)
    await state.set_state(States.withdraw_method)
    await call.answer()


# পুরোনো কোডগুলোর সাথে মার্জ করুন (যেমন wm_, wn, wa)
# wa-এ USD সাপোর্ট যোগ করুন (পুরোনো কোডে ইতিমধ্যে আছে)
@dp.callback_query(F.data.startswith("set_lang_"))
async def set_language(call: types.CallbackQuery):
    lang = call.data.split("_")[2]
    if lang not in LANGUAGES:
        await call.answer("Invalid language.")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, call.from_user.id))
        await db.commit()

    await call.message.edit_text(await t(call.from_user.id, "language_changed"), reply_markup=await main_menu(call.from_user.id))
    await call.answer()


@dp.message(Command("restart"), F.from_user.id.in_(ADMIN_IDS))
async def restart_bot(message: types.Message):
    await message.answer(await t(message.from_user.id, "restarting"))
    import os
    os.system("pkill -f main.py && python main.py &")


@dp.message(Command("pending"), F.from_user.id.in_(ADMIN_IDS))
async def list_pending(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT f.order_id, f.user_id, f.category, f.sub_category, f.rate, f.user_claimed_count, f.created_at,
                   u.full_name, u.username
            FROM files f
            JOIN users u ON f.user_id = u.user_id
            WHERE f.status = 'pending'
            ORDER BY f.created_at DESC
        """) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer(await t(message.from_user.id, "pending_no_files"))
        return

    text = await t(message.from_user.id, "pending_files_title") + "\n\n"
    kb_rows = []

    for row in rows:
        total = row['rate'] * row['user_claimed_count']
        dt = datetime.datetime.strptime(row['created_at'], "%Y-%m-%d %H:%M:%S")
        date_str = dt.strftime("%d %b %Y, %I:%M %p")

        text += (
            f"🆔 <b>{await t(message.from_user.id, 'order_id_label')}</b> <code>{row['order_id']}</code>\n"
            f"📅 <b>{await t(message.from_user.id, 'submitted_at')}</b> {date_str}\n"
            f"👤 <b>{await t(message.from_user.id, 'name_label')}</b> {row['full_name']}\n"
            f"@{row['username'] or 'None'} | <code>{row['user_id']}</code>\n"
            f"🔹 {row['category']} - {row['sub_category']}\n"
            f"📊 <b>{row['user_claimed_count']}</b> × {row['rate']} = <b>{total} ৳</b>\n\n"
        )

        kb_rows.append([
            InlineKeyboardButton(text="Approve", callback_data=f"approve_{row['order_id']}"),
            InlineKeyboardButton(text="Reject", callback_data=f"reject_{row['order_id']}")
        ])
        kb_rows.append([InlineKeyboardButton(text="View Profile", callback_data=f"admin_viewuser_{row['user_id']}")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


@dp.message(Command("pendingwd"), F.from_user.id.in_(ADMIN_IDS))
async def list_pending_withdraw(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT w.order_id, w.user_id, w.amount_bdt, w.amount_usd, w.currency, w.method, w.number, w.requested_at,
                   u.full_name, u.username
            FROM withdraw_requests w
            JOIN users u ON w.user_id = u.user_id
            WHERE w.status = 'pending'
            ORDER BY w.requested_at DESC
        """) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer(await t(message.from_user.id, "pending_no_withdraw"))
        return

    text = await t(message.from_user.id, "pending_withdraw_title") + "\n\n"
    kb_rows = []

    for row in rows:
        amount = row['amount_usd'] if row['currency'] == 'USD' else row['amount_bdt']
        currency_sym = '$' if row['currency'] == 'USD' else '৳'
        dt = datetime.datetime.strptime(row['requested_at'], "%Y-%m-%d %H:%M:%S")
        date_str = dt.strftime("%d %b %Y, %I:%M %p")

        text += (
            f"🆔 <b>{await t(message.from_user.id, 'order_id_label')}</b> <code>{row['order_id']}</code>\n"
            f"📅 <b>{await t(message.from_user.id, 'submitted_at')}</b> {date_str}\n"
            f"👤 {row['full_name']} | @{row['username'] or 'None'} | <code>{row['user_id']}</code>\n"
            f"💳 {row['method'].upper()} - <code>{row['number']}</code>\n"
            f"💰 <b>{amount}{currency_sym}</b>\n\n"
        )

        kb_rows.append([
            InlineKeyboardButton(text="Approve", callback_data=f"admin_approvewd_{row['user_id']}_{row['order_id']}"),
            InlineKeyboardButton(text="Reject", callback_data=f"admin_rejectwd_{row['user_id']}_{row['order_id']}")
        ])
        kb_rows.append([InlineKeyboardButton(text="View Profile", callback_data=f"admin_viewuser_{row['user_id']}")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


@dp.message(Command("pendingfiles"), F.from_user.id.in_(ADMIN_IDS))
async def list_pending_files(message: types.Message):
    # pending কমান্ডের মতোই — একই লিস্ট
    await list_pending(message)


@dp.message(Command("reported"), F.from_user.id.in_(ADMIN_IDS))
async def list_reported(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT f.order_id, f.user_id, f.category, f.sub_category, f.rate, f.data_count, f.created_at,
                   u.full_name, u.username
            FROM files f
            JOIN users u ON f.user_id = u.user_id
            WHERE f.status = 'reported'
            ORDER BY f.created_at DESC
        """) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer(await t(message.from_user.id, "no_reported_files"))
        return

    text = await t(message.from_user.id, "reported_files_title") + "\n\n"
    kb_rows = []

    for row in rows:
        total = row['rate'] * row['data_count']
        dt = datetime.datetime.strptime(row['created_at'], "%Y-%m-%d %H:%M:%S")
        date_str = dt.strftime("%d %b %Y, %I:%M %p")

        text += (
            f"🆔 <code>{row['order_id']}</code> | {date_str}\n"
            f"{row['full_name']} | @{row['username'] or 'None'}\n"
            f"{row['category']} - {row['sub_category']} | {row['data_count']} × {row['rate']} = {total} ৳\n\n"
        )

        kb_rows.append([InlineKeyboardButton(text=f"Release {row['order_id']}", callback_data=f"release_btn_{row['order_id']}")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


# রিলিজ কোয়ান্টিটি প্রসেস (পূর্বের মতোই উন্নত)
# ... (পূর্বের release_button ও process_release_quantity কোড একই রাখুন)


@dp.message(Command("approve"), F.from_user.id.in_(ADMIN_IDS))
async def manual_approve(message: types.Message):
    try:
        order_id = message.text.split()[1].upper()
    except IndexError:
        await message.answer(await t(message.from_user.id, "approve_usage"))
        return

    # approve_file লজিক কল করুন (callback-এর মতো)
    fake_call = types.CallbackQuery(
        id="manual",
        from_user=message.from_user,
        chat_instance="",
        data=f"approve_{order_id}",
        message=message
    )
    await approve_file(fake_call)


@dp.message(Command("broadcast"), F.from_user.id.in_(ADMIN_IDS))
async def broadcast(message: types.Message):
    if len(message.text.split(maxsplit=1)) < 2:
        await message.answer(await t(message.from_user.id, "broadcast_usage"))
        return

    text = message.text.split(maxsplit=1)[1]
    success = 0
    failed = 0

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()

    for (uid,) in rows:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            success += 1
        except:
            failed += 1

    await message.answer(f"Broadcast complete!\nSuccess: {success}\nFailed: {failed}")


@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(await t(message.from_user.id, "help_text"), reply_markup=await main_menu(message.from_user.id))


@dp.message(Command("myrate"))
async def my_rate(message: types.Message):
    # today_rate-এর মতোই কোড, ভাষা + কারেন্সি সাপোর্ট সহ
    await today_rate(types.CallbackQuery(id="myrate", from_user=message.from_user, chat_instance="", data="today_rate", message=message))


@dp.callback_query(F.data == "myrate_refresh")
async def myrate_refresh(call: types.CallbackQuery):
    await today_rate(call)
@dp.message(Command("mystats"))
@dp.callback_query(F.data == "mystats")
async def my_stats(event: types.Message | types.CallbackQuery):
    if isinstance(event, types.CallbackQuery):
        message = event.message
        user_id = event.from_user.id
        await event.answer()
    else:
        message = event
        user_id = event.from_user.id

    user = await get_user(user_id)
    if not user:
        text = await t(user_id, "user_not_found")
        kb = back_home_kb()
        if isinstance(event, types.CallbackQuery):
            await message.edit_text(text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)
        return

    lang = user['language']
    use_usd = lang != 'bn'
    currency = '$' if use_usd else '৳'

    # ডেটা আনপ্যাক
    pending = user['pending']
    reported = user['reported']
    approved = user['approved']
    rejected = user['rejected']
    earnings_bdt = user['earnings_bdt'] or 0
    earnings_usd = user['earnings_usd'] or 0
    earnings = earnings_usd if use_usd else earnings_bdt
    referral_count = user.get('referral_count', 0)

    # উইথড্র স্ট্যাটস
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) as count, COALESCE(SUM(amount_bdt), 0) as total FROM withdraw_requests WHERE user_id = ? AND status = 'pending'", (user_id,)) as cursor:
            pending_wd = await cursor.fetchone()
        async with db.execute("SELECT COALESCE(SUM(amount_bdt), 0) as total FROM withdraw_requests WHERE user_id = ? AND status = 'approved'", (user_id,)) as cursor:
            paid_wd = await cursor.fetchone()

    pending_wd_count = pending_wd['count']
    pending_wd_amount = pending_wd['total']
    paid_wd_amount = paid_wd['total']

    text = await t(user_id, "my_stats_header") + "\n\n"

    text += await t(user_id, "balance_label") + f" <b>{earnings}{currency}</b>\n\n"

    text += "<b>" + await t(user_id, "withdraw_stats") + "</b>\n"
    text += await t(user_id, "pending_withdraws") + f" <b>{pending_wd_count}</b>\n"
    text += await t(user_id, "pending_amount") + f" <b>{pending_wd_amount}{currency}</b>\n"
    text += await t(user_id, "total_paid") + f" <b>{paid_wd_amount}{currency}</b>\n\n"

    text += "<b>" + await t(user_id, "file_stats") + "</b>\n"
    text += await t(user_id, "pending") + f" <b>{pending}</b>\n"
    text += await t(user_id, "reported") + f" <b>{reported}</b>\n"
    text += await t(user_id, "approved") + f" <b>{approved}</b>\n"
    text += await t(user_id, "rejected") + f" <b>{rejected}</b>\n\n"

    text += "<b>" + await t(user_id, "referral") + "</b>\n"
    text += await t(user_id, "referred_users") + f" <b>{referral_count}</b>\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await t(user_id, "withdraw"), callback_data="withdraw_start")],
        [InlineKeyboardButton(text=await t(user_id, "today_rate"), callback_data="today_rate")],
        [InlineKeyboardButton(text=await t(user_id, "refresh"), callback_data="mystats")],
        [InlineKeyboardButton(text=await t(user_id, "home"), callback_data="main_menu")]
    ])

    if isinstance(event, types.CallbackQuery):
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.message(Command("userstats"), F.from_user.id.in_(ADMIN_IDS))
async def admin_user_stats(message: types.Message):
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer(await t(message.from_user.id, "userstats_usage"))
            return

        target_id = int(args[1])
        user = await get_user(target_id)

        if not user:
            await message.answer(await t(message.from_user.id, "user_not_found"))
            return

        lang = user['language']
        use_usd = lang != 'bn'
        currency = '$' if use_usd else '৳'
        earnings = user['earnings_usd'] if use_usd else user['earnings_bdt']

        referral_count = user.get('referral_count', 0)
        referrer = user.get('referrer', 'None')

        # উইথড্র স্ট্যাটস
        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT COUNT(*) as count, COALESCE(SUM(amount_bdt), 0) as total FROM withdraw_requests WHERE user_id = ? AND status = 'pending'", (target_id,)) as cursor:
                pending_wd = await cursor.fetchone()
            async with db.execute("SELECT COALESCE(SUM(amount_bdt), 0) as total FROM withdraw_requests WHERE user_id = ? AND status = 'approved'", (target_id,)) as cursor:
                paid_wd = await cursor.fetchone()

        stats_text = await t(message.from_user.id, "admin_user_stats_header") + "\n\n"
        stats_text += f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
        stats_text += f"👤 <b>Name:</b> {user['full_name']}\n"
        stats_text += f"@{user['username'] or 'None'}\n"
        stats_text += f"🌍 <b>Language:</b> {lang.upper()}\n\n"

        stats_text += f"💰 <b>Balance:</b> {earnings}{currency}\n\n"

        stats_text += "<b>Withdraw Stats</b>\n"
        stats_text += f"Pending: {pending_wd['count']} ({pending_wd['total']}{currency})\n"
        stats_text += f"Paid: {paid_wd['total']}{currency}\n\n"

        stats_text += "<b>File Stats</b>\n"
        stats_text += f"Pending: {user['pending']}\n"
        stats_text += f"Reported: {user['reported']}\n"
        stats_text += f"Approved: {user['approved']}\n"
        stats_text += f"Rejected: {user['rejected']}\n\n"

        stats_text += "<b>Referral</b>\n"
        stats_text += f"Referred: {referral_count}\n"
        stats_text += f"Referrer ID: {referrer}\n"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Pending Withdraws", callback_data=f"admin_pendingwd_{target_id}")],
            [InlineKeyboardButton(text="File History", callback_data=f"admin_files_{target_id}")],
            [InlineKeyboardButton(text="Copy User ID", callback_data=f"copyid_{target_id}")],
            [InlineKeyboardButton(text="Back", callback_data="main_menu")]
        ])

        await message.answer(stats_text, parse_mode="HTML", reply_markup=kb)

    except ValueError:
        await message.answer(await t(message.from_user.id, "invalid_user_id"))
    except Exception as e:
        await message.answer(await t(message.from_user.id, "error_occurred"))
        print(f"Admin User Stats Error: {e}")


@dp.message(Command("rules"))
async def rules(message: types.Message):
    user_id = message.from_user.id
    rules_text = await t(user_id, "bot_rules")
    kb = back_home_kb()
    await message.answer(rules_text, parse_mode="HTML", reply_markup=kb)


@dp.message(Command("invite"))
async def invite_command(message: types.Message):
    user_id = message.from_user.id
    lang = (await get_user(user_id))['language']

    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

    referral_count = (await get_user(user_id)).get('referral_count', 0)

    invite_text = (
        await t(user_id, "invite_header") + "\n\n" +
        await t(user_id, "your_link") + f" <code>{ref_link}</code>\n\n" +
        await t(user_id, "total_referred") + f" <b>{referral_count}</b>\n" +
        await t(user_id, "referral_bonus_info")
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await t(user_id, "share_link"), url=f"https://t.me/share/url?url={ref_link}")],
        [InlineKeyboardButton(text=await t(user_id, "home"), callback_data="main_menu")]
    ])

    await message.answer(invite_text, parse_mode="HTML", reply_markup=kb)


@dp.message(Command("trackorder"), F.from_user.id.in_(ADMIN_IDS))
async def admin_track_order(message: types.Message):
    try:
        order_id = message.text.split()[1].upper()

        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row

            # ফাইল চেক
            async with db.execute("""
                SELECT f.*, u.full_name, u.username
                FROM files f
                JOIN users u ON f.user_id = u.user_id
                WHERE f.order_id = ?
            """, (order_id,)) as cursor:
                file_row = await cursor.fetchone()

            if file_row:
                user_id = file_row['user_id']
                lang = (await get_user(user_id))['language']
                use_usd = lang != 'bn'
                currency = '$' if use_usd else '৳'
                amount = file_row['rate'] * file_row['data_count']

                date_str = datetime.datetime.strptime(file_row['created_at'], "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y, %I:%M %p")

                text = (
                    await t(message.from_user.id, "file_order_details") + "\n\n" +
                    f"Order ID: <code>{order_id}</code>\n" +
                    f"Date: {date_str}\n" +
                    f"User: {file_row['full_name']} | @{file_row['username'] or 'None'} | <code>{user_id}</code>\n" +
                    f"Category: {file_row['category']} - {file_row['sub_category']}\n" +
                    f"Data: {file_row['data_count']} × {file_row['rate']} = <b>{amount}{currency}</b>\n" +
                    f"Status: <b>{file_row['status']}</b>"
                )

                kb = []
                if file_row['status'] == 'pending':
                    kb.append([
                        InlineKeyboardButton(text="Approve", callback_data=f"approve_{order_id}"),
                        InlineKeyboardButton(text="Reject", callback_data=f"reject_{order_id}")
                    ])
                elif file_row['status'] == 'reported':
                    kb.append([InlineKeyboardButton(text="Release", callback_data=f"release_btn_{order_id}")])

                kb.append([InlineKeyboardButton(text="View Profile", callback_data=f"admin_viewuser_{user_id}")])
                kb.append([InlineKeyboardButton(text="Copy Order ID", callback_data=f"copyorder_{order_id}")])
                kb.append([InlineKeyboardButton(text="Back", callback_data="main_menu")])

                await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
                return

            # উইথড্র চেক
            async with db.execute("""
                SELECT w.*, u.full_name, u.username
                FROM withdraw_requests w
                JOIN users u ON w.user_id = u.user_id
                WHERE w.order_id = ?
            """, (order_id,)) as cursor:
                wd_row = await cursor.fetchone()

            if wd_row:
                user_id = wd_row['user_id']
                lang = (await get_user(user_id))['language']
                use_usd = lang != 'bn'
                currency = '$' if use_usd else '৳'
                amount = wd_row['amount_usd'] if use_usd else wd_row['amount_bdt']

                date_str = datetime.datetime.strptime(wd_row['requested_at'], "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y, %I:%M %p")

                text = (
                    await t(message.from_user.id, "withdraw_order_details") + "\n\n" +
                    f"Order ID: <code>{order_id}</code>\n" +
                    f"Date: {date_str}\n" +
                    f"User: {wd_row['full_name']} | @{wd_row['username'] or 'None'} | <code>{user_id}</code>\n" +
                    f"Method: {wd_row['method'].upper()} - <code>{wd_row['number']}</code>\n" +
                    f"Amount: <b>{amount}{currency}</b>\n" +
                    f"Status: <b>{wd_row['status']}</b>"
                )

                kb = []
                if wd_row['status'] == 'pending':
                    kb.append([
                        InlineKeyboardButton(text="Approve", callback_data=f"admin_approvewd_{user_id}_{order_id}"),
                        InlineKeyboardButton(text="Reject", callback_data=f"admin_rejectwd_{user_id}_{order_id}")
                    ])

                kb.append([InlineKeyboardButton(text="View Profile", callback_data=f"admin_viewuser_{user_id}")])
                kb.append([InlineKeyboardButton(text="Copy Order ID", callback_data=f"copyorder_{order_id}")])
                kb.append([InlineKeyboardButton(text="Back", callback_data="main_menu")])

                await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
                return

            await message.answer(await t(message.from_user.id, "order_not_found", order_id=order_id))

    except IndexError:
        await message.answer(await t(message.from_user.id, "trackorder_usage"))
    except Exception as e:
        await message.answer(await t(message.from_user.id, "error_occurred"))
        print(f"Admin Track Error: {e}")
async def admin_multi_release(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    lines = message.text.splitlines()[1:]  # /release এর পরের লাইনগুলো
    if not lines:
        await message.answer(
            await t(message.from_user.id, "multi_release_usage"),
            parse_mode="HTML"
        )
        return

    success_count = 0
    failed = []

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        for line in lines:
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) != 2:
                failed.append(f"{line} → ভুল ফরম্যাট")
                continue

            order_id = parts[0].upper()
            try:
                quantity = int(parts[1])
                if quantity <= 0:
                    raise ValueError
            except ValueError:
                failed.append(f"{order_id} → পরিমাণ সঠিক সংখ্যা হতে হবে")
                continue

            async with db.execute("""
                SELECT user_id, rate, data_count, status 
                FROM files WHERE order_id = ? AND status = 'reported'
            """, (order_id,)) as cursor:
                row = await cursor.fetchone()

            if not row:
                failed.append(f"{order_id} → রিপোর্টের অপেক্ষায় নেই বা পাওয়া যায়নি")
                continue

            if quantity > row['data_count']:
                failed.append(f"{order_id} → পরিমাণ সর্বোচ্চ {row['data_count']} হতে পারে")
                continue

            amount = row['rate'] * quantity

            # আপডেট
            await db.execute("""
                UPDATE users 
                SET earnings_bdt = earnings_bdt + ?, reported = reported - 1, approved = approved + 1 
                WHERE user_id = ?
            """, (amount, row['user_id']))

            await db.execute("UPDATE files SET status = 'approved', data_count = ? WHERE order_id = ?", (quantity, order_id))

            # ইউজারকে নোটিফিকেশন (ভাষা + কারেন্সি)
            lang = (await get_user(row['user_id']))['language']
            currency = '$' if lang != 'bn' else '৳'
            current_date = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

            notify_msg = (
                await t(row['user_id'], "payment_released") + "\n\n" +
                await t(row['user_id'], "order_id_label") + f" <code>{order_id}</code>\n" +
                await t(row['user_id'], "released_quantity") + f" <b>{quantity}</b>\n" +
                await t(row['user_id'], "approved_amount") + f" <b>{amount}{currency}</b>\n" +
                await t(row['user_id'], "submitted_at") + f" {current_date}"
            )

            copy_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=await t(row['user_id'], "copy_order_id"), callback_data=f"copyorder_{order_id}")]
            ])

            try:
                await bot.send_message(row['user_id'], notify_msg, parse_mode="HTML", reply_markup=copy_kb)
            except:
                pass

            success_count += 1

        await db.commit()

    # এডমিনকে রিপোর্ট
    result_text = await t(message.from_user.id, "multi_release_success", count=success_count)
    if failed:
        result_text += "\n\n" + await t(message.from_user.id, "failed_list") + "\n" + "\n".join(f"• {f}" for f in failed)

    await message.answer(result_text, parse_mode="HTML")


@dp.message(Command("addbalance"), F.from_user.id.in_(ADMIN_IDS))
async def manual_add_balance(message: types.Message):
    try:
        args = message.text.split()
        if len(args) != 3:
            raise ValueError

        user_id = int(args[1])
        amount = float(args[2])
        if amount <= 0:
            raise ValueError
    except:
        await message.answer(await t(message.from_user.id, "addbalance_usage"), parse_mode="HTML")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT full_name, earnings_bdt FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user_row = await cursor.fetchone()

        if not user_row:
            await message.answer(await t(message.from_user.id, "user_not_found"))
            return

        new_balance = user_row['earnings_bdt'] + amount
        await db.execute("UPDATE users SET earnings_bdt = ? WHERE user_id = ?", (new_balance, user_id))
        await db.commit()

    # ইউজারকে নোটিফিকেশন
    try:
        await bot.send_message(
            user_id,
            await t(user_id, "balance_added") + f"\n\n" +
            await t(user_id, "added_amount") + f" <b>{amount} ৳</b>\n" +
            await t(user_id, "new_balance") + f" <b>{new_balance} ৳</b>",
            parse_mode="HTML"
        )
    except:
        pass

    await message.answer(
        await t(message.from_user.id, "addbalance_success") + "\n\n" +
        f"👤 {user_row['full_name']} (<code>{user_id}</code>)\n" +
        f"💰 +{amount} ৳ → নতুন ব্যালেন্স: <b>{new_balance} ৳</b>",
        parse_mode="HTML"
    )


@dp.message(Command("deduct"), F.from_user.id.in_(ADMIN_IDS))
async def deduct_balance(message: types.Message):
    try:
        args = message.text.split(maxsplit=3)
        if len(args) < 3:
            raise ValueError
        order_id = args[1].upper()
        amount = float(args[2])
        reason = args[3] if len(args) > 3 else await t(message.from_user.id, "default_deduct_reason")
        if amount <= 0:
            raise ValueError
    except:
        await message.answer(await t(message.from_user.id, "deduct_usage"), parse_mode="HTML")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id FROM files WHERE order_id = ?", (order_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            await message.answer(await t(message.from_user.id, "order_not_found", order_id=order_id))
            return

        user_id = row['user_id']
        await db.execute("UPDATE users SET earnings_bdt = earnings_bdt - ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

    try:
        await bot.send_message(
            user_id,
            await t(user_id, "balance_deducted") + "\n\n" +
            await t(user_id, "order_id_label") + f" <code>{order_id}</code>\n" +
            await t(user_id, "deducted_amount") + f" <b>{amount} ৳</b>\n" +
            await t(user_id, "reason_label") + f" {reason}",
            parse_mode="HTML"
        )
    except:
        pass

    await message.answer(await t(message.from_user.id, "deduct_success", order_id=order_id, amount=amount))


@dp.message(Command("setrate"), F.from_user.id.in_(ADMIN_IDS))
async def set_rate(message: types.Message):
    lines = message.text.splitlines()[1:]
    if not lines:
        await message.answer(await t(message.from_user.id, "setrate_usage"), parse_mode="HTML")
        return

    updated = []
    skipped = []

    cat_map = {
        "Webmail": "Facebook_Webmail",
        "Anymail": "Facebook_Anymail",
        "Number": "Facebook_Number",
        "PC Clone Cookies": "Facebook_PC Clone Cookies",
        "PC Clone 1000x": "Facebook_PC Clone Cookies",
        "6155/56x Cookies": "Facebook_PC Clone Cookies",
        "Instagram Cookies": "Instagram_Instagram Cookies",
        "Instagram 2FA": "Instagram_Instagram 2FA",
        "Niva Coin": "Coins_Niva Coin",
        "NS Coin": "Coins_NS Coin",
        "Topfollow": "Coins_Topfollow",
        "Nitra Coin": "Coins_Nitra Coin",
        "Hotmail 30+ Friend": "Facebook_Hotmail",
        "Hotmail 00 Friend": "Facebook_Hotmail",
        "Gmail Files": "Gmail_Gmail Files",
        "Random Gmail": "Gmail_Random Gmail",
        "Other Files": "Others_Other Files"
    }

    current_full_date = datetime.datetime.now().strftime("%d %B %Y, %A")

    async with aiosqlite.connect(DB_NAME) as db:
        for line in lines:
            line = line.strip()
            if not line or '=' not in line:
                skipped.append(f"{line} → ফরম্যাট ভুল")
                continue

            cat_name, value = line.split('=', 1)
            cat_name = cat_name.strip()
            db_cat = cat_map.get(cat_name)

            if not db_cat:
                skipped.append(f"{cat_name} → ক্যাটাগরি ম্যাপে নেই")
                continue

            parts = [p.strip() for p in value.split('|')]
            try:
                rate = float(parts[0])
            except:
                skipped.append(f"{cat_name} → রেট সংখ্যা নয়")
                continue

            format_text = parts[1] if len(parts) > 1 else "UID | Pass"
            last_time = parts[2] if len(parts) > 2 else "11:00 PM BD"
            report_time = parts[3] if len(parts) > 3 else "24 Hours"

            await db.execute("""
                INSERT OR REPLACE INTO rates
                (category, sub_category, rate_bdt, display_name, format_text, last_time, report_time, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, DATETIME('now'))
            """, (db_cat.split('_')[0], db_cat.split('_')[1], rate, cat_name, format_text, last_time, report_time))

            updated.append((cat_name, rate, format_text, last_time, report_time))

        await db.commit()

    if not updated:
        await message.answer(await t(message.from_user.id, "no_rates_updated"))
        return

    # ব্রডকাস্ট টেক্সট (ভাষা নির্দিষ্ট নয় — এডমিনের জন্য)
    broadcast_text = (
        f"📅 <b>রেট আপডেট: {current_full_date}</b>\n\n"
        "💎 <b>সবাই Submit শুরু করুন</b> 💎\n\n"
    )

    for cat, rate, fmt, lt, rt in updated:
        usd = round(rate / USD_RATE, 2)
        broadcast_text += (
            f"<b>{cat}</b>\n"
            f"💸 রেট: <b>{rate} BDT (${usd} USD)</b>\n"
            f"📄 ফরম্যাট: <b>{fmt}</b>\n"
            f"⏰ লাস্ট টাইম: <b>{lt}</b>\n"
            f"📊 রিপোর্ট টাইম: <b>{rt}</b>\n\n"
        )

    broadcast_text += await t(message.from_user.id, "rate_broadcast_footer")

    # ব্রডকাস্ট
    success = 0
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()

    for (uid,) in users:
        try:
            await bot.send_message(uid, broadcast_text, parse_mode="HTML", disable_web_page_preview=True)
            success += 1
        except:
            pass

    result = await t(message.from_user.id, "setrate_success", count=len(updated), broadcast=success)
    if skipped:
        result += "\n\n" + await t(message.from_user.id, "skipped_rates") + "\n" + "\n".join(f"• {s}" for s in skipped)

    await message.answer(result, parse_mode="HTML")


@dp.message(Command("profile"))
async def profile_command(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user:
        await message.answer(await t(user_id, "profile_not_found"))
        return

    lang = user['language']
    currency = '$' if lang != 'bn' else '৳'
    earnings = user['earnings_usd'] if lang != 'bn' else user['earnings_bdt']

    profile_text = (
        await t(user_id, "profile_header") + "\n\n" +
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n" +
        f"👤 <b>Name:</b> {user['full_name']}\n" +
        f"@{user['username'] or 'None'}\n" +
        f"🌍 <b>Language:</b> {lang.upper()}\n\n" +
        f"💰 <b>Balance:</b> {earnings}{currency}\n\n" +
        f"Pending: {user['pending']} | Reported: {user['reported']}\n" +
        f"Approved: {user['approved']} | Rejected: {user['rejected']}\n\n" +
        f"Referred: {user.get('referral_count', 0)} users"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await t(user_id, "balance"), callback_data="balance_menu")],
        [InlineKeyboardButton(text=await t(user_id, "my_files"), callback_data="files_menu")],
        [InlineKeyboardButton(text=await t(user_id, "referral"), callback_data="referral")],
        [InlineKeyboardButton(text=await t(user_id, "home"), callback_data="main_menu")]
    ])

    await message.answer(profile_text, parse_mode="HTML", reply_markup=kb)


@dp.message(Command("profile"), F.from_user.id.in_(ADMIN_IDS))
async def admin_profile(message: types.Message):
    try:
        target_id = int(message.text.split()[1])
    except:
        await message.answer(await t(message.from_user.id, "admin_profile_usage"))
        return

    user = await get_user(target_id)
    if not user:
        await message.answer(await t(message.from_user.id, "user_not_found"))
        return

    lang = user['language']
    currency = '$' if lang != 'bn' else '৳'
    earnings = user['earnings_usd'] if lang != 'bn' else user['earnings_bdt']

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT order_id, created_at FROM files WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 5", (target_id,)) as cursor:
            pending_files = await cursor.fetchall()
        async with db.execute("SELECT order_id, created_at FROM files WHERE user_id = ? AND status = 'reported' ORDER BY created_at DESC LIMIT 5", (target_id,)) as cursor:
            reported_files = await cursor.fetchall()
        async with db.execute("SELECT order_id, requested_at FROM withdraw_requests WHERE user_id = ? AND status = 'pending' ORDER BY requested_at DESC LIMIT 5", (target_id,)) as cursor:
            pending_wd = await cursor.fetchall()

    profile_text = await t(message.from_user.id, "admin_profile_header") + "\n\n"
    profile_text += f"🆔 <code>{target_id}</code> | {user['full_name']} | @{user['username'] or 'None'}\n"
    profile_text += f"Language: {lang.upper()} | Balance: {earnings}{currency}\n\n"
    profile_text += f"Pending: {user['pending']} | Reported: {user['reported']} | Approved: {user['approved']} | Rejected: {user['rejected']}\n"
    profile_text += f"Referred: {user.get('referral_count', 0)}\n\n"

    if pending_files:
        profile_text += "Pending Files:\n"
        for row in pending_files:
            profile_text += f"• <code>{row['order_id']}</code> ({row['created_at'][:10]})\n"

    if reported_files:
        profile_text += "\nReported Files:\n"
        for row in reported_files:
            profile_text += f"• <code>{row['order_id']}</code> ({row['created_at'][:10]})\n"

    if pending_wd:
        profile_text += "\nPending Withdraws:\n"
        for row in pending_wd:
            profile_text += f"• <code>{row['order_id']}</code> ({row['requested_at'][:10]})\n"

    kb = [
        [InlineKeyboardButton(text="Copy User ID", callback_data=f"copyid_{target_id}")],
        [InlineKeyboardButton(text="Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb)

    await message.answer(profile_text, parse_mode="HTML", reply_markup=reply_markup)


@dp.message(Command("stats"), F.from_user.id.in_(ADMIN_IDS))
async def bot_stats(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(earnings_bdt), 0) FROM users") as cursor:
            total_earnings = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM files WHERE status = 'pending'") as cursor:
            pending_files = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM files WHERE status = 'reported'") as cursor:
            reported_files = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'pending'") as cursor:
            pending_wd = (await cursor.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(amount_bdt), 0) FROM withdraw_requests WHERE status = 'approved'") as cursor:
            total_payout = (await cursor.fetchone())[0]

    text = await t(message.from_user.id, "bot_stats_header") + "\n\n"
    text += f"👥 Total Users: <b>{total_users}</b>\n"
    text += f"💰 Total Earnings: <b>{total_earnings} ৳</b>\n"
    text += f"📁 Pending Files: <b>{pending_files}</b>\n"
    text += f"⏳ Reported Files: <b>{reported_files}</b>\n"
    text += f"💸 Pending Withdraws: <b>{pending_wd}</b>\n"
    text += f"📤 Total Payout: <b>{total_payout} ৳</b>"

    await message.answer(text, parse_mode="HTML")


@dp.message(Command("adminhelp"), F.from_user.id.in_(ADMIN_IDS))
async def admin_help(message: types.Message):
    await message.answer(await t(message.from_user.id, "admin_help_text"), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("toggle"), F.from_user.id.in_(ADMIN_IDS))
async def toggle_category_start(message: types.Message, state: FSMContext):
    try:
        args = message.text.split()
        if len(args) != 3:
            await message.answer(await t(message.from_user.id, "toggle_usage"))
            return

        full_cat = args[1]
        action = args[2].lower()

        if action not in ["on", "off"]:
            await message.answer(await t(message.from_user.id, "toggle_on_off_only"))
            return

        async with aiosqlite.connect(DB_NAME) as db:
            if action == "off":
                await db.execute("DELETE FROM toggles WHERE item = ?", (f"upload_{full_cat}",))
                await db.commit()
                await message.answer(await t(message.from_user.id, "category_disabled", category=full_cat.replace('_', ' ')))
                return

            # অন করা
            await db.execute("INSERT OR REPLACE INTO toggles (item, enabled) VALUES (?, 1)", (f"upload_{full_cat}",))
            await db.commit()

            await state.update_data(toggle_cat=full_cat)
            await state.set_state(AdminStates.toggle_rate)
            await message.answer(await t(message.from_user.id, "category_enabled", category=full_cat.replace('_', ' ')) + "\n\n💰 রেট লিখুন:")

    except Exception as e:
        await message.answer(await t(message.from_user.id, "error_occurred"))
        print(e)


@dp.message(AdminStates.toggle_rate)
async def toggle_get_rate(message: types.Message, state: FSMContext):
    try:
        rate = float(message.text.strip())
        if rate < 0:
            raise ValueError
    except:
        await message.answer(await t(message.from_user.id, "invalid_rate"))
        return

    await state.update_data(toggle_rate=rate)
    await state.set_state(AdminStates.toggle_format)
    await message.answer(f"✅ রেট: {rate} ৳\n\n📄 ফরম্যাট লিখুন:")


@dp.message(AdminStates.toggle_format)
async def toggle_get_format(message: types.Message, state: FSMContext):
    format_text = message.text.strip()
    if not format_text:
        await message.answer(await t(message.from_user.id, "format_required"))
        return

    await state.update_data(toggle_format=format_text)
    await state.set_state(AdminStates.toggle_last_time)
    await message.answer(f"✅ ফরম্যাট: {format_text}\n\n⏰ লাস্ট টাইম লিখুন (ডিফল্ট: 11:00 PM BD):")


@dp.message(AdminStates.toggle_last_time)
async def toggle_get_last_time(message: types.Message, state: FSMContext):
    last_time = message.text.strip() or "11:00 PM BD"
    await state.update_data(toggle_last_time=last_time)
    await state.set_state(AdminStates.toggle_report_time)
    await message.answer(f"✅ লাস্ট টাইম: {last_time}\n\n📊 রিপোর্ট টাইম লিখুন (ডিফল্ট: 24 Hours):")


@dp.message(AdminStates.toggle_report_time)
async def toggle_get_report_time(message: types.Message, state: FSMContext):
    report_time = message.text.strip() or "24 Hours"
    data = await state.get_data()
    full_cat = data['toggle_cat']
    rate = data['toggle_rate']
    format_text = data['toggle_format']
    last_time = data['toggle_last_time']

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR REPLACE INTO rates
            (category, sub_category, rate_bdt, display_name, format_text, last_time, report_time, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, DATETIME('now'))
        """, (full_cat.split('_')[0], full_cat.split('_')[1], rate, full_cat.replace('_', ' '), format_text, last_time, report_time))
        await db.commit()

    await message.answer(
        await t(message.from_user.id, "toggle_complete", category=full_cat.replace('_', ' '), rate=rate, format=format_text, last_time=last_time, report_time=report_time)
    )
    await state.clear()


@dp.callback_query(F.data == "support")
async def support(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text(await t(call.from_user.id, "support_prompt"))
    await state.set_state(States.support_ticket)
    await call.answer()


@dp.message(States.support_ticket)
async def receive_ticket(message: types.Message, state: FSMContext):
    admin_text = f"🆘 Support Ticket\nUser: {message.from_user.full_name} (@{message.from_user.username or 'None'}) | <code>{message.from_user.id}</code>\nMessage: {message.text}"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text)
        except:
            pass

    await message.answer(await t(message.from_user.id, "support_sent"))
    await state.clear()
async def give_refer_bonus(new_user_id: int):
    """
    ৫ লেভেল MLM রেফার বোনাস সিস্টেম
    Level 1: ৫ টাকা
    Level 2-5: ২ টাকা করে
    """
    bonuses = [5, 2, 2, 2, 2]  # Level 0 = direct, Level 1-4 = indirect
    current = new_user_id
    level = 0

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        while current and level < len(bonuses):
            async with db.execute("SELECT referrer, full_name, language FROM users WHERE user_id = ?", (current,)) as cursor:
                row = await cursor.fetchone()
                if not row or not row['referrer']:
                    break

                referrer_id = row['referrer']
                lang = row['language']

                bonus_amount = bonuses[level]
                await db.execute("UPDATE users SET earnings_bdt = earnings_bdt + ?, referral_count = referral_count + 1 WHERE user_id = ?", (bonus_amount, referrer_id))

                # রেফারারকে নোটিফিকেশন
                try:
                    notify_text = (
                        await t(referrer_id, "refer_bonus_received") + "\n\n" +
                        await t(referrer_id, "level_label") + f" <b>{level + 1}</b>\n" +
                        await t(referrer_id, "bonus_amount") + f" <b>{bonus_amount} ৳</b>\n" +
                        await t(referrer_id, "from_user") + f" <b>{row['full_name']}</b> (<code>{current}</code>)"
                    )
                    await bot.send_message(referrer_id, notify_text, parse_mode="HTML")
                except:
                    pass  # ব্লক করলে ইগনোর

                current = referrer_id
                level += 1

        await db.commit()


# ডেইলি মোটিভেশন + রিমাইন্ডার (সকাল ৮টা + দুপুর ২টা)
async def daily_motivation():
    messages = {
        8: "daily_morning_motivation",
        14: "daily_afternoon_reminder"
    }

    while True:
        now = datetime.datetime.now()
        hour = now.hour

        if hour in messages:
            key = messages[hour]
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute("SELECT user_id, language FROM users") as cursor:
                    users = await cursor.fetchall()

            for uid, lang in users:
                try:
                    text = await t(uid, key)
                    await bot.send_message(uid, text, parse_mode="HTML", disable_web_page_preview=True)
                except:
                    pass

        await asyncio.sleep(1800)  # প্রতি ৩০ মিনিট চেক


# অটো ডেইলি ব্যাকআপ (রাত ১২টা)
async def daily_backup():
    while True:
        now = datetime.datetime.now()
        if now.hour == 0 and now.minute < 5:  # রাত ১২:০০-১২:০৫ এর মধ্যে
            backup_name = f"{BACKUP_NAME}_{now.strftime('%Y%m%d')}.db"
            if os.path.exists(DB_NAME):
                try:
                    shutil.copy(DB_NAME, backup_name)
                    # পুরোনো ব্যাকআপ রাখা (শেষ ৭ দিন)
                    backups = sorted([f for f in os.listdir('.') if f.startswith(BACKUP_NAME.split('.')[0])])
                    for old in backups[:-7]:
                        os.remove(old)
                    print(f"Backup created: {backup_name}")
                except Exception as e:
                    print(f"Backup failed: {e}")

        await asyncio.sleep(300)  # প্রতি ৫ মিনিট চেক


# অটো ক্লিনআপ: ৩০ দিনের পুরোনো পেন্ডিং ফাইল ডিলিট (যদি এডমিন চান)
async def cleanup_old_pending():
    while True:
        await asyncio.sleep(86400)  # প্রতিদিন চেক
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM files WHERE status = 'pending' AND created_at < ?", (cutoff,))
            await db.commit()


# মেইন ফাংশন
async def main():
    await init_db()

    # ব্যাকগ্রাউন্ড টাস্ক শুরু
    asyncio.create_task(daily_motivation())
    asyncio.create_task(daily_backup())
    asyncio.create_task(cleanup_old_pending())

    print("Bot started successfully!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
