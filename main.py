import os
import asyncio
import signal
import traceback
import pytesseract
import logging
import sys
import re
from PIL import Image
from pyrogram import Client, filters
from pyrogram.types import Message
from playwright.async_api import async_playwright

# --- 1. LOGLAMA ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BorsaMatrisi")
sys.stdout.reconfigure(line_buffering=True)

pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

# --- 2. AYARLAR ---
API_ID      = int(os.environ.get("API_ID", 0))
API_HASH    = os.environ.get("API_HASH", "")
BOT_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
SESSION_STR = os.environ.get("SESSION_STRING", "")
TARGET_BOT  = "ucretsizderinlikbot"

# --- 3. CLIENT'LAR ---
user_app = Client(
    "userbot",
    session_string=SESSION_STR,
    api_id=API_ID,
    api_hash=API_HASH
)
bot_app = Client(
    "mainbot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH
)

# --- 4. OCR PARSE ---
def parse_ocr_table(text):
    buyers  = []
    sellers = []
    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = re.search(
            r'([A-Za-zÇçĞğİıÖöŞşÜü][A-Za-zÇçĞğİıÖöŞşÜü0-9\.\s\-]+?)\s+'
            r'%?([\d]+[.,][\d]+)\s+'
            r'(-?[\d]+[.,][\d]+)\s+'
            r'([\d]+[.,][\d]+)',
            line
        )
        if match:
            kurum   = match.group(1).strip()
            oran    = match.group(2).replace(",", ".")
            lot     = match.group(3).replace(",", ".")
            maliyet = match.group(4).replace(",", ".")
            row = {"kurum": kurum, "oran": oran, "lot": lot, "maliyet": maliyet}
            if float(lot) >= 0:
                buyers.append(row)
            else:
                sellers.append(row)
    return buyers, sellers


def process_ocr(image_path):
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang="tur+eng")
    logger.info(f"📄 OCR ham metin:\n{text[:500]}")
    buyers, sellers = parse_ocr_table(text)

    if not buyers and not sellers:
        logger.warning("⚠️ İlk OCR parse başarısız, görsel büyütülüp tekrar deneniyor...")
        w, h = img.size
        img2 = img.resize((w * 2, h * 2), Image.LANCZOS)
        text2 = pytesseract.image_to_string(img2, lang="tur+eng")
        logger.info(f"📄 2. OCR ham metin:\n{text2[:500]}")
        buyers, sellers = parse_ocr_table(text2)

    logger.info(f"✅ Parse — Alıcı: {len(buyers)}, Satıcı: {len(sellers)}")
    return buyers, sellers


# --- 5. HTML ŞABLON ---
def build_rows(rows, is_buyer):
    html = ""
    for i, r in enumerate(rows):
        lot_val = r["lot"]
        if is_buyer:
            lot_color = "#0077cc"
        else:
            lot_color = "#cc0000"
            if not lot_val.startswith("-"):
                lot_val = f"-{lot_val}"
        bg = "#f7fffe" if is_buyer else "#fff7f7"
        alt = "#edfdf5" if is_buyer else "#fdedef"
        row_bg = bg if i % 2 == 0 else alt

        # DIĞERsatırını soluk yap
        diger = r["kurum"].upper().strip() == "DIĞER" or r["kurum"].upper().strip() == "DİĞER"
        style = "opacity:0.55;" if diger else ""

        html += f"""
        <tr style="background:{row_bg};{style}">
            <td style="font-weight:{'600' if not diger else '400'}">{r['kurum']}</td>
            <td style="color:#d97b00;font-weight:700;">%{r['oran']}</td>
            <td style="color:{lot_color};font-weight:700;">{lot_val}</td>
            <td style="color:#444;">{r['maliyet']}</td>
        </tr>"""
    return html


async def generate_premium_image(hisse_kodu, buyers, sellers):
    buyer_rows  = build_rows(buyers,  is_buyer=True)
    seller_rows = build_rows(sellers, is_buyer=False)

    no_data = '<tr><td colspan="4" style="text-align:center;color:#bbb;padding:18px;font-size:13px;">Veri bulunamadı</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head><meta charset="UTF-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background: #f4f6f9;
    font-family: 'Segoe UI', Arial, sans-serif;
    width: 720px;
    padding: 24px 24px 18px 24px;
  }}

  /* BAŞLIK */
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    margin-bottom: 18px;
    padding-bottom: 14px;
    border-bottom: 2px solid #e0e0e0;
  }}
  .hisse {{
    font-size: 42px;
    font-weight: 900;
    color: #0a0a0a;
    letter-spacing: 3px;
    line-height: 1;
  }}
  .meta {{
    text-align: right;
    font-size: 12px;
    color: #888;
    line-height: 1.7;
  }}
  .meta .title {{ font-size: 14px; font-weight: 700; color: #333; letter-spacing:1px; }}
  .meta .brand {{ font-size: 13px; font-weight: 700; color: #0077cc; }}

  /* KART */
  .card {{
    border-radius: 14px;
    overflow: hidden;
    margin-bottom: 18px;
    box-shadow: 0 3px 16px rgba(0,0,0,0.09);
  }}
  .card-buyer  {{ border: 2.5px solid #27ae60; }}
  .card-seller {{ border: 2.5px solid #e74c3c; }}

  /* KART BAŞLIĞI */
  .card-head {{
    padding: 11px 18px;
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 1.2px;
    color: #fff;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .card-buyer  .card-head {{ background: linear-gradient(90deg, #1e8449, #27ae60, #2ecc71); }}
  .card-seller .card-head {{ background: linear-gradient(90deg, #a93226, #c0392b, #e74c3c); }}

  /* TABLO */
  table {{ width:100%; border-collapse:collapse; }}
  thead tr {{ background: #ececec; }}
  thead th {{
    padding: 8px 14px;
    text-align: left;
    font-size: 11px;
    font-weight: 700;
    color: #666;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    border-bottom: 1px solid #ddd;
  }}
  tbody td {{
    padding: 10px 14px;
    font-size: 14px;
    border-bottom: 1px solid rgba(0,0,0,0.05);
  }}
  tbody tr:last-child td {{ border-bottom: none; }}

  /* ALT BİLGİ */
  .footer {{
    text-align: center;
    font-size: 11px;
    color: #bbb;
    margin-top: 2px;
    letter-spacing: 0.5px;
  }}
</style>
</head>
<body>

  <div class="header">
    <div class="hisse">{hisse_kodu.upper()}</div>
    <div class="meta">
      <div class="title">ARACI KURUM DAĞILIMI</div>
      <div>Günlük (Anlık) Veriler</div>
      <div class="brand">@borsamatrisibot</div>
    </div>
  </div>

  <div class="card card-buyer">
    <div class="card-head">▲ &nbsp;NET ALICILAR</div>
    <table>
      <thead><tr>
        <th>Kurum</th><th>Oran</th><th>Net Lot</th><th>Maliyet</th>
      </tr></thead>
      <tbody>{buyer_rows if buyer_rows else no_data}</tbody>
    </table>
  </div>

  <div class="card card-seller">
    <div class="card-head">▼ &nbsp;NET SATICILLAR</div>
    <table>
      <thead><tr>
        <th>Kurum</th><th>Oran</th><th>Net Lot</th><th>Maliyet</th>
      </tr></thead>
      <tbody>{seller_rows if seller_rows else no_data}</tbody>
    </table>
  </div>

  <div class="footer">t.me/borsamatrisibot &nbsp;·&nbsp; Borsa Matrisi</div>

</body>
</html>"""

    out = f"/tmp/result_{hisse_kodu}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/usr/bin/chromium",
            headless=True,
            args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage","--disable-gpu"]
        )
        page = await browser.new_page(viewport={"width": 768, "height": 1000})
        await page.set_content(html, wait_until="networkidle")
        await page.screenshot(path=out, full_page=True)
        await browser.close()

    logger.info(f"✅ Görsel oluşturuldu: {out}")
    return out


# --- 6. HANDLER'LAR ---
@bot_app.on_message(filters.command("test"))
async def test_cmd(client: Client, message: Message):
    logger.info(f"✅ /test — kullanıcı: {message.from_user.id}")
    await message.reply_text("✅ Sistem çalışıyor!")

@bot_app.on_message(filters.command("akd") | filters.command("derinlik"))
async def handle_request(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("⚠️ Kullanım: /akd HISSE")
        return

    hisse = message.command[1].upper()
    logger.info(f"📥 /akd — hisse: {hisse}, kullanıcı: {message.from_user.id}")
    wait_msg = await message.reply_text(f"⏳ {hisse} taranıyor...")

    try:
        logger.info(f"📤 Hedef bota gönderiliyor: /akd {hisse}")
        await user_app.send_message(TARGET_BOT, f"/akd {hisse}")
        await asyncio.sleep(8)

        img_path = None
        logger.info("🔍 Cevap aranıyor...")
        async for msg in user_app.get_chat_history(TARGET_BOT, limit=5):
            logger.info(f"   → id:{msg.id} photo:{bool(msg.photo)} text:{(msg.text or '')[:40]}")
            if msg.photo:
                img_path = await user_app.download_media(
                    msg.photo, file_name=f"/tmp/ocr_{hisse}.jpg"
                )
                logger.info(f"✅ İndirildi: {img_path}")
                break

        if not img_path:
            await wait_msg.edit("❌ Hedef bottan görsel gelmedi. Tekrar dene.")
            return

        buyers, sellers = await asyncio.to_thread(process_ocr, img_path)
        final_img = await generate_premium_image(hisse, buyers, sellers)

        await message.reply_photo(
            final_img,
            caption=f"⚡️ **{hisse}** | Aracı Kurum Dağılımı\n@borsamatrisibot"
        )
        await wait_msg.delete()

        for f in [img_path, final_img]:
            if f and os.path.exists(f):
                os.remove(f)

    except Exception:
        logger.error(f"💥 HATA:\n{traceback.format_exc()}")
        await wait_msg.edit("❌ Bir hata oluştu. Loglara bakılıyor...")


# --- 7. BAŞLATICI ---
async def main():
    logger.info("🚀 Başlatılıyor...")
    async with bot_app, user_app:
        logger.info("✅ Her iki client aktif!")
        stop_event = asyncio.Event()

        def _stop(*_):
            logger.info("🛑 Durduruluyor...")
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _stop)

        await stop_event.wait()
    logger.info("👋 Kapatıldı.")

if __name__ == "__main__":
    bot_app.run(main())
