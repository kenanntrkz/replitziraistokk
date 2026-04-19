"""WhatsApp bildirim servisi (Evolution API üzerinden)."""
import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

WA_URL = os.environ.get('WHATSAPP_API_URL', 'http://10.0.0.3:8080').rstrip('/')
WA_KEY = os.environ.get('WHATSAPP_API_KEY', '')
WA_INSTANCE = os.environ.get('WHATSAPP_INSTANCE', 'tarim')
WA_TO = os.environ.get('WHATSAPP_TO', '')

DATA_DIR = '/var/www/tarim/data'


def _dedup_ok(key, seconds):
    if not key:
        return True
    flag = os.path.join(DATA_DIR, f'wa_{key}.ts')
    try:
        if os.path.exists(flag):
            with open(flag) as f:
                last = float(f.read().strip())
            if time.time() - last < seconds:
                return False
    except Exception:
        pass
    return True


def _dedup_mark(key):
    if not key:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    flag = os.path.join(DATA_DIR, f'wa_{key}.ts')
    try:
        with open(flag, 'w') as f:
            f.write(str(time.time()))
    except Exception:
        logger.exception('dedup flag yazılamadı')


def send_whatsapp(message, dedup_key=None, dedup_seconds=86400, to=None):
    """Evolution API'ye tek kişilik metin mesaj gönder.

    dedup_key verilirse aynı key son dedup_seconds içinde tekrar gönderilmez.
    to parametresi verilmezse WHATSAPP_TO env var kullanılır.
    """
    hedef = to or WA_TO
    if not hedef or not WA_KEY:
        logger.warning('WhatsApp config eksik (WHATSAPP_TO/KEY)')
        return False, 'config_eksik'

    if not _dedup_ok(dedup_key, dedup_seconds):
        return False, 'dedup_skip'

    try:
        url = f'{WA_URL}/message/sendText/{WA_INSTANCE}'
        headers = {'apikey': WA_KEY, 'Content-Type': 'application/json'}
        body = {'number': hedef, 'text': message}
        r = requests.post(url, json=body, headers=headers, timeout=10)
        if r.status_code in (200, 201):
            _dedup_mark(dedup_key)
            logger.info(f'WhatsApp gönderildi: {dedup_key or "ad-hoc"}')
            return True, 'ok'
        logger.warning(f'WhatsApp HTTP {r.status_code}: {r.text[:300]}')
        return False, f'http_{r.status_code}'
    except Exception as e:
        logger.exception(f'WhatsApp istisnası: {e}')
        return False, 'exception'


def kritik_stok_mesaji(kritik_ilaclar, kritik_gubreler):
    """Kritik stok listesinden okunabilir WhatsApp metni üret."""
    lines = ['🚨 *Zirai Stok — Kritik Uyarı*', '']
    if kritik_ilaclar:
        lines.append('💊 *Kritik İlaçlar:*')
        for i in kritik_ilaclar:
            lines.append(f'• {i.ad}: {round(i.miktar, 1)} {i.birim} (min {i.min_stok})')
    if kritik_gubreler:
        if kritik_ilaclar:
            lines.append('')
        lines.append('🌱 *Kritik Gübreler:*')
        for g in kritik_gubreler:
            lines.append(f'• {g.ad}: {round(g.miktar, 1)} {g.birim} (min {g.min_stok})')
    lines += ['', 'https://tarim.kenanturkoz.cloud/']
    return '\n'.join(lines)


def hos_uyari_mesaji(hos_listesi):
    """HÖS aktif bağlar için WhatsApp mesajı."""
    if not hos_listesi:
        return None
    lines = ['🍇 *Hasat Öncesi Süre (HÖS) Uyarısı*', '']
    lines.append('Aşağıdaki bağlar *henüz hasat yapılamaz*:')
    for h in hos_listesi:
        lines.append(f"• {h['bag'].ad} — güvenli: {h['guvenli_tarih'].strftime('%d.%m.%Y')} ({h['kalan_gun']} gün)")
    lines += ['', 'https://tarim.kenanturkoz.cloud/']
    return '\n'.join(lines)


def tekrar_uyari_mesaji(onerileri):
    """Tekrar ilaçlama zamanı gelen/geçen parseller için WhatsApp mesajı."""
    if not onerileri:
        return None
    lines = ['💧 *Tekrar İlaçlama Zamanı*', '']
    gecti = [o for o in onerileri if o.get('durum') == 'geçti']
    zamani = [o for o in onerileri if o.get('durum') == 'zamanı']
    if gecti:
        lines.append('*Zamanı Geçti:*')
        for o in gecti:
            lines.append(f"• {o['bag'].ad} — {o['ilac'].ad}: son {o['son_tarih'].strftime('%d.%m.%Y')} ({o['gecen_gun']} gün önce, aralık {o['aralik']} g)")
    if zamani:
        if gecti:
            lines.append('')
        lines.append('*Bu Günlerde:*')
        for o in zamani:
            lines.append(f"• {o['bag'].ad} — {o['ilac'].ad}: son {o['son_tarih'].strftime('%d.%m.%Y')} ({o['gecen_gun']}/{o['aralik']} gün)")
    lines += ['', 'https://tarim.kenanturkoz.cloud/']
    return '\n'.join(lines)
