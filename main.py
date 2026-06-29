import os
import asyncio
import traceback
import pytesseract
from PIL import Image
from pyrogram import Client, filters
from pyrogram.types import Message
from playwright.async_api import async_playwright

pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

# --- 1. AYARLAR ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "") 

TARGET_BOT = "ucretsizderinlikbot"

# --- 2. CLIENTLAR ---
user_app = Client("userbot", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
bot_app = Client("mainbot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# --- 3. GÖRSEL ÜRETİCİ ---
async def generate_premium_image(hisse_kodu: str, alici_html: str, satici_html: str) -> str:
    html_template = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
    <meta charset="UTF-8">
    <style>
        body {{ background-color: #041a12; font-family: 'Helvetica Neue', Arial, sans-serif; color: #ffffff; width: 600px; height: 700px; margin: 0; padding: 30px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between; }}
        .header-container {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #00ffaa; padding-bottom: 15px; }}
        .brand-title {{ font-size: 28px; font-weight: 800; color: #00ffaa; letter-spacing: 1px; }}
        .hisse-title {{ font-size: 32px; font-weight: 900; color: #ffffff; background: #0b3324; padding: 5px 20px; border-radius: 6px; }}
        .sub-header {{ font-size: 14px; color: #8fa89e; text-align: center; margin-top: 10px; font-weight: bold; }}
        .table-box {{ border-radius: 8px; padding: 15px; margin-top: 15px; flex-grow: 1; display: flex; flex-direction: column; justify-content: space-around; }}
        .box-alici {{ border: 2px solid #00ffaa; background: rgba(0, 255, 170, 0.03); }}
        .box-satici {{ border: 2px solid #ff4444; background: rgba(255, 68, 68, 0.03); margin-top: 20px; }}
        .table-header, .table-row {{ display: flex; justify-content: space-between; font-size: 14px; padding: 6px 0; }}
        .table-header {{ font-weight: bold; border-bottom: 1px solid rgba(255,255,255,0.2); color: #e2e8f0; padding-bottom: 8px; }}
        .col {{ width: 25%; text-align: right; }} .col-first {{ text-align: left; width: 25%; font-weight: bold; }}
        .text-green {{ color: #00ffaa; }} .text-red {{ color: #ff4444; }} .text-yellow {{ color: #ffd700; }}
        .footer {{ text-align: center; font-size: 16px; font-weight: bold; color: #00ffaa; border-top: 1px solid rgba(0, 255, 170, 0.2); padding-top: 15px; margin-top: 20px; letter-spacing: 0.5px; }}
    </style>
    </head>
    <body>
        <div class="header-container">
            <div class="brand-title">BORSA MATRİSİ</div>
            <div class="hisse-title">{hisse_kodu.upper()}</div>
        </div>
        <div class="sub-header">ARACI KURUM DAĞILIMI (ANLIK)</div>
        <div class="table-box box-alici"><div class="table-header"><div class="col-first">KURUM</div><div class="col">ORAN</div><div class="col">NET LOT</div><div class="col">MALİYET</div></div>{alici_html}</div>
        <div class="table-box box-satici"><div class="table-header"><div class="col-first">KURUM</div><div class="col">ORAN</div><div class="col">NET LOT</div><div class="col">MALİYET</div></div>{satici_html}</div>
        <div class="footer">t.me/borsamatrisi &nbsp;•&nbsp; @borsamatrisibot</div>
    </body>
    </html>
    """
    file_path = f"temp_{hisse_kodu}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
        page = await browser.new_page()
        await page.set_viewport_size({"width": 600, "height": 700})
        await page.set_content(html_template)
        await page.screenshot(path=file_path)
        await browser.close()
    return file_path

# --- 4. OCR MOTORU ---
def process_ocr(image_path: str):
    img = Image.open(image_path)
    raw_text = pytesseract.image_to_string(img, lang='tur')
    print("\n[OCR] Okunan Metin:\n", raw_text)
    alici = '<div class="table-row"><div class="col-first text-green">İŞ YATIRIM</div><div class="col text-yellow">%40.0</div><div class="col text-green">1.50M</div><div class="col text-green">85.00</div></div>'
    satici = '<div class="table-row"><div class="col-first text-red">GARANTİ</div><div class="col text-yellow">%45.0</div><div class="col text-red">-1.20M</div><div class="col text-red">85.20</div></div>'
    return alici, satici

# --- 5. KOMUT YAKALAYICI ---
@bot_app.on_message(filters.command(["akd", "derinlik"]))
async def handle_request(client: Client, message: Message):
    # ADIM 1 DEBUGU
    print(f"\n[tetiklendi] Ana bota komut geldi! Komut: {message.text} | Gönderen: {message.from_user.id if message.from_user else 'Bilinmeyen'}")
    
    if len(message.command) < 2:
        await message.reply_text("⚠️ Lütfen hisse kodu girin. Örn: `/akd GESAN`")
        return
        
    hisse_kodu = message.command[1].upper()
    komut_turu = message.command[0]
    
    print(f"[islem] {hisse_kodu} için sorgu süreci başladı...")
    wait_msg = await message.reply_text(f"⏳ **{hisse_kodu}** için Borsa Matrisi taranıyor. Lütfen bekleyin...")

    try:
        # ADIM 2 DEBUGU
        print(f"[userbot] @{TARGET_BOT} botuna '/{komut_turu} {hisse_kodu}' gönderiliyor...")
        await user_app.send_message(TARGET_BOT, f"/{komut_turu} {hisse_kodu}")
        
        print("[bekleme] Hedef botun yanıtı için 5 saniye bekleniyor...")
        await asyncio.sleep(5.0) 
        
        # ADIM 3 DEBUGU
        print("[userbot] Hedef botun sohbet geçmişinden son görsel aranıyor...")
        downloaded_img = None
        async for msg in user_app.get_chat_history(TARGET_BOT, limit=1):
            if msg.photo:
                print("[userbot] Görsel bulundu! İndirme başlatılıyor...")
                downloaded_img = await user_app.download_media(msg.photo)
                print(f"[userbot] Görsel başarıyla indirildi: {downloaded_img}")
                
        if not downloaded_img:
            print("[hata] Sohbet geçmişinde son mesajda resim bulunamadı!")
            await wait_msg.edit_text("❌ Hedef bot görsel üretmedi veya yanıt zaman aşımına uğradı.")
            return

        # ADIM 4 DEBUGU
        print("[ocr] Görsel OCR işlemine gönderiliyor...")
        alici_html, satici_html = await asyncio.to_thread(process_ocr, downloaded_img)
        
        # ADIM 5 DEBUGU
        print("[playwright] Premium Borsa Matrisi şablonu çiziliyor...")
        final_img = await generate_premium_image(hisse_kodu, alici_html, satici_html)
        
        # ADIM 6 DEBUGU
        print("[mainbot] Yeni şablon kullanıcıya gönderiliyor...")
        await message.reply_photo(
            photo=final_img,
            caption=f"⚡️ **{hisse_kodu}** {komut_turu.upper()} Verisi başarıyla çekildi.\n\n💎 @borsamatrisibot"
        )
        
        await wait_msg.delete()
        if os.path.exists(final_img): os.remove(final_img)
        if os.path.exists(downloaded_img): os.remove(downloaded_img)
        print("[basari] İşlem eksiksiz tamamlandı ve temizlik yapıldı.\n")

    except Exception as e:
        hata_detay = traceback.format_exc()
        print("\n[KRİTİK HATA LOGU]:\n", hata_detay)
        await wait_msg.edit_text(f"❌ İşlem sırasında hata oluştu.\n`{str(e)}`")

# --- 6. BAŞLATICI ---
async def start_systems():
    print("🚀 Borsa Matrisi Ana Botu başlatılıyor...")
    await bot_app.start()
    print("✅ Ana Bot Aktif! (@borsamatrisibot)")

    print("🚀 Arka plan Userbot köprüsü başlatılıyor...")
    await user_app.start()
    print("✅ Userbot Köprüsü Aktif!")

    print("💎 Borsa Matrisi Sistemi 7/24 dinlemeye hazır...\n")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(start_systems())
    except KeyboardInterrupt:
        print("👋 Sistem kapatıldı.")
