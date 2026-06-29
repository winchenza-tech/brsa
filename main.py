import os
import asyncio
import signal
import traceback
import pytesseract
import logging
import sys
import re
import numpy as np
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
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

# ─────────────────────────────────────────────
# --- 4. OCR — SATIR BAZLI YATAY BANT YÖNTEMİ ---
# ─────────────────────────────────────────────

def prepare_band(band: Image.Image) -> Image.Image:
    """
    Tek bir tablo satırı bandını OCR için hazırlar.
    - 4x büyüt (en önemli adım)
    - Griye çevir
    - Koyu arka plan varsa ters çevir
    - Kontrast artır
    - Threshold
    """
    # 4x büyüt
    w, h = band.size
    band = band.resize((w * 4, h * 4), Image.LANCZOS)

    # Griye çevir
    band = band.convert("L")

    # Ortalama parlaklık → koyu arka plan tespiti
    arr = np.array(band)
    if arr.mean() < 128:
        band = ImageOps.invert(band)

    # Kontrast güçlendir
    band = ImageEnhance.Contrast(band).enhance(3.0)

    # Gürültü temizle
    band = band.filter(ImageFilter.MedianFilter(size=3))

    # Sert threshold
    band = band.point(lambda p: 255 if p > 130 else 0)

    return band


def find_row_bands(img: Image.Image):
    """
    Görseldeki yatay tablo satırlarını bulur.
    Yöntem: Her satırın ortalama parlaklığını hesapla,
    belirgin renk değişimi = satır sınırı.
    """
    arr = np.array(img.convert("L"))
    h, w = arr.shape

    # Her yatay çizginin ortalama parlaklığı
    row_means = arr.mean(axis=1)

    # Satır sınırlarını bul: ani değişim noktaları
    # Tablo satırları genellikle 30-80px yükseklikte
    MIN_ROW_H = 20
    MAX_ROW_H = 120

    # Düz (yatay çizgi) bölgeleri bul: çok düşük std → ayırıcı çizgi
    row_stds = arr.std(axis=1)

    # Ayırıcı çizgiler: std < 15 (düz renk satırı)
    separators = [i for i in range(h) if row_stds[i] < 15]

    # Ayırıcıları grupla → band sınırları
    bands = []
    last = 0
    i = 0
    while i < len(separators):
        sep = separators[i]
        # Ardışık ayırıcıları grupla
        group_end = sep
        while i + 1 < len(separators) and separators[i+1] - separators[i] < 5:
            i += 1
            group_end = separators[i]
        # last → sep arası bir band
        band_h = sep - last
        if MIN_ROW_H <= band_h <= MAX_ROW_H:
            bands.append((last, sep))
        last = group_end
        i += 1

    # Son band
    if h - last >= MIN_ROW_H:
        bands.append((last, h))

    return bands


def ocr_band(img: Image.Image, y1: int, y2: int) -> str:
    """Görselin belirli yatay bandını OCR ile okur."""
    w = img.width
    # Biraz padding ekle
    pad = 3
    band = img.crop((0, max(0, y1 - pad), w, min(img.height, y2 + pad)))
    band = prepare_band(band)

    # Tek satır modu (psm 7) veya tek blok (psm 6)
    config = "--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzÇçĞğİıÖöŞşÜü0123456789.,%-. "
    text = pytesseract.image_to_string(band, lang="tur+eng", config=config).strip()
    return text


def parse_number_clean(s: str):
    """Sayı stringini float'a çevirir. Binlik ayraç akıllıca temizlenir."""
    s = s.strip().replace(" ", "")
    neg = s.startswith("-")
    s = s.lstrip("-+")

    # Virgülü noktaya çevir
    # "176.164" → binlik mi ondalık mı?
    # "69.35"   → ondalık (son kısım 2 hane)
    # "176.164" → binlik (son kısım 3 hane)
    if "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            # Binlik nokta → kaldır
            s = s.replace(".", "")
        elif "," in s:
            # "1.234,56" formatı
            s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")

    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return None


def parse_row_text(text: str):
    """
    Tek bir tablo satırının OCR metnini parse eder.
    Döndürür: (kurum, oran, lot, maliyet) veya None
    """
    if not text or len(text) < 4:
        return None

    skip = {"KURUM", "ORAN", "NET LOT", "NET", "LOT", "MALİYET", "MALIYET",
            "GÜNLÜK", "ANLIK", "VERİ", "BORSA", "MATRİSİ", "T.ME",
            "NET ALICILAR", "ALICILAR", "NET SATICILLAR", "SATICILLAR",
            "ARACI KURUM", "DAĞILIMI", "PREMIUM"}
    if text.upper().strip() in skip:
        return None
    if text.upper().strip().startswith("NET AL") or text.upper().strip().startswith("NET SAT"):
        return None

    # Satırdaki tüm sayıları bul
    numbers = re.findall(r'-?[\d]+[.,][\d]+', text)
    if len(numbers) < 2:
        return None

    # Kurum adı: satırın başındaki metin (sayılardan önce)
    first_num_pos = re.search(r'[\d]', text)
    if not first_num_pos:
        return None

    kurum_raw = text[:first_num_pos.start()].strip()
    # % işaretini ve gereksiz karakterleri temizle
    kurum = re.sub(r'[^A-Za-zÇçĞğİıÖöŞşÜü0-9\.\-\s]', '', kurum_raw).strip()

    if len(kurum) < 1:
        # Kurum adı alınamadıysa tüm metni kullan, sayıları çıkar
        kurum = re.sub(r'[\d\.\,\%\-\+]', '', text).strip()
        kurum = re.sub(r'\s+', ' ', kurum).strip()

    if not kurum:
        return None

    # % içeren sayı → oran
    oran = None
    lot  = None
    maliyet = None

    pct_match = re.search(r'%\s*([\d]+[.,][\d]+)', text)
    if pct_match:
        oran = pct_match.group(1).replace(",", ".")

    # Kalan sayıları lot ve maliyet olarak ata
    # lot: genellikle büyük (>10), maliyet: genellikle küçük (<1000) ve 2 ondalık
    remaining = []
    for n in numbers:
        if oran and n.replace(",", ".") == oran:
            continue
        v = parse_number_clean(n)
        if v is not None:
            remaining.append((n, v))

    if not oran and remaining:
        # İlk sayı oran olabilir
        oran = remaining[0][0].replace(",", ".")
        remaining = remaining[1:]

    if len(remaining) >= 2:
        # Lot: mutlak değer büyük olan
        # Maliyet: xx.xx formatında küçük olan
        by_abs = sorted(remaining, key=lambda x: abs(x[1]), reverse=True)
        lot_raw = by_abs[0][0]
        # Maliyet: 2 ondalık basamaklı küçük sayı
        maliyet_candidates = [r for r in remaining if abs(r[1]) < 1000 and r != by_abs[0]]
        if maliyet_candidates:
            maliyet = maliyet_candidates[0][0].replace(",", ".")
        else:
            maliyet = by_abs[-1][0].replace(",", ".")

        lot_val = parse_number_clean(lot_raw)
        if lot_val is None:
            return None

        lot_display = f"{lot_val:,.0f}".replace(",", ".")
        return {
            "kurum"  : kurum[:25],
            "oran"   : (oran or "—").lstrip("%"),
            "lot"    : lot_display,
            "lot_val": lot_val,
            "maliyet": maliyet or "—"
        }
    elif len(remaining) == 1:
        lot_val = parse_number_clean(remaining[0][0])
        if lot_val is None:
            return None
        return {
            "kurum"  : kurum[:25],
            "oran"   : (oran or "—").lstrip("%"),
            "lot"    : f"{lot_val:,.0f}".replace(",", "."),
            "lot_val": lot_val,
            "maliyet": "—"
        }

    return None


def process_ocr(image_path: str):
    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    logger.info(f"📐 Görsel boyutu: {w}x{h}")

    # Görseli 2x büyüt (band tespiti için)
    img_big = img.resize((w * 2, h * 2), Image.LANCZOS)

    # Satır bantlarını bul
    bands = find_row_bands(img_big)
    logger.info(f"📏 Bulunan bantlar: {len(bands)}")

    buyers  = []
    sellers = []

    # Her bandı OCR ile oku
    for y1, y2 in bands:
        text = ocr_band(img_big, y1, y2)
        if not text:
            continue

        logger.info(f"   Band [{y1}-{y2}]: {repr(text)}")

        row = parse_row_text(text)
        if not row:
            continue

        logger.info(f"   ✅ Parse: {row}")

        if row["lot_val"] >= 0:
            buyers.append(row)
        else:
            sellers.append(row)

    # Eğer band yöntemi yeterli satır bulamadıysa sabit yükseklik ile tara
    if len(buyers) + len(sellers) < 3:
        logger.warning("⚠️ Band tespiti yetersiz, sabit yükseklik taraması yapılıyor...")
        buyers, sellers = fallback_fixed_scan(img)

    logger.info(f"✅ Sonuç — Alıcı: {len(buyers)}, Satıcı: {len(sellers)}")
    return buyers, sellers


def fallback_fixed_scan(img: Image.Image):
    """
    Satır tespiti başarısız olursa görseli sabit aralıklarla tara.
    Tablo satırları genellikle eşit yükseklikte olur.
    """
    w, h = img.size
    img_big = img.resize((w * 2, h * 2), Image.LANCZOS)
    bh = img_big.height

    buyers  = []
    sellers = []

    # 30-70px arası satır yüksekliği dene
    for row_h in [50, 60, 70, 80]:
        buyers_tmp  = []
        sellers_tmp = []
        for y in range(0, bh, row_h):
            text = ocr_band(img_big, y, min(y + row_h, bh))
            if not text:
                continue
            row = parse_row_text(text)
            if not row:
                continue
            if row["lot_val"] >= 0:
                buyers_tmp.append(row)
            else:
                sellers_tmp.append(row)

        total = len(buyers_tmp) + len(sellers_tmp)
        if total > len(buyers) + len(sellers):
            buyers, sellers = buyers_tmp, sellers_tmp
            logger.info(f"   Sabit tarama row_h={row_h}: {total} satır buldu")

    return buyers, sellers


# --- 5. HTML ŞABLON ---
def build_rows(rows: list, is_buyer: bool) -> str:
    html = ""
    for i, r in enumerate(rows):
        lot_val   = r["lot"]
        lot_color = "#0077cc" if is_buyer else "#cc0000"
        if not is_buyer and not str(lot_val).startswith("-"):
            lot_val = f"-{lot_val}"

        bg     = "#f7fffe" if is_buyer else "#fff7f7"
        alt    = "#edfdf5" if is_buyer else "#fdedef"
        row_bg = bg if i % 2 == 0 else alt

        ku = r["kurum"].upper().strip()
        is_diger = any(d in ku for d in ("DIGER", "DİĞER", "DIĞER"))
        opacity  = "opacity:0.50;" if is_diger else ""
        weight   = "400" if is_diger else "600"

        html += f"""<tr style="background:{row_bg};{opacity}">
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
    /* padding-bottom: 10px — satıcı tablosundan sonra max 10px boşluk */
    padding: 22px 22px 10px 22px;
  }}
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
  .card {{
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 3px 14px rgba(0,0,0,0.10);
  }}
  .card-buyer  {{ border: 2.5px solid #27ae60; }}
  .card-seller {{ border: 2.5px solid #e74c3c; }}
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
  .ad-band {{
    background: linear-gradient(90deg,#0056b3,#0077cc,#00aaff);
    color: #fff;
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
  /* Alt footer: satıcı kutusundan hemen sonra, max 10px boşluk */
  .footer {{
    text-align: center;
    font-size: 10px;
    color: #ccc;
    margin-top: 6px;
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

  <div class="ad-band">
    <span class="ad-icon">⚡</span>
    <span class="ad-text">Borsa Matrisi Premium — Anlık Derinlik &amp; Aracı Kurum Analizi</span>
    <span class="ad-link">@borsamatrisibot</span>
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

  <div class="footer">t.me/borsamatrisibot · Borsa Matrisi</div>

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
        page = await browser.new_page(viewport={"width": 764, "height": 200})
        await page.set_content(html, wait_until="networkidle")
        # full_page=True: içeriğe tam oturacak boyut
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
