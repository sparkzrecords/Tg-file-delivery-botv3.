from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading, time, io

# ================= CONFIG =================

BOT_TOKEN = "8462931483:AAFKHd5XHB71XRdejOy-SJFM87Mko1ya0YA"
BOT_USERNAME = "Workzinwbot"

OWNER_ID = 8005808151
ADMINS = set()

INDEX_CHANNEL_ID = -1003713546208
INDEX_FILENAME = "index.txt"

KEYS_CHANNEL_ID = -1003745229983  # <-- your private keys channel
KEYS_FILENAME = "edit_keys.txt"

BRAND_IMAGE_FILE_ID = "AgACAgUAAxkBAAICTWmFc-5xFyQasMOcQe01fjy0QNsrAALfDWsb1vExVNgtspi4niWXAQADAgADeQADOAQ"

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ================= POST TARGETS =================

POST_TARGETS = {
    "sparkz":  {"id": -1003751113967},
    "network": {"id": -1003584561836},
    "manga":   {"id": -1003354289051},
    "parody":  {"id": -1003890422953},
}

# ================= PRIVATE INGEST =================

PRIVATE_CHANNEL_IDS = {
    -1003202127622,
    -1003397027756,
    -1003430467044,
}

# ================= FILE SPACE ADMIN =================

@bot.message_handler(commands=["filespace"])
def file_space(m):
    if not is_admin(m.from_user.id):
        return

    parts = m.text.split()
    if len(parts) < 2:
        bot.reply_to(
            m,
            "📦 *File Space Manager*\n\n"
            "`/filespace add -100xxxxxxxxx`\n"
            "`/filespace remove -100xxxxxxxxx`\n"
            "`/filespace list`",
            parse_mode="Markdown"
        )
        return

    action = parts[1].lower()

    if action == "list":
        if not PRIVATE_CHANNEL_IDS:
            bot.reply_to(m, "🚫 No storage channels configured")
            return

        text = "📦 *Active Storage Channels:*\n\n"
        text += "\n".join(f"`{cid}`" for cid in PRIVATE_CHANNEL_IDS)
        bot.reply_to(m, text, parse_mode="Markdown")
        return

    if len(parts) != 3:
        bot.reply_to(m, "❌ Invalid format")
        return

    try:
        cid = int(parts[2])
    except ValueError:
        bot.reply_to(m, "❌ Invalid channel ID")
        return

    if action == "add":
        PRIVATE_CHANNEL_IDS.add(cid)
        bot.reply_to(m, f"✅ Added storage channel:\n`{cid}`", parse_mode="Markdown")

    elif action == "remove":
        if cid in PRIVATE_CHANNEL_IDS:
            PRIVATE_CHANNEL_IDS.remove(cid)
            bot.reply_to(m, f"✅ Removed storage channel:\n`{cid}`", parse_mode="Markdown")
        else:
            bot.reply_to(m, "❌ Channel not found")

    else:
        bot.reply_to(m, "❌ Unknown action")

# ================= STORAGE =================

FILES = {}
UPLOAD_BUFFER = []
SEEN_FILE_IDS = set()

# ================= EDIT PRESETS =================

EDIT_PRESETS = {}   # editkey -> {"image": ..., "caption": ...}

POST_DRAFT = {
    "active": False,
    "editkey": None,
    "image": None,
    "caption": None
}

# ================= COOLDOWNS =================

REFRESH_COOLDOWN = {}
SEND_COOLDOWN = {}

REFRESH_COOLDOWN_SECONDS = 7
SEND_COOLDOWN_SECONDS = 10

# ================= STATS =================

STATS = {
    "drops_sent": 0,
    "unique_users": set(),
    "blocked_requests": 0,
    "refresh_clicks": 0,
    "cooldown_hits": 0,
}


# ================= SUB CHANNELS =================

SUB_CHANNELS = {
    "@sparkzanime": {"id": -1003751113967, "link": "https://t.me/sparkzanime"},
    "@hanimenetwork5": {"id": -1003584561836, "link": "https://t.me/hanimenetwork5"},
}

# ================= DYNAMIC SUB2UNLOCK ADMIN =================

@bot.message_handler(commands=["subadd"])
def sub_add(m):
    if not is_admin(m.from_user.id):
        return

    parts = m.text.split()
    if len(parts) != 3:
        bot.reply_to(m, "Usage: /subadd @channel -100xxxxxxxxx")
        return

    username = parts[1]
    try:
        cid = int(parts[2])
    except ValueError:
        bot.reply_to(m, "❌ Invalid channel id")
        return

    SUB_CHANNELS[username] = {
        "id": cid,
        "link": f"https://t.me/{username.lstrip('@')}"
    }

    bot.reply_to(m, f"✅ Added to sub-lock: {username}")


@bot.message_handler(commands=["subremove"])
def sub_remove(m):
    if not is_admin(m.from_user.id):
        return

    parts = m.text.split()
    if len(parts) != 2:
        bot.reply_to(m, "Usage: /subremove @channel")
        return

    removed = SUB_CHANNELS.pop(parts[1], None)
    bot.reply_to(
        m,
        f"✅ Removed {parts[1]}" if removed else "❌ Channel not found"
    )


@bot.message_handler(commands=["sublist"])
def sub_list(m):
    if not is_admin(m.from_user.id):
        return

    if not SUB_CHANNELS:
        bot.reply_to(m, "🚫 No sub-to-unlock channels set")
        return

    text = "📢 *Sub-to-Unlock Channels:*\n\n" + "\n".join(SUB_CHANNELS.keys())
    bot.reply_to(m, text, parse_mode="Markdown")

# ================= AUTH =================

def is_admin(uid):
    return uid == OWNER_ID or uid in ADMINS

@bot.message_handler(commands=["stats"])
def stats(m):
    if not is_admin(m.from_user.id):
        return

    text = (
        "📊 *SparkzAnime Stats*\n\n"
        f"📦 Drops sent: `{STATS['drops_sent']}`\n"
        f"👤 Unique users: `{len(STATS['unique_users'])}`\n"
        f"🚫 Blocked requests: `{STATS['blocked_requests']}`\n"
        f"🔄 Refresh clicks: `{STATS['refresh_clicks']}`\n"
        f"⏳ Cooldown hits: `{STATS['cooldown_hits']}`"
    )

    bot.send_message(m.chat.id, text, parse_mode="Markdown")

# ================= UTIL =================

def auto_delete(chat_id, msg_ids, delay=900):
    def task():
        time.sleep(delay)
        for mid in msg_ids:
            try:
                bot.delete_message(chat_id, mid)
            except:
                pass
    threading.Thread(target=task, daemon=True).start()

# ================= INDEX SNAPSHOT =================

def generate_index_text():
    lines = [
        "# SparkzAnime Index Snapshot",
        f"# keys={len(FILES)}",
        f"# generated={int(time.time())}",
        ""
    ]
    for key, fids in FILES.items():
        lines.append(f"[{key}]")
        lines.extend(fids)
        lines.append("")
    return "\n".join(lines)

def upload_index_snapshot():
    bio = io.BytesIO(generate_index_text().encode("utf-8"))
    bio.name = INDEX_FILENAME
    bot.send_document(INDEX_CHANNEL_ID, bio, caption="📦 index snapshot")

# ================= INDEX RESTORE =================

@bot.message_handler(commands=["restore"])
def restore_index(m):
    if not is_admin(m.from_user.id) or m.chat.type != "private":
        return

    if not m.reply_to_message or not m.reply_to_message.document:
        bot.reply_to(m, "❌ Reply to an index.txt file")
        return

    raw = bot.download_file(
        bot.get_file(m.reply_to_message.document.file_id).file_path
    )

    text = raw.decode("utf-8", errors="ignore")
    restored, current = {}, None

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            restored[current] = []
        elif current:
            restored[current].append(line)

    FILES.clear()
    FILES.update(restored)

    bot.reply_to(
        m,
        "✅ Index restored\n" +
        "\n".join(f"- {k} ({len(v)})" for k, v in FILES.items())
    )

# ================= EDIT PRESET BACKUP =================

def save_edit_preset_to_channel(editkey, image, caption):
    """
    Save one edit preset as a text file to the keys channel.
    """

    lines = [
        f"[edit:{editkey}]",
        f"image={image if image else 'SKIP'}",
        f"caption={caption if caption else 'SKIP'}",
        ""
    ]

    text = "\n".join(lines)

    bio = io.BytesIO(text.encode("utf-8"))
    bio.name = KEYS_FILENAME

    bot.send_document(
        KEYS_CHANNEL_ID,
        bio,
        caption=f"🗝 Edit preset saved: {editkey}"
    )

# ================= SUB CHECK =================

def get_missing_channels(uid):
    missing = []
    for ch in SUB_CHANNELS.values():
        try:
            m = bot.get_chat_member(ch["id"], uid)
            if m.status not in ("member", "administrator", "creator"):
                missing.append(ch)
        except:
            missing.append(ch)
    return missing

def send_sub_buttons(chat_id, missing, key):
    kb = InlineKeyboardMarkup(row_width=1)
    for ch in missing:
        kb.add(InlineKeyboardButton("📢 Subscribe", url=ch["link"]))
    kb.add(InlineKeyboardButton("🔄 Refresh Access", callback_data=f"refresh:{key}"))
    bot.send_message(chat_id, "🔒 Access locked", reply_markup=kb)

# ================= INGEST =================

@bot.channel_post_handler(content_types=["document", "video", "photo", "audio"])
def ingest_file(m):
    if m.chat.id not in PRIVATE_CHANNEL_IDS:
        return

    fid = (
        m.document.file_id if m.document else
        m.video.file_id if m.video else
        m.photo[-1].file_id if m.photo else
        m.audio.file_id
    )

    if fid in SEEN_FILE_IDS:
        return

    SEEN_FILE_IDS.add(fid)
    UPLOAD_BUFFER.append(fid)

@bot.channel_post_handler(content_types=["text"])
def bind_key(m):
    if m.chat.id not in PRIVATE_CHANNEL_IDS:
        return
    if not UPLOAD_BUFFER:
        return

    key = m.text.strip().lower().replace(" ", "_")

    FILES.setdefault(key, []).extend(UPLOAD_BUFFER)
    UPLOAD_BUFFER.clear()

    # 🔐 ALWAYS persist first
    upload_index_snapshot()

    # 🧾 confirmation to owner only
    bot.send_message(
        OWNER_ID,
        f"✅ Saved `{key}` ({len(FILES[key])} files)",
        parse_mode="Markdown"
    )

# ================= DELIVERY =================

def send_files(chat_id, key):
    now = time.time()
    last = SEND_COOLDOWN.get((chat_id, key), 0)

    if now - last < SEND_COOLDOWN_SECONDS:
        STATS["cooldown_hits"] += 1
        bot.send_message(chat_id, "⏳ Please wait before requesting again")
        return

    SEND_COOLDOWN[(chat_id, key)] = now

    if key not in FILES:
        bot.send_message(chat_id, "❌ Invalid or expired key")
        return

    sent = [
        bot.send_photo(
            chat_id,
            BRAND_IMAGE_FILE_ID,
            caption="⚡ SPARKZANIME DROP ⚡\n⏳ Auto-delete in 15 min"
        ).message_id
    ]

    for fid in FILES[key]:
        sent.append(bot.send_document(chat_id, fid).message_id)

    auto_delete(chat_id, sent)

# ================= START =================

@bot.message_handler(commands=["start"])
def start(m):
    parts = m.text.split(maxsplit=1)

    # Case 1: plain /start (no key)
    if len(parts) < 2:
        bot.send_message(
            m.chat.id,
            """🎬 Welcome to Sparkzanime Download Hub

Use links shared in our Telegram channels to get anime files.
New users coming from YouTube can start from here 👇

📢 Stay updated:
->open this channel and search for Anime you want
@sparkzanime
"""
        )
        return

    # Case 2: /start <key>
    key = parts[1].strip().lower()
    uid = m.from_user.id

    missing = get_missing_channels(uid)

    if missing:
        send_sub_buttons(m.chat.id, missing, key)
    else:
        send_files(m.chat.id, key)

# ================= REFRESH =================

@bot.callback_query_handler(func=lambda c: c.data.startswith("refresh:"))
def refresh(c):
    key = c.data.split(":", 1)[1]
    uid = c.from_user.id

    now = time.time()
    last = REFRESH_COOLDOWN.get((uid, key), 0)

    if now - last < REFRESH_COOLDOWN_SECONDS:
        bot.answer_callback_query(c.id, "⏳ Slow down")
        return

    REFRESH_COOLDOWN[(uid, key)] = now
    missing = get_missing_channels(uid)

    if missing:
        send_sub_buttons(c.message.chat.id, missing, key)
    else:
        bot.answer_callback_query(c.id, "✅ Access granted")
        send_files(c.message.chat.id, key)


# ================= EDIT PRESET FLOW =================

@bot.message_handler(commands=["edit"])
def edit(m):
    if not is_admin(m.from_user.id):
        return

    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(m, "❌ Usage: /edit <editkey>")
        return

    editkey = parts[1].strip().lower()

    POST_DRAFT["active"] = True
    POST_DRAFT["editkey"] = editkey
    POST_DRAFT["image"] = None
    POST_DRAFT["caption"] = None

    bot.reply_to(
        m,
        f"🖼 Editing preset `{editkey}`\nSend image or /skip",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["skip"])
def skip(m):
    if not POST_DRAFT["active"]:
        return

    # 1️⃣ skip image → ask caption
    if POST_DRAFT["image"] is None:
        POST_DRAFT["image"] = "SKIP"
        bot.reply_to(m, "✍️ Send caption or /skip")
        return

    # 2️⃣ skip caption → finalize
    POST_DRAFT["caption"] = "SKIP"
    finalize_edit_preset(m)


@bot.message_handler(commands=["cancel"])
def cancel(m):
    POST_DRAFT["active"] = False
    POST_DRAFT["editkey"] = None
    POST_DRAFT["image"] = None
    POST_DRAFT["caption"] = None

    bot.reply_to(m, "❌ Cancelled")


@bot.message_handler(content_types=["photo"])
def edit_image(m):
    if not POST_DRAFT["active"]:
        return
    if POST_DRAFT["image"] is not None:
        return

    POST_DRAFT["image"] = m.photo[-1].file_id
    bot.reply_to(m, "✍️ Send caption or /skip")


@bot.message_handler(func=lambda m: POST_DRAFT["active"] and POST_DRAFT["caption"] is None)
def edit_caption(m):
    POST_DRAFT["caption"] = m.text
    finalize_edit_preset(m)


# ================= FINALIZE EDIT PRESET =================

def finalize_edit_preset(m):
    editkey = POST_DRAFT["editkey"]

    EDIT_PRESETS[editkey] = {
        "image": POST_DRAFT["image"],
        "caption": POST_DRAFT["caption"]
    }

    # 🔐 backup to private keys channel
    save_edit_preset_to_channel(
        editkey,
        POST_DRAFT["image"],
        POST_DRAFT["caption"]
    )

    POST_DRAFT["active"] = False
    POST_DRAFT["editkey"] = None
    POST_DRAFT["image"] = None
    POST_DRAFT["caption"] = None

    bot.reply_to(
        m,
        f"✅ Saved edit preset `{editkey}`",
        parse_mode="Markdown"
    )


# ================= SAVE PRESET =================

def save_edit_preset(m):
    editkey = POST_DRAFT["editkey"]

    EDIT_PRESETS[editkey] = {
        "image": POST_DRAFT["image"],
        "caption": POST_DRAFT["caption"]
    }

    POST_DRAFT.update({
        "active": False,
        "editkey": None,
        "image": None,
        "caption": None
    })

    bot.reply_to(
        m,
        f"✅ Saved edit preset `{editkey}`",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["post"])
def post(m):
    if not is_admin(m.from_user.id):
        return

    parts = m.text.split()[1:]
    if not parts:
        bot.reply_to(m, "❌ No arguments")
        return

    targets = []
    bindings = []

    # separate targets and bindings
    for p in parts:
        if p in POST_TARGETS:
            targets.append(p)
        else:
            bindings.append(p)

    if not targets or not bindings:
        bot.reply_to(m, "❌ Missing target or bindings")
        return

    valid_blocks = []

    for raw in bindings:
        # expected: editkey:filekey=label
        if "=" not in raw or ":" not in raw:
            continue

        left, label = raw.split("=", 1)
        editkey, filekey = left.split(":", 1)

        editkey = editkey.strip().lower()
        filekey = filekey.strip().lower()
        label = label.strip()

        if editkey not in EDIT_PRESETS:
            continue
        if filekey not in FILES:
            continue

        valid_blocks.append({
            "editkey": editkey,
            "filekey": filekey,
            "label": label
        })

    if not valid_blocks:
        bot.reply_to(m, "❌ No valid bindings")
        return

    for t in targets:
        for block in valid_blocks:
            preset = EDIT_PRESETS[block["editkey"]]

            caption = (
                preset["caption"]
                if preset["caption"] not in (None, "SKIP")
                else "🔥 New Drop 🔥"
            )

            image = (
                preset["image"]
                if preset["image"] not in (None, "SKIP")
                else None
            )

            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(
                InlineKeyboardButton(
                    block["label"].upper(),
                    url=f"https://t.me/{BOT_USERNAME}?start={block['filekey']}"
                )
            )

            if image:
                bot.send_photo(
                    POST_TARGETS[t]["id"],
                    image,
                    caption=caption,
                    reply_markup=kb
                )
            else:
                bot.send_message(
                    POST_TARGETS[t]["id"],
                    caption,
                    reply_markup=kb
                )

    bot.reply_to(m, "✅ Posted")


# ================= DYNAMIC POST TARGET ADMIN =================

@bot.message_handler(commands=["postadd"])
def post_add(m):
    if not is_admin(m.from_user.id):
        return

    parts = m.text.split()
    if len(parts) != 3:
        bot.reply_to(m, "Usage: /postadd key -100xxxxxxxxx")
        return

    key = parts[1].lower()
    try:
        cid = int(parts[2])
    except ValueError:
        bot.reply_to(m, "❌ Invalid channel id")
        return

    POST_TARGETS[key] = {"id": cid}
    bot.reply_to(m, f"✅ Added post target `{key}`", parse_mode="Markdown")


@bot.message_handler(commands=["postremove"])
def post_remove(m):
    if not is_admin(m.from_user.id):
        return

    parts = m.text.split()
    if len(parts) != 2:
        bot.reply_to(m, "Usage: /postremove key")
        return

    removed = POST_TARGETS.pop(parts[1].lower(), None)
    bot.reply_to(
        m,
        f"✅ Removed `{parts[1]}`" if removed else "❌ Key not found",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["postlist"])
def post_list(m):
    if not is_admin(m.from_user.id):
        return

    if not POST_TARGETS:
        bot.reply_to(m, "🚫 No post targets configured")
        return

    text = "📢 *Post Targets:*\n\n" + "\n".join(
        f"- `{k}` → `{v['id']}`" for k, v in POST_TARGETS.items()
    )

    bot.reply_to(m, text, parse_mode="Markdown")

# ================= WEBHOOK =================

@app.route("/webhook", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(
        request.get_data().decode("utf-8", errors="ignore")
    )
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def home():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
