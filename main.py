import os
import asyncio
import signal
import traceback
import pytesseract
import logging
import sys
import re
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
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

# --- 4. GÖRSEL ÖN İŞLEME ---
def preprocess_image(img: Image.Image) -> Image.Image:
    """
    Koyu arka planlı, renkli yazılı görsel → Tesseract için beyaz zemin siyah yazı.
    Adımlar: 2x büyüt → griye çevir → kontrast artır → keskinleştir → threshold
    """
    w, h = img.size
    img = img.resize((w * 2, h * 2), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.filter(ImageFilter.SHARPEN)

    # Koyu arka plan varsa ters çevir (ortalama piksel < 128 → koyu zemin)
    avg = sum(img.getdata()) / (img.width * img.height)
    if avg < 128:
        img = ImageOps.invert(img)

    # Gürültüyü temizle: sert siyah-beyaz
    img = img.point(lambda p: 255 if p > 140 else 0, "1").convert("L")
    return img


# --- 5. OCR PARSE ---
def parse_ocr_table(text: str):
    buyers  = []
    sellers = []

    # Başlık satırlarını atla
    skip_words = {
        "KURUM", "ORAN", "NET", "LOT", "MALİYET", "MALIYET",
        "GÜNLÜK", "GUNLUK", "ANLIK", "ANLUK", "VERİ", "VERI",
        "DAĞILIM", "DAGILIM", "ARACI", "KURUM DAĞILIMI"
    }

    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if len(line) < 5:
            continue
        if line.upper() in skip_words:
            continue

        # Satırdaki tüm sayı gruplarını çek
        nums = re.findall(r'-?[\d]+[.,][\d]+', line)
        if len(nums) < 3:
            continue

        # Satır başındaki metin → kurum adı
        kurum_match = re.match(
            r'^([A-ZÇĞİÖŞÜa-zçğışöüI][A-ZÇĞİÖŞÜa-zçğışöüI0-9\.\-\s]{0,25}?)\s+[-\d]',
            line
        )
        if not kurum_match:
            continue

        kurum = kurum_match.group(1).strip()
        if not kurum or kurum.upper() in skip_words:
            continue

        oran    = nums[0].lstrip("%").replace(",", ".")
        lot_raw = nums[1].replace(",", ".")
        maliyet = nums[2].replace(",", ".")

        # Binlik nokta ayracını temizle: "176.164" → 176164
        # Kural: lot değeri genellikle >100, maliyet <1000
        try:
            lot_float = float(lot_raw)
            # Eğer değer çok küçükse binlik ayraçlı olabilir
            if abs(lot_float) < 10 and "." in lot_raw:
                parts = lot_raw.split(".")
                if len(parts[-1]) == 3:  # "176.164" → son 3 hane
                    lot_float = float(lot_raw.replace(".", ""))
        except ValueError:
            continue

        if abs(lot_float) < 0.01:
            continue

        # Lot görüntü formatı: binlik nokta, ondalık virgül
        lot_display = f"{lot_float:,.0f}".replace(",", ".")

        row = {
            "kurum"  : kurum,
            "oran"   : oran,
            "lot"    : lot_display,
            "maliyet": maliyet
        }

        if lot_float >= 0:
            buyers.append(row)
        else:
            sellers.append(row)

    return buyers, sellers


def process_ocr(image_path: str):
    img = Image.open(image_path)
    processed = preprocess_image(img)

    proc_path = f"/tmp/proc_{os.path.basename(image_path)}.png"
    processed.save(proc_path)

    # PSM 6: tek blok tablo
    cfg6 = "--psm 6"
    text = pytesseract.image_to_string(processed, lang="tur+eng", config=cfg6)
    logger.info(f"📄 OCR psm6:\n{text[:600]}")
    buyers, sellers = parse_ocr_table(text)

    # Az satır geldiyse PSM 4 ile tekrar dene
    if len(buyers) + len(sellers) < 3:
        logger.warning("⚠️ Az satır, psm4 deneniyor...")
        cfg4 = "--psm 4"
        text2 = pytesseract.image_to_string(processed, lang="tur+eng", config=cfg4)
        logger.info(f"📄 OCR psm4:\n{text2[:600]}")
        b2, s2 = parse_ocr_table(text2)
        if len(b2) + len(s2) > len(buyers) + len(sellers):
            buyers, sellers = b2, s2

    if os.path.exists(proc_path):
        os.remove(proc_path)

    logger.info(f"✅ Parse — Alıcı: {len(buyers)}, Satıcı: {len(sellers)}")
    return buyers, sellers


# --- 6. HTML ŞABLON ---
def build_rows(rows: list, is_buyer: bool) -> str:
    html = ""
    for i, r in enumerate(rows):
        lot_val = r["lot"]
        lot_color = "#0077cc" if is_buyer else "#cc0000"
        if not is_buyer and not lot_val.startswith("-"):
            lot_val = f"-{lot_val}"

        bg  = "#f7fffe" if is_buyer else "#fff7f7"
        alt = "#edfdf5" if is_buyer else "#fdedef"
        row_bg = bg if i % 2 == 0 else alt

        kurum_key = r["kurum"].upper().strip()
        is_diger  = kurum_key in ("DIĞER", "DİĞER", "DIGER", "DiĞER", "DIGER")
        opacity   = "opacity:0.50;" if is_diger else ""
        weight    = "400" if is_diger else "600"

        html += f"""
        <tr style="background:{row_bg};{opacity}">
            <td style="font-weight:{weight};">{r['kurum']}</td>
            <td style="color:#d97b00;font-weight:700;">%{r['oran']}</td>
            <td style="color:{lot_color};font-weight:700;">{lot_val}</td>
            <td style="color:#444;">{r['maliyet']}</td>
        </tr>"""
    return html


async def generate_premium_image(hisse_kodu: str, buyers: list, sellers: list) -> str:
    buyer_rows  = build_rows(buyers,  is_buyer=True)
    seller_rows = build_rows(sellers, is_buyer=False)
    no_data = '<tr><td colspan="4" style="text-align:center;color:#bbb;padding:18px;font-size:13px;">Veri bulunamadı</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head><meta charset="UTF-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background: #f0f2f5;
    font-family: 'Segoe UI', Arial, sans-serif;
    width: 720px;
    padding: 22px 22px 16px 22px;
  }}

  /* BAŞLIK */
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    margin-bottom: 16px;
    padding-bottom: 14px;
    border-bottom: 2px solid #dde1e7;
  }}
  .hisse {{
    font-size: 44px;
    font-weight: 900;
    color: #0a0a0a;
    letter-spacing: 3px;
    line-height: 1;
  }}
  .meta {{
    text-align: right;
    font-size: 12px;
    color: #888;
    line-height: 1.8;
  }}
  .meta .title {{ font-size: 13px; font-weight: 700; color: #333; letter-spacing:1px; }}
  .meta .brand {{ font-size: 14px; font-weight: 800; color: #0077cc; }}

  /* KART */
  .card {{
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 3px 14px rgba(0,0,0,0.10);
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
  .card-buyer  .card-head {{ background: linear-gradient(90deg,#1e8449,#27ae60,#2ecc71); }}
  .card-seller .card-head {{ background: linear-gradient(90deg,#a93226,#c0392b,#e74c3c); }}

  /* TABLO */
  table {{ width:100%; border-collapse:collapse; }}
  thead tr {{ background:#ececec; }}
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
  tbody tr:last-child td {{ border-bottom:none; }}

  /* REKLAM BANDI — tablolar arasında */
  .ad-band {{
    background: linear-gradient(90deg,#0056b3,#0077cc,#00aaff);
    color: #fff;
    text-align: center;
    padding: 11px 18px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.8px;
    border-radius: 10px;
    box-shadow: 0 3px 12px rgba(0,119,204,0.35);
    margin: 14px 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }}
  .ad-band .ad-icon {{ font-size: 20px; }}
  .ad-band .ad-text {{ flex: 1; text-align: left; }}
  .ad-band .ad-link {{
    background: rgba(255,255,255,0.22);
    border: 1.5px solid rgba(255,255,255,0.50);
    border-radius: 7px;
    padding: 3px 12px;
    font-size: 14px;
    font-weight: 900;
    letter-spacing: 1px;
    white-space: nowrap;
  }}

  /* ALT BİLGİ */
  .footer {{
    text-align: center;
    font-size: 11px;
    color: #bbb;
    margin-top: 10px;
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

  <!-- ALICI TABLOSU -->
  <div class="card card-buyer">
    <div class="card-head">▲ &nbsp;NET ALICILAR</div>
    <table>
      <thead><tr>
        <th>Kurum</th><th>Oran</th><th>Net Lot</th><th>Maliyet</th>
      </tr></thead>
      <tbody>{buyer_rows if buyer_rows else no_data}</tbody>
    </table>
  </div>

  <!-- REKLAM BANDI -->
  <div class="ad-band">
    <span class="ad-icon">⚡</span>
    <span class="ad-text">Borsa Matrisi Premium — Anlık Derinlik &amp; Aracı Kurum Analizi</span>
    <span class="ad-link">@borsamatrisibot</span>
  </div>

  <!-- SATICI TABLOSU -->
  <div class="card card-seller">
    <div class="card-head">▼ &nbsp;NET SATICILLAR</div>
    <table>
      <thead><tr>
        <th>Kurum</th><th>Oran</th><th>Net Lot</th><th>Maliyet</th>
      </tr></thead>
      <tbody>{seller_rows if seller_rows else no_data}</tbody>
    </table>
  </div>

  <div class="footer">t.me/borsamatrisibot &nbsp;·&nbsp; Borsa Matrisi &nbsp;·&nbsp; Tüm veriler anlık güncellenir</div>

</body>
</html>"""

    out = f"/tmp/result_{hisse_kodu}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/usr/bin/chromium",
            headless=True,
            args=["--no-sandbox","--disable-setuid-sandbox",
                  "--disable-dev-shm-usage","--disable-gpu"]
        )
        page = await browser.new_page(viewport={"width": 764, "height": 1000})
        await page.set_content(html, wait_until="networkidle")
        await page.screenshot(path=out, full_page=True)
        await browser.close()

    logger.info(f"✅ Görsel oluşturuldu: {out}")
    return out


# --- 7. HANDLER'LAR ---
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


# --- 8. BAŞLATICI ---
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
