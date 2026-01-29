from pyrogram import Client, filters
from pyrogram.types import Message
import re, time, os
from pathlib import Path

DOWNLOAD_DIR = "BOT/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# def normalize_year(y):
#     y = y.strip()
#     return f"{y}" if len(y) == 2 else y

# def extract_cards(text):
#     all_cards = []
#     for line in text.splitlines():
#         digits = re.findall(r'\d{2,}', line)
#         for i in range(len(digits) - 3):
#             cc, mm, yy, cvv = digits[i:i+4]
#             if 13 <= len(cc) <= 16 and len(mm) <= 2 and len(yy) in [2, 4] and len(cvv) in [3, 4]:
#                 try:
#                     mm = mm.zfill(2)
#                     yyyy = normalize_year(yy)
#                     card = f"{cc}|{mm}|{yyyy}|{cvv}"
#                     all_cards.append(card)
#                     break
#                 except:
#                     continue
#     unique_cards = list(set(all_cards))
#     return all_cards, unique_cards

def normalize_year(y: str) -> str:
    y = y.strip()
    # always return 2-digit year
    if len(y) == 4:
        return y[-2:]
    return y

def extract_cards(text):
    all_cards = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # --- Try CSV-style: Card number, EXP, CVV, ... ---
        # Split by comma; first three fields are safe (later fields may have quotes/commas)
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 3:
            raw_cc = parts[0]
            raw_exp = parts[1]
            raw_cvv = parts[2]

            # Skip header rows
            if raw_cc.lower().startswith("card number"):
                continue

            # Remove trailing .0 / .00 from card field, then strip all non-digits
            raw_cc = re.sub(r'\.0+$', '', raw_cc)
            cc = re.sub(r'\D', '', raw_cc)

            # Extract MM/YY or MM/YYYY
            m = re.match(r'^\s*(\d{1,2})\s*[\/\-\s]\s*(\d{2,4})\s*$', raw_exp)
            cvv = re.sub(r'\D', '', raw_cvv)

            if m and 13 <= len(cc) <= 16 and 3 <= len(cvv) <= 4:
                mm = m.group(1).zfill(2)
                yy = normalize_year(m.group(2))
                card = f"{cc}|{mm}|{yy}|{cvv}"
                all_cards.append(card)
                continue  # done with this line

        # --- Fallback: free-text digit window (old behavior) ---
        digits = re.findall(r'\d{2,}', line)
        for i in range(len(digits) - 3):
            cc, mm, yy, cvv = digits[i:i+4]
            if 13 <= len(cc) <= 16 and len(mm) <= 2 and len(yy) in [2, 4] and len(cvv) in [3, 4]:
                try:
                    mm = mm.zfill(2)
                    yy = normalize_year(yy)
                    card = f"{cc}|{mm}|{yy}|{cvv}"
                    all_cards.append(card)
                    break
                except:
                    continue

    unique_cards = list(set(all_cards))
    return all_cards, unique_cards


def get_next_filename():
    base_name = "Christopher-Filtered-"
    existing_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.startswith(base_name) and f.endswith(".txt")]
    if not existing_files:
        return os.path.join(DOWNLOAD_DIR, f"{base_name}0001.txt")
    numbers = [int(f[len(base_name):-4]) for f in existing_files]
    next_num = max(numbers) + 1
    return os.path.join(DOWNLOAD_DIR, f"{base_name}{next_num:04d}.txt")

@Client.on_message(filters.command("fl") & filters.reply)
async def filter_cards(client, message: Message):
    start = time.time()
    reply = message.reply_to_message
    text = ""

    # Send initial placeholder message
    status_msg = await message.reply("<pre>- - -</pre>")

    if reply.document:
        filename = reply.document.file_name
        base, ext = os.path.splitext(filename)

        unique_filename = filename
        counter = 1
        while os.path.exists(os.path.join(DOWNLOAD_DIR, unique_filename)):
            unique_filename = f"{base}_{counter}{ext}"
            counter += 1

        file_path = await reply.download(file_name=os.path.join(DOWNLOAD_DIR, unique_filename))

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

    elif reply.text:
        text = reply.text

    else:
        await status_msg.edit("⚠️ Unsupported message. Please reply to a text or text file.")
        return

    all_cards, unique_cards = extract_cards(text)
    total_cards = len(all_cards)
    unique_count = len(unique_cards)
    duplicates = total_cards - unique_count
    end = time.time()

    if unique_count == 0:
        await status_msg.edit("⚠️ No valid CCs found in this file or message.")
        return

    timetaken = round(end - start, 2)

    if reply.document:
        caption = (
            f"• <b>Total CC :</b> <code>{total_cards}</code>\n"
            f"• <b>Duplicate Remove :</b> <code>{duplicates}</code>\n"
            f"• <b>Unique CC :</b> <code>{unique_count}</code>\n"
            f"• <b>T/t :</b> <code>{timetaken} sec</code>\n"
            f"• <b>Req By :</b> <a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"
        )

        filtered_file_path = get_next_filename()
        with open(filtered_file_path, "w") as f:
            f.write("\n".join(unique_cards))

        os.remove(file_path)

        await status_msg.delete()
        await message.reply_document(
            document=filtered_file_path,
            file_name=Path(filtered_file_path).name,
            caption=caption,
            reply_to_message_id=message.id,
        )

    else:
        # For text input: just edit with cards only, no caption/summary
        cards_text = "\n".join(unique_cards)
        await status_msg.edit(f"<code>{cards_text}</code>")
