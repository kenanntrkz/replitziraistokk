import json
import os
import datetime
import time
import requests
import pytz
import urllib.parse
from functools import wraps
from flask import render_template, request, redirect, url_for, flash, jsonify, send_file, make_response, g, session
import re
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app import app, db
from models import Ilac, Gubre, IlacKullanim, GubreKullanim, Bag, Photo, StokHareket
from services.notify import send_whatsapp, kritik_stok_mesaji, hos_uyari_mesaji, tekrar_uyari_mesaji
from services.weather import forecast_for_bag, parse_gps, fetch_forecast
from services.pdf_defter import zirai_ilac_defteri_pdf
from services.storage import put_photo, presigned_get, delete_photo, get_bytes
from services.vision import teshis_et


# --- Ad normalize (Python .lower() vs Postgres LOWER() Türkçe İ uyumsuzluğu fix) ---
def _normalize_ad(s):
    return (s or "").lower().replace("̇", "").strip()

# --- HÖS (Hasat Öncesi Süre) yardımcıları ---
def parse_hasat_gun(s):
    """Serbest metinden HÖS gün sayısını çıkar: '7 gün' -> 7, '21' -> 21, None -> None."""
    if not s:
        return None
    m = re.search(r'(\d+)', str(s))
    return int(m.group(1)) if m else None


def compute_bag_hos(bag_id):
    """Bir bağın aktif HÖS durumunu döndür.
    Dönüş: {
        'guvenli_tarih': date veya None,
        'kalan_gun': int (negatif ise serbest),
        'aktif': bool (bugün < guvenli_tarih),
        'kayitlar': [{'ilac_ad', 'tarih', 'hasat_gun', 'serbest_tarih'}, ...]
    }
    """
    kayitlar = (
        db.session.query(IlacKullanim, Ilac)
        .join(Ilac, IlacKullanim.ilac_id == Ilac.id)
        .filter(IlacKullanim.bag_id == bag_id)
        .filter(Ilac.hasat_suresi_gun != None)
        .all()
    )
    bugun = datetime.date.today()
    liste = []
    en_gec = None
    for kullanim, ilac in kayitlar:
        if not kullanim.tarih or not ilac.hasat_suresi_gun:
            continue
        uyg_tarih = kullanim.tarih.date() if hasattr(kullanim.tarih, 'date') else kullanim.tarih
        serbest = uyg_tarih + datetime.timedelta(days=ilac.hasat_suresi_gun)
        liste.append({
            'ilac_ad': ilac.ad,
            'tarih': uyg_tarih,
            'hasat_gun': ilac.hasat_suresi_gun,
            'serbest_tarih': serbest,
        })
        if en_gec is None or serbest > en_gec:
            en_gec = serbest
    kalan = (en_gec - bugun).days if en_gec else None
    return {
        'guvenli_tarih': en_gec,
        'kalan_gun': kalan,
        'aktif': (en_gec is not None and en_gec > bugun),
        'kayitlar': sorted(liste, key=lambda x: x['serbest_tarih'], reverse=True),
    }


def compute_all_bag_hos():
    """Tüm bağlar için HÖS durumunu dön — dashboard için."""
    sonuc = []
    for bag in Bag.query.filter_by(aktif=True).all():
        hos = compute_bag_hos(bag.id)
        if hos['guvenli_tarih']:
            sonuc.append({'bag': bag, **hos})
    # aktif olanlar başta, kalan gün küçükten büyüğe
    sonuc.sort(key=lambda x: (0 if x['aktif'] else 1, x['kalan_gun'] if x['kalan_gun'] is not None else 9999))
    return sonuc


def compute_tekrar_onerileri(bag_id=None):
    """Tekrar_araligi_gun ayarlı ilaçlar için (bag, ilac) başına son kullanımdan
    geçen günü hesaplayıp öneri üret.
    Dönüş: [{'bag', 'ilac', 'son_tarih', 'gecen_gun', 'aralik', 'gecikme', 'durum'}]
    durum: 'zamanı' (0..2 gün kala), 'geçti' (aralık geçildi), 'yakın' (aralık-3 içinde)
    """
    q = (
        db.session.query(IlacKullanim, Ilac, Bag)
        .join(Ilac, IlacKullanim.ilac_id == Ilac.id)
        .join(Bag, IlacKullanim.bag_id == Bag.id)
        .filter(Ilac.tekrar_araligi_gun != None)
        .filter(Ilac.tekrar_araligi_gun > 0)
        .filter(Bag.aktif == True)
    )
    if bag_id is not None:
        q = q.filter(IlacKullanim.bag_id == bag_id)
    # Her (bag, ilac) için en son tarihi tut
    son = {}
    for k, i, b in q.all():
        if not k.tarih:
            continue
        tar = k.tarih.date() if hasattr(k.tarih, 'date') else k.tarih
        key = (b.id, i.id)
        if key not in son or son[key]['tarih'] < tar:
            son[key] = {'bag': b, 'ilac': i, 'tarih': tar}
    bugun = datetime.date.today()
    sonuc = []
    for v in son.values():
        ilac = v['ilac']
        aralik = ilac.tekrar_araligi_gun
        gecen = (bugun - v['tarih']).days
        gecikme = gecen - aralik  # 0 ise tam zamanı, pozitif ise geçmiş
        if gecikme >= 0:
            durum = 'geçti'
        elif gecikme >= -2:
            durum = 'zamanı'
        elif gecikme >= -5:
            durum = 'yakın'
        else:
            continue  # daha erken
        sonuc.append({
            'bag': v['bag'],
            'ilac': ilac,
            'son_tarih': v['tarih'],
            'gecen_gun': gecen,
            'aralik': aralik,
            'gecikme': gecikme,
            'durum': durum,
        })
    # Önce 'geçti', sonra 'zamanı', sonra 'yakın'; her grupta gecikmesi büyük önde
    oncelik = {'geçti': 0, 'zamanı': 1, 'yakın': 2}
    sonuc.sort(key=lambda x: (oncelik[x['durum']], -x['gecikme']))
    return sonuc


# --- Stok hareket log helper ---
def log_stok(urun_type, urun_id, tip, miktar, birim=None, birim_fiyat=None, not_bilgisi=None, referans=None):
    """Stok hareketini kaydet. Çağıran commit'ten sorumlu."""
    try:
        hareket = StokHareket(
            urun_type=urun_type, urun_id=urun_id, tip=tip,
            miktar=abs(float(miktar)) if miktar is not None else 0,
            birim=birim, birim_fiyat=birim_fiyat,
            not_bilgisi=not_bilgisi, referans=referans,
        )
        db.session.add(hareket)
    except Exception as e:
        app.logger.exception(f'log_stok hatası: {e}')


# --- Hedef hastalık canonical key (dropdown gruplama için) ---
_TR_MAP = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iisSgGuUoOcC")
def _hastalik_key(s):
    """Hastalık etiketini canonical hale getir: parantez at, 'bağ/bağda' prefix at, son ek sadeleştir."""
    if not s:
        return ""
    t = re.sub(r'\([^)]*\)', '', s).strip()
    t = t.translate(_TR_MAP).lower().replace("̇", "")
    t = re.sub(r'^(bag|bagda)\s+', '', t)
    t = re.sub(r'(si|su|sı|sü)$', '', t)
    return t.strip()

# --- GİRİŞ SİSTEMİ ---
# Kullanıcı adı ve şifre .env dosyasından okunur, yoksa varsayılan değerler kullanılır
APP_USERNAME = os.environ.get('APP_USERNAME', 'admin')
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'tarim2026')

# ----- E-POSTA BILDIRIMI -----
SMTP_HOST = os.environ.get('SMTP_HOST', 'mail.turkoz.digital')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER_ADDR = os.environ.get('SMTP_USER', 'iletisim@turkoz.digital')
SMTP_PASS = os.environ.get('SMTP_PASS')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL', 'kenan@turkoz.digital')


def kritik_stok_email_gonder(kritik_ilaclar, kritik_gubreler):
    """Kritik stok uyarisi e-postasi - gunde bir kez gonderilir."""
    if not kritik_ilaclar and not kritik_gubreler:
        return False
    if not SMTP_PASS:
        app.logger.warning('SMTP_PASS tanimli degil, e-posta gonderilemedi.')
        return False

    flag_file = '/var/www/tarim/data/last_kritik_email.txt'
    try:
        if os.path.exists(flag_file):
            with open(flag_file, 'r') as fh:
                last_ts = float(fh.read().strip())
            import time as _time
            if _time.time() - last_ts < 86400:
                return False
    except Exception:
        pass

    lines_list = ['Zirai Stok Takip Sistemi - Kritik Stok Uyarisi', '']
    if kritik_ilaclar:
        lines_list.append('KRITIK ILACLAR:')
        for ilac in kritik_ilaclar:
            lines_list.append(
                '  - ' + ilac.ad + ': ' + str(round(ilac.miktar, 1)) + ' ' + ilac.birim +
                ' (min: ' + str(ilac.min_stok) + ' ' + ilac.birim + ')'
            )
    if kritik_gubreler:
        lines_list.append('')
        lines_list.append('KRITIK GUBRELER:')
        for gubre in kritik_gubreler:
            lines_list.append(
                '  - ' + gubre.ad + ': ' + str(round(gubre.miktar, 1)) + ' ' + gubre.birim +
                ' (min: ' + str(gubre.min_stok) + ' ' + gubre.birim + ')'
            )
    lines_list.append('')
    lines_list.append('Toplam kritik urun: ' + str(len(kritik_ilaclar) + len(kritik_gubreler)))
    lines_list.append('http://tarim.kenanturkoz.cloud/')

    body = chr(10).join(lines_list)

    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER_ADDR
        msg['To'] = NOTIFY_EMAIL
        msg['Subject'] = '[Zirai Stok] ' + str(len(kritik_ilaclar) + len(kritik_gubreler)) + ' Kritik Stok Uyarisi'
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER_ADDR, SMTP_PASS)
            server.sendmail(SMTP_USER_ADDR, NOTIFY_EMAIL, msg.as_string())
        import time as _time
        os.makedirs('/var/www/tarim/data', exist_ok=True)
        with open(flag_file, 'w') as fh:
            fh.write(str(_time.time()))
        app.logger.info('Kritik stok e-postasi gonderildi: ' + NOTIFY_EMAIL)
        return True
    except Exception as e:
        app.logger.error('Kritik stok e-posta hatasi: ' + str(e))
        return False


def kritik_stok_whatsapp_gonder(kritik_ilaclar, kritik_gubreler):
    """Kritik stok WhatsApp uyarısı — günde 1 kez."""
    if not kritik_ilaclar and not kritik_gubreler:
        return False
    msg = kritik_stok_mesaji(kritik_ilaclar, kritik_gubreler)
    ok, _ = send_whatsapp(msg, dedup_key='kritik_stok', dedup_seconds=86400)
    return ok


def hos_whatsapp_gonder(hos_aktif):
    """HÖS aktif bağlar için WhatsApp uyarısı — günde 1 kez."""
    msg = hos_uyari_mesaji(hos_aktif)
    if not msg:
        return False
    ok, _ = send_whatsapp(msg, dedup_key='hos_uyari', dedup_seconds=86400)
    return ok


def tekrar_whatsapp_gonder(onerileri):
    """Tekrar ilaçlama önerileri için WhatsApp uyarısı — günde 1 kez."""
    msg = tekrar_uyari_mesaji(onerileri)
    if not msg:
        return False
    ok, _ = send_whatsapp(msg, dedup_key='tekrar_uyari', dedup_seconds=86400)
    return ok


def login_required(f):
    """Giriş yapmayan kullanıcıları login sayfasına yönlendirir."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('giris'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/giris', methods=['GET', 'POST'])
def giris():
    """Kullanıcı giriş sayfası."""
    if session.get('logged_in'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        kullanici_adi = request.form.get('kullanici_adi', '')
        sifre = request.form.get('sifre', '')

        if kullanici_adi == APP_USERNAME and sifre == APP_PASSWORD:
            session['logged_in'] = True
            session['kullanici'] = kullanici_adi
            session.permanent = True
            flash('Başarıyla giriş yaptınız.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Kullanıcı adı veya şifre hatalı!', 'danger')

    return render_template('login.html')

@app.route('/cikis')
def cikis():
    """Kullanıcı çıkış işlemi."""
    session.clear()
    flash('Başarıyla çıkış yaptınız.', 'info')
    return redirect(url_for('giris'))

# API anahtarları çevre değişkenlerinden al
anthropic_api_key = os.environ.get('ANTHROPIC_API_KEY')
openai_api_key = os.environ.get('OPENAI_API_KEY')

# Model isimleri
CLAUDE_MODEL = "claude-sonnet-4-6"
OPENAI_MODEL = "gpt-4o"  # the newest OpenAI model is "gpt-4o" which was released May 13, 2024

# API istemcilerini hazırla, ancak yalnızca API çağrısı yapıldığında kullan
openai = None
anthropic_client = None

def get_openai_client():
    """
    OpenAI API istemcisini döndürür. Çevre değişkeninden anahtar kullanır.
    """
    global openai
    try:
        if not openai and openai_api_key:
            from openai import OpenAI
            openai = OpenAI(api_key=openai_api_key)
        return openai
    except Exception as e:
        print(f"OpenAI istemcisi oluşturma hatası: {str(e)}")
        return None

def get_anthropic_client():
    """
    Anthropic (Claude) API istemcisini döndürür.
    Sadece çevre değişkenlerinden anahtar kullanılır.
    """
    global anthropic_client
    try:
        if not anthropic_client and anthropic_api_key:
            from anthropic import Anthropic
            anthropic_client = Anthropic(api_key=anthropic_api_key)
        return anthropic_client
    except Exception as e:
        print(f"Anthropic istemcisi oluşturma hatası: {str(e)}")
        return None

def get_perplexity_url(query_text):
    """
    Perplexity.ai'a doğrudan sorgu URL'si oluşturur.
    API anahtarı yoksa kullanıcıyı doğrudan web sitesine yönlendirerek
    arama yapmalarını sağlar.
    
    Parametre:
        query_text: Sorgu metni
        
    Dönüş:
        Perplexity.ai sorgu URL'si
    """
    encoded_query = urllib.parse.quote(query_text)
    return f"https://www.perplexity.ai/search?q={encoded_query}"

# Global template context processor
@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now()}

# Ana sayfa
@app.route('/')
@login_required
def index():
    # Kritik stok kontrolü (min_stok altındaki ürünler)
    kritik_ilaclar = Ilac.query.filter(Ilac.miktar < Ilac.min_stok).all()
    kritik_gubreler = Gubre.query.filter(Gubre.miktar < Gubre.min_stok).all()
    
    # Özet istatistikler
    toplam_ilac = Ilac.query.count()
    toplam_gubre = Gubre.query.count()
    toplam_bag = Bag.query.filter_by(aktif=True).count()
    
    # Son işlemler
    son_ilaclama = IlacKullanim.query.order_by(IlacKullanim.tarih.desc()).first()
    son_gubreleme = GubreKullanim.query.order_by(GubreKullanim.tarih.desc()).first()
    
    # Kritik stok bildirimleri (gunde 1 kez)
    kritik_stok_email_gonder(kritik_ilaclar, kritik_gubreler)
    kritik_stok_whatsapp_gonder(kritik_ilaclar, kritik_gubreler)

    # HÖS (Hasat Öncesi Süre) durumu
    hos_listesi = compute_all_bag_hos()
    hos_aktif = [h for h in hos_listesi if h['aktif']]
    hos_serbest = [h for h in hos_listesi if not h['aktif']]

    # HÖS WhatsApp uyarısı (yaklaşan/aktif olanlar için günde 1 kez)
    hos_yaklasan = [h for h in hos_aktif if h['kalan_gun'] is not None and h['kalan_gun'] <= 7]
    if hos_yaklasan:
        hos_whatsapp_gonder(hos_yaklasan)

    # SKT uyarıları (bugün – 30 gün sonra arası dolacak + zaten dolmuş)
    bugun = datetime.date.today()
    skt_sinir = bugun + datetime.timedelta(days=30)
    skt_yaklasan = []  # [{urun, tip, kalan_gun}]
    skt_dolmus = []
    for i in Ilac.query.filter(Ilac.son_kullanma_tarihi != None).all():
        if i.son_kullanma_tarihi < bugun:
            skt_dolmus.append({'urun': i, 'tip': 'ilac', 'kalan_gun': (i.son_kullanma_tarihi - bugun).days})
        elif i.son_kullanma_tarihi <= skt_sinir:
            skt_yaklasan.append({'urun': i, 'tip': 'ilac', 'kalan_gun': (i.son_kullanma_tarihi - bugun).days})
    for g in Gubre.query.filter(Gubre.son_kullanma_tarihi != None).all():
        if g.son_kullanma_tarihi < bugun:
            skt_dolmus.append({'urun': g, 'tip': 'gubre', 'kalan_gun': (g.son_kullanma_tarihi - bugun).days})
        elif g.son_kullanma_tarihi <= skt_sinir:
            skt_yaklasan.append({'urun': g, 'tip': 'gubre', 'kalan_gun': (g.son_kullanma_tarihi - bugun).days})
    skt_yaklasan.sort(key=lambda x: x['kalan_gun'])
    skt_dolmus.sort(key=lambda x: x['kalan_gun'])

    # Hava durumu (GPS'i olan ilk aktif bağ için)
    hava = None
    hava_bag = None
    for _bag in Bag.query.filter_by(aktif=True).all():
        if _bag.gps_koordinat and parse_gps(_bag.gps_koordinat):
            hava = forecast_for_bag(_bag)
            hava_bag = _bag
            if hava:
                break

    # Tekrar ilaçlama önerileri
    tekrar_onerileri = compute_tekrar_onerileri()

    # Tekrar önerileri için WhatsApp bildirimi (günde 1 kez dedup)
    try:
        tekrar_whatsapp_gonder([o for o in tekrar_onerileri if o['durum'] in ('geçti', 'zamanı')])
    except Exception as _e:
        app.logger.warning(f'tekrar_whatsapp_gonder hata: {_e}')

    return render_template('index.html',
        ilac_uyarilar=kritik_ilaclar,
        gubre_uyarilar=kritik_gubreler,
        toplam_ilac=toplam_ilac,
        toplam_gubre=toplam_gubre,
        toplam_bag=toplam_bag,
        son_ilaclama=son_ilaclama,
        son_gubreleme=son_gubreleme,
        hos_aktif=hos_aktif,
        hos_serbest=hos_serbest,
        hava=hava,
        hava_bag=hava_bag,
        skt_yaklasan=skt_yaklasan,
        skt_dolmus=skt_dolmus,
        tekrar_onerileri=tekrar_onerileri,
    )

# ----- İLAÇ YÖNETİMİ -----
@app.route('/ilaclar', methods=['GET', 'POST'])
@login_required
def ilaclar():
    if request.method == 'POST':
        # Yeni ilaç ekleme
        ad = request.form['ad']
        etken_madde = request.form['etken_madde']
        hedef_hastalik = request.form['hedef_hastalik']
        miktar = float(request.form['miktar'])
        birim = request.form['birim']
        dozaj = request.form.get('dozaj', '').strip()
        grup = request.form.get('grup', '').strip()
        hasat_suresi = request.form.get('hasat_suresi', '').strip()
        uyari = request.form.get('uyari', '').strip()
        birim_fiyat = request.form.get('birim_fiyat', '').strip()
        alim_tarihi = request.form.get('alim_tarihi', '').strip()
        try:
            birim_fiyat_val = float(birim_fiyat) if birim_fiyat else None
        except ValueError:
            birim_fiyat_val = None
        try:
            alim_tarihi_val = datetime.datetime.strptime(alim_tarihi, '%Y-%m-%d').date() if alim_tarihi else None
        except ValueError:
            alim_tarihi_val = None
        skt = request.form.get('son_kullanma_tarihi', '').strip()
        lot_no = request.form.get('lot_no', '').strip() or None
        acilma = request.form.get('acilma_tarihi', '').strip()
        try:
            skt_val = datetime.datetime.strptime(skt, '%Y-%m-%d').date() if skt else None
        except ValueError:
            skt_val = None
        try:
            acilma_val = datetime.datetime.strptime(acilma, '%Y-%m-%d').date() if acilma else None
        except ValueError:
            acilma_val = None
        _tra = request.form.get('tekrar_araligi_gun', '').strip()
        try:
            tekrar_val = int(_tra) if _tra else None
        except ValueError:
            tekrar_val = None
        kaydet_json = 'kaydet_json' in request.form

        # Aynı isimde ilaç varsa miktarı güncelle, yoksa yeni kayıt aç
        mevcut_ilac = Ilac.query.filter(
            db.func.lower(Ilac.ad) == _normalize_ad(ad)
        ).first()

        if mevcut_ilac:
            mevcut_ilac.miktar += miktar
            if etken_madde and not mevcut_ilac.etken_madde:
                mevcut_ilac.etken_madde = etken_madde
            if hedef_hastalik and not mevcut_ilac.hedef_hastalik:
                mevcut_ilac.hedef_hastalik = hedef_hastalik
            if dozaj and not mevcut_ilac.dozaj:
                mevcut_ilac.dozaj = dozaj
            if grup and not mevcut_ilac.grup:
                mevcut_ilac.grup = grup
            if hasat_suresi and not mevcut_ilac.hasat_suresi:
                mevcut_ilac.hasat_suresi = hasat_suresi
                mevcut_ilac.hasat_suresi_gun = parse_hasat_gun(hasat_suresi)
            if uyari and not mevcut_ilac.uyari:
                mevcut_ilac.uyari = uyari
            if birim_fiyat_val is not None:
                mevcut_ilac.birim_fiyat = birim_fiyat_val
            if alim_tarihi_val:
                mevcut_ilac.alim_tarihi = alim_tarihi_val
            if skt_val:
                mevcut_ilac.son_kullanma_tarihi = skt_val
            if lot_no:
                mevcut_ilac.lot_no = lot_no
            if acilma_val:
                mevcut_ilac.acilma_tarihi = acilma_val
            if tekrar_val is not None:
                mevcut_ilac.tekrar_araligi_gun = tekrar_val
            log_stok('ilac', mevcut_ilac.id, 'GIRIS', miktar,
                     birim=mevcut_ilac.birim, birim_fiyat=birim_fiyat_val,
                     not_bilgisi='Stok ekleme', referans='ilac_ekle')
            db.session.commit()
            flash(f'{ad} stoğa eklendi → Yeni toplam: {mevcut_ilac.miktar} {mevcut_ilac.birim}', 'success')
        else:
            yeni_ilac = Ilac(
                ad=ad,
                etken_madde=etken_madde,
                hedef_hastalik=hedef_hastalik,
                miktar=miktar,
                birim=birim,
                dozaj=dozaj,
                grup=grup,
                hasat_suresi=hasat_suresi,
                hasat_suresi_gun=parse_hasat_gun(hasat_suresi),
                uyari=uyari,
                birim_fiyat=birim_fiyat_val,
                alim_tarihi=alim_tarihi_val,
                son_kullanma_tarihi=skt_val,
                lot_no=lot_no,
                acilma_tarihi=acilma_val,
                tekrar_araligi_gun=tekrar_val,
            )
            db.session.add(yeni_ilac)
            db.session.flush()
            log_stok('ilac', yeni_ilac.id, 'GIRIS', miktar,
                     birim=birim, birim_fiyat=birim_fiyat_val,
                     not_bilgisi='İlk kayıt', referans='ilac_ekle')
            db.session.commit()
        
        # İlacı JSON dosyasına da kaydet
        if kaydet_json:
            try:
                # JSON formatında ilaç verisi oluştur
                ilac_json = {
                    "ad": ad,
                    "etken_madde": etken_madde,
                    "hedef_hastalik": hedef_hastalik,
                    "dozaj": dozaj,
                    "birim": birim,
                    "miktar": miktar
                }
                
                # API sunucusu üzerinden JSON veritabanını güncelle
                response = requests.post('http://0.0.0.0:3000/api/ilaclar', json=ilac_json, timeout=3)
                
                if response.status_code == 200:
                    print(f"İlaç ekleme: '{ad}' başarıyla JSON'a eklendi/güncellendi (API üzerinden).")
                    flash(f'{ad} ilacı başarıyla eklendi ve JSON veritabanına kaydedildi.', 'success')
                else:
                    print(f"İlaç ekleme API hatası: {response.text}")
                    flash(f'{ad} ilacı eklendi ancak JSON kayıt hatası: API yanıt kodu {response.status_code}', 'warning')
                    
            except Exception as e:
                print(f"İlaç ekleme JSON hatası: {str(e)}")
                flash(f'{ad} ilacı eklendi ancak JSON kayıt hatası: {str(e)}', 'warning')
        else:
            flash(f'{ad} ilacı başarıyla eklendi.', 'success')
        
        return redirect(url_for('ilaclar'))
    
    # Tüm ilaçları getir
    ilaclar = Ilac.query.all()
    
    # Her istekte en güncel verileri almak için zaman damgası oluşturalım
    timestamp = int(time.time())
    
    # API sunucusundan veri al
    try:
        # API sunucusundan JSON veriyi al
        response = requests.get('http://localhost:3000/api/ilaclar')
        
        if response.status_code == 200:
            zirai_ilaclar = response.json()
            
            # Verileri ilac.html şablonuna uygun formata dönüştür
            initial_ilaclar = []
            for ilac in zirai_ilaclar:
                initial_ilaclar.append({
                    'ad': ilac.get('ad', '') or ilac.get('ilac_adi', ''),
                    'etken_madde': ilac.get('etken_madde', ''),
                    'hedef_hastalik': ilac.get('hedef_hastalik', '') or ilac.get('hastalik', ''),
                    'dozaj': str(ilac.get('dozaj', '')),
                    'grup': ilac.get('grup', ''),
                    'hasat_suresi': ilac.get('hasat_suresi', ''),
                    'uyari': ilac.get('uyari', '')
                })
            
            print(f"API'den ilac listesi yüklendi: {len(initial_ilaclar)} ilaç.")
        else:
            print(f"API ilac listesi yükleme hatası: HTTP {response.status_code}")
            initial_ilaclar = []
            
    except Exception as e:
        print(f"API ilac listesi yükleme hatası: {e}")
        initial_ilaclar = []
        
        # API hatası durumunda dosyadan yüklemeyi dene (yedek çözüm)
        try:
            # Dosyadan oku
            with open('data/ilaclar_autocomplete.json', 'r', encoding='utf-8') as f:
                zirai_ilaclar = json.load(f)
                    
            # Verileri ilac.html şablonuna uygun formata dönüştür
            initial_ilaclar = []
            for ilac in zirai_ilaclar:
                # Dozaj bilgisini sayısal formata dönüştür
                dozaj_str = ilac.get('dozaj', '0')
                if dozaj_str is None:
                    dozaj_str = '0'
                # Sadece sayısal kısmı al
                dozaj_match = re.search(r'(\d+(?:\.\d+)?)', str(dozaj_str))
                dozaj_value = float(dozaj_match.group(1)) if dozaj_match else 0
                
                initial_ilaclar.append({
                    'ad': ilac.get('ad', '') or ilac.get('ilac_adi', ''),
                    'etken_madde': ilac.get('etken_madde', ''),
                    'hedef_hastalik': ilac.get('hedef_hastalik', '') or ilac.get('hastalik', ''),
                    'dozaj': str(ilac.get('dozaj', '')),
                    'grup': ilac.get('grup', ''),
                    'hasat_suresi': ilac.get('hasat_suresi', ''),
                    'uyari': ilac.get('uyari', '')
                })
            print(f"Dosyadan ilac listesi yüklendi (yedek çözüm): {len(initial_ilaclar)} ilaç.")
        except Exception as backup_e:
            print(f"Dosyadan ilac listesi yükleme hatası: {backup_e}")
            initial_ilaclar = []
    
    # Tarayıcı önbelleğini devre dışı bırakacak başlıkları ekleyelim
    # Kapasite hesapla
    def calc_kapasite(miktar, birim, dozaj_str):
        import re as _re
        if not dozaj_str:
            return None, None
        m = _re.search(r'(\d+(?:[.,]\d+)?)', str(dozaj_str))
        if not m:
            return None, None
        try:
            doz = float(m.group(1).replace(',', '.'))
        except Exception:
            return None, None
        if doz <= 0:
            return None, None
        # lt ve kg'ı 1000 ile çarp
        if birim in ('lt', 'kg'):
            stok_base = miktar * 1000
        else:  # ml, gr
            stok_base = miktar
        uygulama_litre = (stok_base / doz) * 100
        taral = uygulama_litre / 1600
        return round(uygulama_litre, 1), round(taral, 2)

    ilac_hesaplar = {}
    for ilac in ilaclar:
        ul, tr = calc_kapasite(ilac.miktar, ilac.birim, ilac.dozaj)
        ilac_hesaplar[ilac.id] = {
            'uygulama_litre': ul,
            'taral': tr,
            'dusuk': (tr is not None and tr < 1)
        }

    # Son uygulama tarihleri (her ilaç için en son kullanım)
    from sqlalchemy import func as _sql_func
    ilac_son_uygulama = dict(
        db.session.query(IlacKullanim.ilac_id, _sql_func.max(IlacKullanim.tarih))
        .group_by(IlacKullanim.ilac_id).all()
    )

    # Hedef hastalık dropdown (canonical key ile grupla) → [(label, key), ...]
    _grups = {}
    for il in ilaclar:
        if not il.hedef_hastalik:
            continue
        for h in il.hedef_hastalik.split('/'):
            h = h.strip()
            if not h:
                continue
            k = _hastalik_key(h)
            if not k:
                continue
            _grups.setdefault(k, [])
            if h not in _grups[k]:
                _grups[k].append(h)
    hastalik_dropdown = []
    for k, labels in _grups.items():
        labels_sorted = sorted(labels, key=lambda s: (0 if not s.lower().startswith('bağ') else 1, len(s)))
        hastalik_dropdown.append((labels_sorted[0], k))
    hastalik_dropdown.sort(key=lambda x: x[0])

    response = make_response(render_template('ilac.html', ilaclar=ilaclar, initial_ilaclar=initial_ilaclar, ilac_hesaplar=ilac_hesaplar, ilac_son_uygulama=ilac_son_uygulama, hastalik_dropdown=hastalik_dropdown))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

@app.route('/ilac/duzenle/<int:id>', methods=['POST'])
@login_required
def ilac_duzenle(id):
    ilac = Ilac.query.get_or_404(id)
    
    # Önceki değerleri sakla
    eski_ad = ilac.ad
    
    # Yeni değerleri al
    ilac.ad = request.form['ad']
    ilac.etken_madde = request.form.get('etken_madde', '')
    ilac.hedef_hastalik = request.form.get('hedef_hastalik', '')
    ilac.miktar = float(request.form['miktar'])
    ilac.birim = request.form['birim']
    ilac.dozaj = request.form.get('dozaj', '').strip()
    ilac.grup = request.form.get('grup', '').strip()
    ilac.hasat_suresi = request.form.get('hasat_suresi', '').strip()
    ilac.hasat_suresi_gun = parse_hasat_gun(ilac.hasat_suresi)
    ilac.uyari = request.form.get('uyari', '').strip()
    ilac.min_stok = float(request.form.get('min_stok', 100))
    _bf = request.form.get('birim_fiyat', '').strip()
    _at = request.form.get('alim_tarihi', '').strip()
    try:
        ilac.birim_fiyat = float(_bf) if _bf else None
    except ValueError:
        pass
    try:
        ilac.alim_tarihi = datetime.datetime.strptime(_at, '%Y-%m-%d').date() if _at else None
    except ValueError:
        pass
    _skt = request.form.get('son_kullanma_tarihi', '').strip()
    _ac = request.form.get('acilma_tarihi', '').strip()
    ilac.lot_no = request.form.get('lot_no', '').strip() or None
    try:
        ilac.son_kullanma_tarihi = datetime.datetime.strptime(_skt, '%Y-%m-%d').date() if _skt else None
    except ValueError:
        pass
    try:
        ilac.acilma_tarihi = datetime.datetime.strptime(_ac, '%Y-%m-%d').date() if _ac else None
    except ValueError:
        pass
    _tra = request.form.get('tekrar_araligi_gun', '').strip()
    try:
        ilac.tekrar_araligi_gun = int(_tra) if _tra else None
    except ValueError:
        pass

    # Veritabanına kaydet
    db.session.commit()
    
    # JSON'a da kaydetmek isteniyor mu?
    kaydet_json = 'kaydet_json' in request.form
    
    if kaydet_json:
        try:
            # JSON formatında ilaç verisi oluştur
            ilac_json = {
                "ad": ilac.ad,
                "etken_madde": ilac.etken_madde,
                "hedef_hastalik": ilac.hedef_hastalik,
                "dozaj": ilac.dozaj,
                "birim": ilac.birim,
                "miktar": ilac.miktar
            }
            
            # API sunucusu üzerinden JSON veritabanını güncelle
            response = requests.post('http://localhost:3000/api/ilaclar', json=ilac_json)
            
            if response.status_code == 200:
                print(f"İlaç düzenleme: '{ilac.ad}' başarıyla JSON'a güncellendi (API üzerinden).")
                flash(f'{ilac.ad} ilacı başarıyla güncellendi ve JSON veritabanında güncellendi.', 'success')
            else:
                print(f"İlaç düzenleme API hatası: {response.text}")
                flash(f'{ilac.ad} ilacı güncellendi ancak JSON güncelleme hatası: API yanıt kodu {response.status_code}', 'warning')
                
        except Exception as e:
            flash(f'{ilac.ad} ilacı güncellendi ancak JSON güncelleme hatası: {str(e)}', 'warning')
    else:
        flash(f'{ilac.ad} ilacı başarıyla güncellendi.', 'success')
        
    # Doğrudan /ilaclar sayfasına yönlendirmek yerine, önce bir temizleme isteği yapalım
    response = make_response(redirect(url_for('ilaclar')))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

@app.route('/ilac/sil/<int:id>', methods=['POST'])
@login_required
def ilac_sil(id):
    ilac = Ilac.query.get_or_404(id)
    
    # İlacın kullanım kayıtlarını da sil
    IlacKullanim.query.filter_by(ilac_id=id).delete()
    
    db.session.delete(ilac)
    db.session.commit()
    flash('İlaç başarıyla silindi', 'success')
    return redirect(url_for('ilaclar'))

# ----- GÜBRE YÖNETİMİ -----
@app.route('/gubreler', methods=['GET', 'POST'])
@login_required
def gubreler():
    if request.method == 'POST':
        # Yeni gübre ekleme
        ad = request.form['ad']
        formulasyon = request.form['formulasyon']
        kategori = request.form.get('kategori', '')
        miktar = float(request.form['miktar'])
        birim = request.form['birim']
        kullanim_alani = request.form['kullanim_alani']
        uygulama_dozu = float(request.form['uygulama_dozu']) if request.form.get('uygulama_dozu') else None
        yaprak_dozu = float(request.form['yaprak_dozu']) if request.form.get('yaprak_dozu') else None
        not_bilgisi = request.form['not_bilgisi']
        _gbf = request.form.get('birim_fiyat', '').strip()
        _gat = request.form.get('alim_tarihi', '').strip()
        try:
            g_birim_fiyat = float(_gbf) if _gbf else None
        except ValueError:
            g_birim_fiyat = None
        try:
            g_alim_tarihi = datetime.datetime.strptime(_gat, '%Y-%m-%d').date() if _gat else None
        except ValueError:
            g_alim_tarihi = None
        _gskt = request.form.get('son_kullanma_tarihi', '').strip()
        g_lot_no = request.form.get('lot_no', '').strip() or None
        _gac = request.form.get('acilma_tarihi', '').strip()
        try:
            g_skt = datetime.datetime.strptime(_gskt, '%Y-%m-%d').date() if _gskt else None
        except ValueError:
            g_skt = None
        try:
            g_acilma = datetime.datetime.strptime(_gac, '%Y-%m-%d').date() if _gac else None
        except ValueError:
            g_acilma = None

        # Aynı isimde gübre varsa miktarı güncelle, yoksa yeni kayıt aç
        mevcut = Gubre.query.filter(
            db.func.lower(Gubre.ad) == _normalize_ad(ad)
        ).first()

        if mevcut:
            mevcut.miktar += miktar
            # Boş alanları doldur
            if formulasyon and not mevcut.formulasyon:
                mevcut.formulasyon = formulasyon
            if kategori and not mevcut.kategori:
                mevcut.kategori = kategori
            if kullanim_alani and not mevcut.kullanim_alani:
                mevcut.kullanim_alani = kullanim_alani
            if uygulama_dozu and not mevcut.uygulama_dozu:
                mevcut.uygulama_dozu = uygulama_dozu
            if yaprak_dozu and not mevcut.yaprak_dozu:
                mevcut.yaprak_dozu = yaprak_dozu
            if g_birim_fiyat is not None:
                mevcut.birim_fiyat = g_birim_fiyat
            if g_alim_tarihi:
                mevcut.alim_tarihi = g_alim_tarihi
            if g_skt:
                mevcut.son_kullanma_tarihi = g_skt
            if g_lot_no:
                mevcut.lot_no = g_lot_no
            if g_acilma:
                mevcut.acilma_tarihi = g_acilma
            log_stok('gubre', mevcut.id, 'GIRIS', miktar,
                     birim=mevcut.birim, birim_fiyat=g_birim_fiyat,
                     not_bilgisi='Stok ekleme', referans='gubre_ekle')
            db.session.commit()
            flash(f'{ad} stoğa eklendi → Yeni toplam: {mevcut.miktar} {mevcut.birim}', 'success')
        else:
            yeni_gubre = Gubre(
                ad=ad,
                formulasyon=formulasyon,
                kategori=kategori,
                miktar=miktar,
                birim=birim,
                kullanim_alani=kullanim_alani,
                uygulama_dozu=uygulama_dozu,
                yaprak_dozu=yaprak_dozu,
                not_bilgisi=not_bilgisi,
                birim_fiyat=g_birim_fiyat,
                alim_tarihi=g_alim_tarihi,
                son_kullanma_tarihi=g_skt,
                lot_no=g_lot_no,
                acilma_tarihi=g_acilma,
            )
            db.session.add(yeni_gubre)
            db.session.flush()
            log_stok('gubre', yeni_gubre.id, 'GIRIS', miktar,
                     birim=birim, birim_fiyat=g_birim_fiyat,
                     not_bilgisi='İlk kayıt', referans='gubre_ekle')
            db.session.commit()
            flash(f'{ad} gübre olarak eklendi.', 'success')
        return redirect(url_for('gubreler'))
    
    # Tüm gübreleri getir
    gubreler = Gubre.query.all()
    from sqlalchemy import func as _sql_func
    gubre_son_uygulama = dict(
        db.session.query(GubreKullanim.gubre_id, _sql_func.max(GubreKullanim.tarih))
        .group_by(GubreKullanim.gubre_id).all()
    )
    return render_template('gubre.html', gubreler=gubreler, gubre_son_uygulama=gubre_son_uygulama)

@app.route('/gubre/duzenle/<int:id>', methods=['POST'])
@login_required
def gubre_duzenle(id):
    gubre = Gubre.query.get_or_404(id)
    gubre.ad = request.form['ad']
    gubre.formulasyon = request.form['formulasyon']
    gubre.kategori = request.form.get('kategori', '')
    gubre.miktar = float(request.form['miktar'])
    gubre.birim = request.form['birim']
    gubre.kullanim_alani = request.form['kullanim_alani']
    gubre.uygulama_dozu = float(request.form['uygulama_dozu']) if request.form.get('uygulama_dozu') else None
    gubre.yaprak_dozu = float(request.form['yaprak_dozu']) if request.form.get('yaprak_dozu') else None
    gubre.not_bilgisi = request.form['not_bilgisi']
    _gbf = request.form.get('birim_fiyat', '').strip()
    _gat = request.form.get('alim_tarihi', '').strip()
    try:
        gubre.birim_fiyat = float(_gbf) if _gbf else None
    except ValueError:
        pass
    try:
        gubre.alim_tarihi = datetime.datetime.strptime(_gat, '%Y-%m-%d').date() if _gat else None
    except ValueError:
        pass
    _gskt = request.form.get('son_kullanma_tarihi', '').strip()
    _gac = request.form.get('acilma_tarihi', '').strip()
    gubre.lot_no = request.form.get('lot_no', '').strip() or None
    try:
        gubre.son_kullanma_tarihi = datetime.datetime.strptime(_gskt, '%Y-%m-%d').date() if _gskt else None
    except ValueError:
        pass
    try:
        gubre.acilma_tarihi = datetime.datetime.strptime(_gac, '%Y-%m-%d').date() if _gac else None
    except ValueError:
        pass

    db.session.commit()
    flash('Gübre başarıyla güncellendi', 'success')
    return redirect(url_for('gubreler'))

@app.route('/gubre/sil/<int:id>', methods=['POST'])
@login_required
def gubre_sil(id):
    gubre = Gubre.query.get_or_404(id)
    
    # Gübrenin kullanım kayıtlarını da sil
    GubreKullanim.query.filter_by(gubre_id=id).delete()
    
    db.session.delete(gubre)
    db.session.commit()
    flash('Gübre başarıyla silindi', 'success')
    return redirect(url_for('gubreler'))

@app.route('/api/gubre-katalog', methods=['GET'])
@login_required
def api_gubre_katalog_liste():
    """Katalogdaki tüm ürünleri döndürür (dropdown için)."""
    rows = db.session.execute(
        db.text('SELECT id, ad, kategori FROM gubre_katalog ORDER BY kategori, ad')
    ).fetchall()
    return jsonify([{'id': r[0], 'ad': r[1], 'kategori': r[2]} for r in rows])

@app.route('/api/gubre-katalog/<int:katalog_id>', methods=['GET'])
@login_required
def api_gubre_katalog_detay(katalog_id):
    """Katalog ürün detayını döndürür (form doldurma için)."""
    row = db.session.execute(
        db.text('SELECT id, ad, kategori, formulasyon, aciklama, yaprak_dozu_min, yaprak_dozu_max, damlama_dozu_min, damlama_dozu_max, kullanim_alani, ambalaj_secenekleri, kaynak FROM gubre_katalog WHERE id = :id'),
        {'id': katalog_id}
    ).fetchone()
    if not row:
        return jsonify({'error': 'Bulunamadı'}), 404
    return jsonify({
        'id': row[0], 'ad': row[1], 'kategori': row[2], 'formulasyon': row[3],
        'aciklama': row[4], 'yaprak_dozu_min': row[5], 'yaprak_dozu_max': row[6],
        'damlama_dozu_min': row[7], 'damlama_dozu_max': row[8],
        'kullanim_alani': row[9], 'ambalaj_secenekleri': row[10], 'kaynak': row[11]
    })

@app.route('/api/gubre-katalog/ekle', methods=['POST'])
@login_required
def api_gubre_katalog_ekle():
    """Manuel eklenen ürünü kataloğa kaydeder."""
    data = request.get_json()
    if not data or not data.get('ad'):
        return jsonify({'error': 'Ad zorunlu'}), 400
    try:
        db.session.execute(db.text("""
            INSERT INTO gubre_katalog (ad, kategori, formulasyon, yaprak_dozu_min, yaprak_dozu_max, damlama_dozu_min, damlama_dozu_max, kullanim_alani, kaynak)
            VALUES (:ad, :kategori, :formulasyon, :yaprak_dozu_min, :yaprak_dozu_max, :damlama_dozu_min, :damlama_dozu_max, :kullanim_alani, 'manuel')
            ON CONFLICT (ad, kaynak) DO UPDATE SET
                kategori=EXCLUDED.kategori, formulasyon=EXCLUDED.formulasyon
        """), {
            'ad': data.get('ad'), 'kategori': data.get('kategori'),
            'formulasyon': data.get('formulasyon'),
            'yaprak_dozu_min': data.get('yaprak_dozu'), 'yaprak_dozu_max': data.get('yaprak_dozu'),
            'damlama_dozu_min': data.get('uygulama_dozu'), 'damlama_dozu_max': data.get('uygulama_dozu'),
            'kullanim_alani': data.get('kullanim_alani')
        })
        db.session.commit()
        # Yeni eklenen id'yi bul
        row = db.session.execute(
            db.text("SELECT id FROM gubre_katalog WHERE ad=:ad AND kaynak='manuel'"),
            {'ad': data.get('ad')}
        ).fetchone()
        return jsonify({'success': True, 'katalog_id': row[0] if row else None})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ----- İLAÇ KULLANIM YÖNETİMİ -----
@app.route('/ilac-kullanim', methods=['GET', 'POST'])
@login_required
def ilac_kullanim():
    if request.method == 'POST':
        su_miktari = float(request.form['su_miktari'])
        ilac_ids = request.form.getlist('ilac_ids[]')
        
        basarili_kayitlar = 0
        hatalar = []
        bag_id_val = int(request.form.get('bag_id')) if request.form.get('bag_id') else None
        
        # Her ilaç için ayrı kayıt oluştur
        for ilac_id in ilac_ids:
            if not ilac_id:
                continue  # Boş seçimleri atla
                
            try:
                ilac_id = int(ilac_id)
                
                # İlacı bulalım
                ilac = Ilac.query.get_or_404(ilac_id)
                
                # Dozaj hesaplaması (100 litre suya ne kadar ilaç)
                dozaj_str = str(ilac.dozaj or '0')
                dozaj_match = re.search(r'(\d+(?:[.,]\d+)?)', dozaj_str)
                dozaj_sayi = float(dozaj_match.group(1).replace(',', '.')) if dozaj_match else 0.0
                gereken_ilac_miktari = (su_miktari / 100) * dozaj_sayi
                
                # Stok kontrolü
                if gereken_ilac_miktari > ilac.miktar:
                    hatalar.append(f'Stokta yeterli {ilac.ad} bulunmuyor! Gereken: {gereken_ilac_miktari:.2f} {ilac.birim}')
                    continue
                
                # Kullanım kaydı oluştur
                yeni_kullanim = IlacKullanim(
                    ilac_id=ilac_id,
                    bag_id=bag_id_val,
                    kullanilan_miktar=gereken_ilac_miktari,
                    su_miktari=su_miktari
                )
                
                # Stoktan düş
                ilac.miktar -= gereken_ilac_miktari

                db.session.add(yeni_kullanim)
                db.session.flush()
                _bag = Bag.query.get(bag_id_val) if bag_id_val else None
                log_stok('ilac', ilac.id, 'CIKIS', gereken_ilac_miktari,
                         birim=ilac.birim, birim_fiyat=ilac.birim_fiyat,
                         not_bilgisi=f'Kullanım — {_bag.ad if _bag else "—"}',
                         referans=f'IlacKullanim#{yeni_kullanim.id}')
                basarili_kayitlar += 1
                
            except Exception as e:
                hatalar.append(f'Hata: {ilac_id} kimlikli ilaç işlenirken bir hata oluştu - {str(e)}')
        
        # Tüm değişiklikleri commit et
        if basarili_kayitlar > 0:
            db.session.commit()
            flash(f'{basarili_kayitlar} ilaç kullanımı kaydedildi.', 'success')
        
        # Hataları göster
        for hata in hatalar:
            flash(hata, 'danger')
            
        return redirect(url_for('ilac_kullanim'))
    
    # Mevcut ilaçları ve bağları getir
    ilaclar = Ilac.query.all()
    baglar = Bag.query.filter_by(aktif=True).all()
    # Gruplama için yeterli kayıt al (100), sonra ilk 10 grubu al
    son_kullanimlar_raw = IlacKullanim.query.order_by(IlacKullanim.tarih.desc()).limit(100).all()
    tr_timezone = pytz.timezone('Europe/Istanbul')
    def utc_to_tr_ilac(utc_dt):
        if not utc_dt:
            return None
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=pytz.UTC)
        return utc_dt.astimezone(tr_timezone)
    gruplari = IlacKullanim.grup_kayitlari(son_kullanimlar_raw)
    son_grup_kullanimlari = sorted(gruplari.values(), key=lambda x: x['tarih'], reverse=True)[:10]
    for grup in son_grup_kullanimlari:
        grup['tr_tarih'] = utc_to_tr_ilac(grup['tarih'])

    return render_template('ilac_kullanim.html', ilaclar=ilaclar, baglar=baglar, son_grup_kullanimlari=son_grup_kullanimlari)

# ----- GÜBRE KULLANIM YÖNETİMİ -----
@app.route('/gubre-kullanim', methods=['GET', 'POST'])
@login_required
def gubre_kullanim():
    if request.method == 'POST':
        gubre_id = int(request.form['gubre_id'])
        kullanilan_miktar = float(request.form['kullanilan_miktar'])
        alan = float(request.form['alan']) if request.form['alan'] else None
        bag_id = int(request.form['bag_id']) if request.form.get('bag_id') else None
        
        # Gübreyi bulalım
        gubre = Gubre.query.get_or_404(gubre_id)
        
        # Stok kontrolü
        if kullanilan_miktar > gubre.miktar:
            flash(f'Stokta yeterli {gubre.ad} bulunmuyor! Gereken: {kullanilan_miktar} {gubre.birim}', 'danger')
            return redirect(url_for('gubre_kullanim'))
        
        # Kullanım kaydı oluştur
        yeni_kullanim = GubreKullanim(
            gubre_id=gubre_id,
            bag_id=bag_id,
            kullanilan_miktar=kullanilan_miktar,
            alan=alan
        )
        
        # Stoktan düş
        gubre.miktar -= kullanilan_miktar

        db.session.add(yeni_kullanim)
        db.session.flush()
        _bag = Bag.query.get(bag_id) if bag_id else None
        log_stok('gubre', gubre.id, 'CIKIS', kullanilan_miktar,
                 birim=gubre.birim, birim_fiyat=gubre.birim_fiyat,
                 not_bilgisi=f'Kullanım — {_bag.ad if _bag else "—"}',
                 referans=f'GubreKullanim#{yeni_kullanim.id}')
        db.session.commit()
        flash(f'Gübre kullanımı kaydedildi. {kullanilan_miktar} {gubre.birim} kullanıldı.', 'success')
        return redirect(url_for('gubre_kullanim'))
    
# Mevcut gübreleri ve bağları getir
    gubreler = Gubre.query.all()
    baglar = Bag.query.filter_by(aktif=True).all()
    son_kullanimlar = GubreKullanim.query.order_by(GubreKullanim.tarih.desc()).limit(10).all()
    
    return render_template('gubre_kullanim.html', gubreler=gubreler, baglar=baglar, son_kullanimlar=son_kullanimlar)

# ----- RAPORLAR -----
@app.route('/raporlar')
@login_required
def raporlar():
    rapor_turu = request.args.get('rapor_turu', 'gunluk')
    baslangic_tarih = request.args.get('baslangic_tarih')
    bitis_tarih = request.args.get('bitis_tarih')
    
    # Varsayılan tarih aralıkları
    now = datetime.datetime.now()
    
    if rapor_turu == 'gunluk':
        baslangic = now.replace(hour=0, minute=0, second=0, microsecond=0)
        bitis = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif rapor_turu == 'aylik':
        baslangic = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            bitis = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(microseconds=1)
        else:
            bitis = now.replace(month=now.month+1, day=1, hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(microseconds=1)
    elif rapor_turu == 'yillik':
        baslangic = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        bitis = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(microseconds=1)
    else:
        baslangic = now - datetime.timedelta(days=30)
        bitis = now
    
    # Özel tarih aralığı belirtilmişse onu kullan
    if baslangic_tarih:
        baslangic = datetime.datetime.strptime(baslangic_tarih, '%Y-%m-%d')
    if bitis_tarih:
        bitis = datetime.datetime.strptime(bitis_tarih, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    
    # İlaç kullanımları
    ilac_kullanimlari = IlacKullanim.query.filter(
        IlacKullanim.tarih >= baslangic,
        IlacKullanim.tarih <= bitis
    ).order_by(IlacKullanim.tarih.desc()).all()
    
    # Gübre kullanımları
    gubre_kullanimlari = GubreKullanim.query.filter(
        GubreKullanim.tarih >= baslangic,
        GubreKullanim.tarih <= bitis
    ).order_by(GubreKullanim.tarih.desc()).all()
    
    return render_template(
        'rapor.html',
        rapor_turu=rapor_turu,
        baslangic=baslangic,
        bitis=bitis,
        ilac_kullanimlari=ilac_kullanimlari,
        gubre_kullanimlari=gubre_kullanimlari
    )


@app.route('/raporlar/maliyet')
@login_required
def raporlar_maliyet():
    """Parsel bazlı ve aylık maliyet raporu (ilaç + gübre)."""
    yil = int(request.args.get('yil', datetime.datetime.now().year))
    baslangic = datetime.datetime(yil, 1, 1)
    bitis = datetime.datetime(yil, 12, 31, 23, 59, 59)

    ilac_kayitlari = IlacKullanim.query.filter(
        IlacKullanim.tarih >= baslangic, IlacKullanim.tarih <= bitis
    ).all()
    gubre_kayitlari = GubreKullanim.query.filter(
        GubreKullanim.tarih >= baslangic, GubreKullanim.tarih <= bitis
    ).all()

    # Parsel bazlı toplam: {bag_id: {'bag': Bag, 'ilac_tl': X, 'gubre_tl': Y, 'alan': dönüm}}
    parsel = {}
    baglar = {b.id: b for b in Bag.query.all()}

    def _parsel_entry(bag_id):
        if bag_id not in parsel:
            bag = baglar.get(bag_id)
            parsel[bag_id] = {
                'bag': bag,
                'alan': bag.alan if bag else 0,
                'ilac_tl': 0.0, 'gubre_tl': 0.0,
                'ilac_count': 0, 'gubre_count': 0,
            }
        return parsel[bag_id]

    aylik = {m: {'ilac': 0.0, 'gubre': 0.0} for m in range(1, 13)}

    for k in ilac_kayitlari:
        fiyat = (k.ilac.birim_fiyat or 0) if k.ilac else 0
        tl = (k.kullanilan_miktar or 0) * fiyat
        if k.bag_id:
            p = _parsel_entry(k.bag_id)
            p['ilac_tl'] += tl
            p['ilac_count'] += 1
        if k.tarih:
            aylik[k.tarih.month]['ilac'] += tl

    for k in gubre_kayitlari:
        fiyat = (k.gubre.birim_fiyat or 0) if k.gubre else 0
        tl = (k.kullanilan_miktar or 0) * fiyat
        if k.bag_id:
            p = _parsel_entry(k.bag_id)
            p['gubre_tl'] += tl
            p['gubre_count'] += 1
        if k.tarih:
            aylik[k.tarih.month]['gubre'] += tl

    parsel_list = []
    for b in parsel.values():
        toplam = b['ilac_tl'] + b['gubre_tl']
        alan = b['alan'] or 0
        tl_per_donum = (toplam / alan) if alan > 0 else 0
        parsel_list.append({
            **b,
            'toplam_tl': toplam,
            'tl_per_donum': tl_per_donum,
        })
    parsel_list.sort(key=lambda x: -x['toplam_tl'])

    toplam_ilac = sum(a['ilac'] for a in aylik.values())
    toplam_gubre = sum(a['gubre'] for a in aylik.values())

    return render_template(
        'rapor_maliyet.html',
        yil=yil,
        parsel_list=parsel_list,
        aylik=aylik,
        toplam_ilac=toplam_ilac,
        toplam_gubre=toplam_gubre,
        toplam_genel=toplam_ilac + toplam_gubre,
    )


@app.route('/raporlar/pdf')
@login_required
def raporlar_pdf():
    """Resmi Zirai İlaç Defteri — PDF çıktı."""
    baslangic_tarih = request.args.get('baslangic_tarih')
    bitis_tarih = request.args.get('bitis_tarih')
    uygulayici = (request.args.get('uygulayici') or 'Kenan Türköz').strip() or '-'

    now = datetime.datetime.now()
    if baslangic_tarih:
        baslangic = datetime.datetime.strptime(baslangic_tarih, '%Y-%m-%d')
    else:
        baslangic = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    if bitis_tarih:
        bitis = datetime.datetime.strptime(bitis_tarih, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    else:
        bitis = now

    kullanimlar = IlacKullanim.query.filter(
        IlacKullanim.tarih >= baslangic,
        IlacKullanim.tarih <= bitis
    ).order_by(IlacKullanim.tarih.asc()).all()

    pdf_bytes = zirai_ilac_defteri_pdf(kullanimlar, baslangic, bitis, uygulayici=uygulayici)
    filename = f'zirai-ilac-defteri-{baslangic.strftime("%Y%m%d")}-{bitis.strftime("%Y%m%d")}.pdf'

    from flask import Response
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(len(pdf_bytes)),
        },
    )


# ----- HARİTA -----
@app.route('/baglar/harita')
@login_required
def baglar_harita():
    """Tüm bağları Leaflet haritasında göster."""
    pins = []
    all_hos = {h['bag'].id: h for h in compute_all_bag_hos()}
    for bag in Bag.query.filter_by(aktif=True).all():
        coords = parse_gps(bag.gps_koordinat) if bag.gps_koordinat else None
        if not coords:
            continue
        hos = all_hos.get(bag.id)
        renk = '#198754'  # yeşil — ok
        durum = 'Uygun'
        if hos and hos['aktif']:
            renk = '#dc3545'
            durum = f'HÖS aktif — {hos["kalan_gun"]} gün kaldı'
        son_ilaclama = bag.son_ilaclama()
        pins.append({
            'id': bag.id, 'ad': bag.ad, 'alan': bag.alan,
            'ekim_tipi': bag.ekim_tipi or '',
            'lat': coords[0], 'lon': coords[1],
            'renk': renk, 'durum': durum,
            'son_ilaclama': son_ilaclama.tarih.strftime('%d.%m.%Y') if son_ilaclama and son_ilaclama.tarih else None,
        })
    return render_template('bag_harita.html', pins=pins)


# ----- TAKVİM -----
@app.route('/takvim')
@login_required
def takvim():
    return render_template('takvim.html')


@app.route('/takvim/feed.json')
@login_required
def takvim_feed():
    """FullCalendar event feed: ilaç, gübre kullanımları + HÖS blokları."""
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    try:
        start = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00')) if start_str else datetime.datetime.now() - datetime.timedelta(days=30)
        end = datetime.datetime.fromisoformat(end_str.replace('Z', '+00:00')) if end_str else datetime.datetime.now() + datetime.timedelta(days=60)
    except Exception:
        start = datetime.datetime.now() - datetime.timedelta(days=30)
        end = datetime.datetime.now() + datetime.timedelta(days=60)

    start_naive = start.replace(tzinfo=None) if start.tzinfo else start
    end_naive = end.replace(tzinfo=None) if end.tzinfo else end

    events = []

    ilac_kayitlari = IlacKullanim.query.filter(
        IlacKullanim.tarih >= start_naive,
        IlacKullanim.tarih <= end_naive,
    ).all()
    for k in ilac_kayitlari:
        bag_ad = k.bag.ad if k.bag else 'Bilinmeyen'
        ilac_ad = k.ilac.ad if k.ilac else '-'
        events.append({
            'id': f'ilac-{k.id}',
            'title': f'💊 {ilac_ad} — {bag_ad}',
            'start': k.tarih.isoformat(),
            'backgroundColor': '#0d6efd',
            'borderColor': '#0d6efd',
            'extendedProps': {
                'description': f'{round(k.kullanilan_miktar, 2)} {k.ilac.birim if k.ilac else ""} · Su: {k.su_miktari}L',
                'url': url_for('bag_detay', id=k.bag_id) if k.bag_id else None,
            },
        })

    gubre_kayitlari = GubreKullanim.query.filter(
        GubreKullanim.tarih >= start_naive,
        GubreKullanim.tarih <= end_naive,
    ).all()
    for k in gubre_kayitlari:
        bag_ad = k.bag.ad if k.bag else 'Bilinmeyen'
        gubre_ad = k.gubre.ad if k.gubre else '-'
        events.append({
            'id': f'gubre-{k.id}',
            'title': f'🌱 {gubre_ad} — {bag_ad}',
            'start': k.tarih.isoformat(),
            'backgroundColor': '#198754',
            'borderColor': '#198754',
            'extendedProps': {
                'description': f'{round(k.kullanilan_miktar, 2)} {k.gubre.birim if k.gubre else ""}',
                'url': url_for('bag_detay', id=k.bag_id) if k.bag_id else None,
            },
        })

    # HÖS blokları (her bag için aktif HÖS aralığını bir blok olarak çiz)
    try:
        for h in compute_all_bag_hos():
            if not h.get('aktif'):
                continue
            bag = h['bag']
            guvenli = h.get('guvenli_tarih')
            kayitlar = h.get('kayitlar') or []
            # HÖS bloğunun başlangıcı: en son uygulanan ilacın tarihi
            son_uyg = max((k['tarih'] for k in kayitlar), default=None)
            if son_uyg and guvenli:
                events.append({
                    'id': f'hos-{bag.id}-{son_uyg.isoformat()}',
                    'title': f'HÖS — {bag.ad}',
                    'start': son_uyg.isoformat(),
                    'end': (guvenli + datetime.timedelta(days=1)).isoformat(),
                    'backgroundColor': '#dc3545',
                    'borderColor': '#dc3545',
                    'display': 'background',
                    'extendedProps': {
                        'description': f'Güvenli hasat: {guvenli.strftime("%d.%m.%Y")} ({h["kalan_gun"]} gün)',
                        'url': url_for('bag_detay', id=bag.id),
                    },
                })
    except Exception as e:
        app.logger.exception(f'takvim HÖS hatası: {e}')

    return jsonify(events)


# ----- STOK HAREKET -----
@app.route('/stok-hareket/<urun_type>/<int:urun_id>')
@login_required
def stok_hareket(urun_type, urun_id):
    if urun_type not in ('ilac', 'gubre'):
        flash('Geçersiz ürün tipi.', 'danger')
        return redirect(url_for('index'))
    urun = (Ilac if urun_type == 'ilac' else Gubre).query.get_or_404(urun_id)
    hareketler = StokHareket.query.filter_by(urun_type=urun_type, urun_id=urun_id)\
        .order_by(StokHareket.tarih.desc()).all()

    toplam_giris = sum(h.miktar for h in hareketler if h.tip == 'GIRIS')
    toplam_cikis = sum(h.miktar for h in hareketler if h.tip == 'CIKIS')
    maliyet_giris = sum((h.miktar * (h.birim_fiyat or 0)) for h in hareketler if h.tip == 'GIRIS')

    return render_template(
        'stok_hareket.html',
        urun=urun, urun_type=urun_type,
        hareketler=hareketler,
        toplam_giris=toplam_giris,
        toplam_cikis=toplam_cikis,
        maliyet_giris=maliyet_giris,
    )


# ----- FOTOĞRAF UPLOAD -----
_PHOTO_PARENT_TYPES = ('bag', 'ilac_kullanim', 'gubre_kullanim')


@app.route('/foto/yukle/<parent_type>/<int:parent_id>', methods=['POST'])
@login_required
def foto_yukle(parent_type, parent_id):
    if parent_type not in _PHOTO_PARENT_TYPES:
        flash('Geçersiz kayıt tipi.', 'danger')
        return redirect(request.referrer or url_for('index'))

    files = request.files.getlist('foto')
    caption = request.form.get('caption', '').strip()
    ai_teshis_iste = request.form.get('ai_teshis') == '1'

    if not files or all((not f.filename for f in files)):
        flash('Dosya seçilmedi.', 'warning')
        return redirect(request.referrer or url_for('index'))

    sayac = 0
    for f in files:
        if not f or not f.filename:
            continue
        try:
            key, mime = put_photo(f, parent_type, parent_id)
        except ValueError as ve:
            flash(f'{f.filename}: {ve}', 'warning')
            continue
        except Exception as e:
            app.logger.exception(f'Foto yükleme hatası: {e}')
            flash(f'{f.filename}: yüklenemedi.', 'danger')
            continue

        ai_text = None
        if ai_teshis_iste and mime.startswith('image/'):
            try:
                f.stream.seek(0)
                image_bytes = f.stream.read()
                ai_text = teshis_et(image_bytes, mime=mime, user_note=caption)
            except Exception as e:
                app.logger.exception(f'AI teşhis hatası: {e}')

        foto = Photo(
            parent_type=parent_type, parent_id=parent_id,
            s3_key=key, mime=mime, caption=caption, ai_teshis=ai_text,
        )
        db.session.add(foto)
        sayac += 1

    db.session.commit()
    if sayac:
        flash(f'{sayac} dosya yüklendi.' + (' AI teşhis yapıldı.' if ai_teshis_iste else ''), 'success')
    return redirect(request.referrer or url_for('index'))


@app.route('/foto/<int:foto_id>')
@login_required
def foto_indir(foto_id):
    foto = Photo.query.get_or_404(foto_id)
    url = presigned_get(foto.s3_key, seconds=3600)
    if not url:
        flash('Foto bulunamadı.', 'danger')
        return redirect(url_for('index'))
    return redirect(url)


@app.route('/foto/sil/<int:foto_id>', methods=['POST'])
@login_required
def foto_sil(foto_id):
    foto = Photo.query.get_or_404(foto_id)
    delete_photo(foto.s3_key)
    db.session.delete(foto)
    db.session.commit()
    flash('Fotoğraf silindi.', 'success')
    return redirect(request.referrer or url_for('index'))


@app.route('/foto/teshis/<int:foto_id>', methods=['POST'])
@login_required
def foto_teshis(foto_id):
    foto = Photo.query.get_or_404(foto_id)
    image_bytes = get_bytes(foto.s3_key)
    if not image_bytes:
        flash('Foto indirilemedi.', 'danger')
        return redirect(request.referrer or url_for('index'))
    ai_text = teshis_et(image_bytes, mime=foto.mime or 'image/jpeg', user_note=foto.caption or '')
    if ai_text:
        foto.ai_teshis = ai_text
        db.session.commit()
        flash('AI teşhis yapıldı.', 'success')
    else:
        flash('AI teşhis alınamadı (API key / model kontrol et).', 'warning')
    return redirect(request.referrer or url_for('index'))


def get_photos(parent_type, parent_id):
    """Template helper: ilgili kayda ait foto listesi (presigned URL ile)."""
    fotos = Photo.query.filter_by(parent_type=parent_type, parent_id=parent_id)\
        .order_by(Photo.tarih.desc()).all()
    out = []
    for f in fotos:
        out.append({
            'id': f.id,
            'url': presigned_get(f.s3_key, 3600),
            'mime': f.mime,
            'caption': f.caption,
            'ai_teshis': f.ai_teshis,
            'tarih': f.tarih,
            'is_image': (f.mime or '').startswith('image/'),
        })
    return out


app.jinja_env.globals['get_photos'] = get_photos


# ----- KARISIM KONTROLÜ -----
@app.route("/karisim-kontrol", methods=["GET", "POST"])
@login_required
def karisim_kontrol():
    """
    İlaç karışımlarının birbirleriyle uyumluluğunu yapay zeka kullanarak kontrol eder.
    Kullanıcının girdiği ilaçları yapay zeka API'lerine gönderir ve karıştırılabilirlik analizi alır.
    """
    if request.method == "POST":
        secilen_ilaclar = []
        for i in range(1, 6):
            ilac = request.form.get(f"ilac{i}")
            if ilac and ilac.strip():
                secilen_ilaclar.append(ilac.strip())

        if len(secilen_ilaclar) < 2:
            flash("Lütfen en az iki ilaç giriniz.", "warning")
            return render_template("karisim.html", sonuc=None, ilac_listesi=get_ilac_listesi())

        kombinasyon = " + ".join(secilen_ilaclar)
        
        prompt = f"""
        Aşağıda verilen tarım ilaçlarının birbiriyle karıştırılabilirliğini değerlendir:
        {kombinasyon}
        
        - Bu karışımın çökelme, kimyasal reaksiyon, pH uyumsuzluğu riski var mı?
        - İçlerinden birbiriyle karıştırılmaması gereken ilaçlar var mı?
        - Uyumsuzluk varsa hangi ikiliden kaynaklanıyor?
        - Kullanım tavsiyesi, karıştırma sırası, sıcaklık/pH önerisi varsa belirt.
        - Lütfen Türkçe, teknik ama sade bir dille açıkla.
        """

        # 1. Claude ile dene
        try:
            client = get_anthropic_client()
            if client:
                response = client.messages.create(
                    model=CLAUDE_MODEL,  # the newest Anthropic model is "claude-3-5-sonnet-20241022" which was released October 22, 2024
                    max_tokens=1000,
                    temperature=0.5,
                    system="Sen bir tarım ilaçları uzmanısın. Tarım ilaçlarının karıştırılabilirliği, kimyasal uyumluluğu, çökelme riskleri ve tank karışımları konusunda uzmansın.",
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                sonuc = response.content[0].text
                return render_template("karisim.html", sonuc=sonuc, ilac_listesi=get_ilac_listesi(), kaynak="Claude AI")
            else:
                raise Exception("Claude API kullanılamıyor")
        except Exception as claude_hatasi:
            print(f"Claude hatası: {str(claude_hatasi)}")
            
            # 2. GPT-4o ile dene
            try:
                client = get_openai_client()
                if client:
                    response = client.chat.completions.create(
                        model=OPENAI_MODEL,  # the newest OpenAI model is "gpt-4o" which was released May 13, 2024
                        temperature=0.5,
                        messages=[
                            {"role": "system", "content": "Sen bir tarım ilaçları uzmanısın. Tarım ilaçlarının karıştırılabilirliği, kimyasal uyumluluğu, çökelme riskleri ve tank karışımları konusunda uzmansın."},
                            {"role": "user", "content": prompt}
                        ]
                    )
                    sonuc = response.choices[0].message.content
                    return render_template("karisim.html", sonuc=sonuc, ilac_listesi=get_ilac_listesi(), kaynak="GPT-4o")
                else:
                    raise Exception("OpenAI API kullanılamıyor")
            except Exception as openai_hatasi:
                print(f"OpenAI hatası: {str(openai_hatasi)}")
                
                # 3. Perplexity araması için yönlendir
                perplexity_url = get_perplexity_url(f"Tarım ilaçları karışımı analizi: {kombinasyon}")
                flash("Yapay zeka servisleri kullanılamıyor, Perplexity aramasına yönlendiriliyorsunuz.", "info")
                return redirect(perplexity_url)

    # GET isteği için tüm ilaçların listesini gönder
    return render_template("karisim.html", sonuc=None, ilac_listesi=get_ilac_listesi())

def get_ilac_listesi():
    """
    Tüm ilaçların listesini veritabanından çeker.
    Karışım kontrolünde otomatik tamamlama için kullanılır.
    """
    ilaclar = Ilac.query.order_by(Ilac.ad).all()
    ilac_listesi = [ilac.ad for ilac in ilaclar]
    
    # Veritabanındaki listeyi tamamlamak için dışarıdan ilaç listesi de ekleyelim
    try:
        with open('data/ilaclar_autocomplete.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            for item in data:
                # İtem bir dictionary ise ilac_adi anahtarı kullan
                if isinstance(item, dict) and 'ilac_adi' in item and item['ilac_adi'] and item['ilac_adi'] not in ilac_listesi:
                    ilac_listesi.append(item['ilac_adi'])
                # İtem bir string ise doğrudan kullan
                elif isinstance(item, str) and item not in ilac_listesi:
                    ilac_listesi.append(item)
    except Exception as e:
        print(f"İlaç listesi okuma hatası: {str(e)}")
        # Dosya yoksa veya okuma hatası olursa varsayılan liste ekleyelim
        varsayilan_ilaclar = [
            "Champion", "Karaçor", "Teldor", "Antracol", "Switch", "Melody Duo",
            "Falcon", "Ridomil Gold", "Score", "Equation Pro", "Trimiltox", "Quadris",
            "Revus", "Topas", "Acrobat", "Vivando", "Pergado", "Signum", "Cabrio"
        ]
        for ilac in varsayilan_ilaclar:
            if ilac not in ilac_listesi:
                ilac_listesi.append(ilac)
    
    # Alfabetik sırala ve boşlukları kaldır
    return sorted([i.strip() for i in ilac_listesi if i.strip()])

# ----- YEDEKLEME -----
# ----- BAĞ YÖNETİMİ -----
@app.route('/baglar', methods=['GET', 'POST'])
@login_required
def baglar():
    if request.method == 'POST':
        # Yeni bağ ekleme
        ad = request.form['ad']
        alan = float(request.form['alan'])
        aciklama = request.form.get('aciklama', '')
        ekim_tipi = request.form.get('ekim_tipi', '')
        gps_koordinat = request.form.get('gps_koordinat', '')
        aktif = 'aktif' in request.form  # Checkbox kontrolü
        
        yeni_bag = Bag(
            ad=ad,
            alan=alan,
            aciklama=aciklama,
            ekim_tipi=ekim_tipi,
            gps_koordinat=gps_koordinat,
            aktif=aktif
        )
        
        db.session.add(yeni_bag)
        db.session.commit()
        
        # JSON dosyasına da kaydet
        Bag.json_dosyasina_kaydet()
        
        flash(f'{ad} bağı başarıyla eklendi.', 'success')
        return redirect(url_for('baglar'))
    
    # Tüm bağları getir (sadece aktif olanlar seçeneği ekle)
    sadece_aktif = request.args.get('sadece_aktif', 'true')
    
    if sadece_aktif == 'true':
        baglar = Bag.query.filter_by(aktif=True).all()
    else:
        baglar = Bag.query.all()
    
    return render_template('bag.html', baglar=baglar, sadece_aktif=sadece_aktif)

@app.route('/bag/duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def bag_duzenle(id):
    bag = Bag.query.get_or_404(id)
    
    if request.method == 'POST':
        bag.ad = request.form['ad']
        bag.alan = float(request.form['alan'])
        bag.aciklama = request.form.get('aciklama', '')
        bag.ekim_tipi = request.form.get('ekim_tipi', '')
        bag.gps_koordinat = request.form.get('gps_koordinat', '')
        bag.aktif = 'aktif' in request.form
        bag.son_guncelleme = datetime.datetime.utcnow()
        
        db.session.commit()
        
        # JSON dosyasını güncelle
        Bag.json_dosyasina_kaydet()
        
        flash(f'{bag.ad} bağı güncellendi.', 'success')
        return redirect(url_for('baglar'))
    
    return render_template('bag_duzenle.html', bag=bag)

@app.route('/bag/sil/<int:id>', methods=['POST'])
@login_required
def bag_sil(id):
    bag = Bag.query.get_or_404(id)
    db.session.delete(bag)
    db.session.commit()
    
    # JSON dosyasını güncelle
    Bag.json_dosyasina_kaydet()
    
    flash(f'{bag.ad} bağı silindi.', 'success')
    return redirect(url_for('baglar'))

@app.route('/bag/detay/<int:id>')
@login_required
def bag_detay(id):
    bag = Bag.query.get_or_404(id)
    
    # İlaçlama kayıtlarını al
    ilaclamalar = IlacKullanim.query.filter_by(bag_id=bag.id).order_by(IlacKullanim.tarih.desc()).all()
    
    # Gübreleme kayıtlarını al
    gubrelemeler = GubreKullanim.query.filter_by(bag_id=bag.id).order_by(GubreKullanim.tarih.desc()).all()
    
    # İlaçlama grupları oluştur
    ilac_gruplari = IlacKullanim.grup_kayitlari(ilaclamalar)
    
    # İlaç ve gübre tarihi için Türkiye saat dilimini kullan
    tr_timezone = pytz.timezone('Europe/Istanbul')
    
    # Tarih çevirmek için yardımcı fonksiyon
    def utc_to_tr(utc_dt):
        if not utc_dt:
            return None
        # UTC olarak kabul et
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=pytz.UTC)
        # Türkiye saatine çevir
        return utc_dt.astimezone(tr_timezone)
    
    # İlaçlamaları tarihe göre grupla
    ilac_gruplari_sirali = sorted(ilac_gruplari.values(), key=lambda x: x['tarih'], reverse=True) if ilac_gruplari else []
    
    # Her bir grup için tarihi dönüştür
    for grup in ilac_gruplari_sirali:
        grup['tr_tarih'] = utc_to_tr(grup['tarih'])
        for ilac in grup['ilaclar']:
            ilac.tr_tarih = utc_to_tr(ilac.tarih)
    
    # Gübrelemelerin tarihlerini dönüştür
    for gubre in gubrelemeler:
        gubre.tr_tarih = utc_to_tr(gubre.tarih)
    
    # Kullanılabilir meteoroloji verileri
    weather_data = forecast_for_bag(bag)

    # HÖS (Hasat Öncesi Süre) durumu
    hos = compute_bag_hos(bag.id)

    # Tekrar ilaçlama önerileri (bu bağ için)
    tekrar_onerileri = compute_tekrar_onerileri(bag_id=bag.id)

    return render_template('bag_detay.html',
                        bag=bag,
                        ilac_gruplari=ilac_gruplari_sirali,
                        gubrelemeler=gubrelemeler,
                        weather_data=weather_data,
                        hos=hos,
                        tekrar_onerileri=tekrar_onerileri)

@app.route('/yedekleme')
@login_required
def yedekleme():
    return render_template('yedekleme.html')

@app.route('/yedekle', methods=['POST'])
@login_required
def yedekle():
    veri_turu = request.form.get('veri_turu', 'hepsi')
    format_turu = request.form.get('format', 'json')
    
    data = {}
    
    if veri_turu in ['hepsi', 'ilaclar']:
        ilaclar = Ilac.query.all()
        data['ilaclar'] = [{
            'id': ilac.id,
            'ad': ilac.ad,
            'etken_madde': ilac.etken_madde,
            'hedef_hastalik': ilac.hedef_hastalik,
            'miktar': ilac.miktar,
            'birim': ilac.birim,
            'dozaj': ilac.dozaj,
            'olusturma_tarihi': ilac.olusturma_tarihi.isoformat() if ilac.olusturma_tarihi else None
        } for ilac in ilaclar]
        
        ilac_kullanimlari = IlacKullanim.query.all()
        data['ilac_kullanimlari'] = [{
            'id': kullanim.id,
            'ilac_id': kullanim.ilac_id,
            'ilac_adi': kullanim.ilac.ad,
            'kullanilan_miktar': kullanim.kullanilan_miktar,
            'su_miktari': kullanim.su_miktari,
            'tarih': kullanim.tarih.isoformat() if kullanim.tarih else None
        } for kullanim in ilac_kullanimlari]
    
    if veri_turu in ['hepsi', 'gubreler']:
        gubreler = Gubre.query.all()
        data['gubreler'] = [{
            'id': gubre.id,
            'ad': gubre.ad,
            'formulasyon': gubre.formulasyon,
            'miktar': gubre.miktar,
            'birim': gubre.birim,
            'kullanim_alani': gubre.kullanim_alani,
            'uygulama_dozu': gubre.uygulama_dozu,
            'not_bilgisi': gubre.not_bilgisi,
            'olusturma_tarihi': gubre.olusturma_tarihi.isoformat() if gubre.olusturma_tarihi else None
        } for gubre in gubreler]
        
        gubre_kullanimlari = GubreKullanim.query.all()
        data['gubre_kullanimlari'] = [{
            'id': kullanim.id,
            'gubre_id': kullanim.gubre_id,
            'gubre_adi': kullanim.gubre.ad,
            'kullanilan_miktar': kullanim.kullanilan_miktar,
            'alan': kullanim.alan,
            'tarih': kullanim.tarih.isoformat() if kullanim.tarih else None
        } for kullanim in gubre_kullanimlari]
    
    # JSON formatına çevir
    json_data = json.dumps(data, ensure_ascii=False, indent=4)
    
    if format_turu == 'json':
        # JSON dosyası olarak indir
        buffer = io.BytesIO()
        buffer.write(json_data.encode('utf-8'))
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'tarim_stok_yedek_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.json',
            mimetype='application/json'
        )
    else:
        # TXT dosyası olarak indir
        buffer = io.BytesIO()
        buffer.write(json_data.encode('utf-8'))
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'tarim_stok_yedek_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.txt',
            mimetype='text/plain'
        )

# İlaç veritabanı dosyasını kontrol et
def check_pesticides_file():
    # data klasörünü kontrol et
    if not os.path.exists('data'):
        os.makedirs('data')
    
    # Zirai ilaç veritabanı dosyaları
    zirai_file_paths = ['data/zirailacliste.json', 'data/ilaclar_autocomplete.json']
    
    # Dosyalar yoksa oluştur
    for zirai_file_path in zirai_file_paths:
        if not os.path.exists(zirai_file_path):
            # Bu durumda boş bir liste oluştur, uygulama hata vermez
            with open(zirai_file_path, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=4)

# Zirai ilaç listesi için API endpoint
@app.route('/api/zirai-ilaclar', methods=['GET'])
@login_required
def api_zirai_ilaclar():
    # Tarayıcı önbelleğini tamamen devre dışı bırakmak için ETag ve timestamp oluşturun
    timestamp = int(time.time())
    requested_timestamp = request.args.get('_')
    
    try:
        with open('data/ilaclar_autocomplete.json', 'r', encoding='utf-8') as f:
            zirai_ilaclar = json.load(f)
            response = jsonify(zirai_ilaclar)
            
            # Önbellek sorununu önlemek için güçlü başlıklar
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '-1'
            response.headers['ETag'] = f'W/"{timestamp}"'
            response.headers['Last-Modified'] = datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
            response.headers['X-Timestamp'] = str(timestamp)  # Özel timestamp başlığı
            
            # Debug log için
            print(f"API: zirai-ilaclar, ilaç sayısı: {len(zirai_ilaclar)}, istek timestamp: {requested_timestamp}, yanıt timestamp: {timestamp}")
            
            return response
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"API hata: zirai-ilaclar, hata: {str(e)}")
        response = jsonify([])
        
        # Hata durumunda da önbelleği devre dışı bırak
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
        response.headers['ETag'] = f'W/"{timestamp}"'
        response.headers['Last-Modified'] = datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
        response.headers['X-Timestamp'] = str(timestamp)
        response.headers['X-Error'] = str(e)
        
        return response
        
# Zirai ilaç arama API'si
@app.route('/api/zirai-ilaclar/search', methods=['GET'])
@login_required
def api_zirai_ilaclar_search():
    query = request.args.get('query', '').lower()
    timestamp = int(time.time())
    requested_timestamp = request.args.get('_')
    
    if not query or len(query) < 2:
        response = jsonify([])
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
        response.headers['ETag'] = f'W/"{timestamp}"'
        response.headers['Last-Modified'] = datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
        response.headers['X-Timestamp'] = str(timestamp)
        return response
    
    try:
        with open('data/ilaclar_autocomplete.json', 'r', encoding='utf-8') as f:
            zirai_ilaclar = json.load(f)
            
            # İsimlerde arama yap
            sonuclar = []
            for ilac in zirai_ilaclar:
                ilac_adi = ilac.get('ilac_adi', '')
                if ilac_adi and query in ilac_adi.lower():
                    # Eksik alanları kontrol et
                    if ilac.get('dozaj') is None:
                        ilac['dozaj'] = '0'
                    if ilac.get('etken_madde') is None:
                        ilac['etken_madde'] = ''
                    if ilac.get('hastalik') is None:
                        ilac['hastalik'] = ''
                    sonuclar.append(ilac)
            
            # En fazla 10 sonuç göster
            response = jsonify(sonuclar[:10])
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '-1'
            response.headers['ETag'] = f'W/"{timestamp}"'
            response.headers['Last-Modified'] = datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
            response.headers['X-Timestamp'] = str(timestamp)
            
            # Debug log için
            print(f"API: zirai-ilaclar/search, sorgu: {query}, sonuç sayısı: {len(sonuclar[:10])}, istek timestamp: {requested_timestamp}, yanıt timestamp: {timestamp}")
            
            return response
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"API hata: zirai-ilaclar/search, hata: {str(e)}, sorgu: {query}")
        response = jsonify([])
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
        response.headers['ETag'] = f'W/"{timestamp}"'
        response.headers['Last-Modified'] = datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
        response.headers['X-Timestamp'] = str(timestamp)
        response.headers['X-Error'] = str(e)
        return response

# Zirai ilaç ekleme/düzenleme API'si
@app.route('/api/zirai-ilaclar/kaydet', methods=['POST'])
@login_required
def api_zirai_ilac_kaydet():
    data = request.get_json()
    timestamp = int(time.time())
    
    if not data or not data.get('ilac_adi'):
        return jsonify({'success': False, 'error': 'Geçersiz ilaç verisi'}), 400
    
    try:
        # Mevcut ilac listesini oku
        zirai_ilaclar = []
        try:
            with open('data/ilaclar_autocomplete.json', 'r', encoding='utf-8') as f:
                zirai_ilaclar = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # Dosya bulunamadıysa yeni bir liste oluştur
            zirai_ilaclar = []
        
        # Mevcut ilaç var mı kontrol et
        ilac_mevcut = False
        for i, ilac in enumerate(zirai_ilaclar):
            if ilac.get('ilac_adi') == data.get('ilac_adi'):
                # Mevcut ilacı güncelle
                zirai_ilaclar[i] = data
                ilac_mevcut = True
                break
        
        # Mevcut değilse listeye ekle
        if not ilac_mevcut:
            zirai_ilaclar.append(data)
        
        # Dosyaya geri yaz
        with open('data/ilaclar_autocomplete.json', 'w', encoding='utf-8') as f:
            json.dump(zirai_ilaclar, f, ensure_ascii=False, indent=4)
        
        # Zirailacliste.json dosyasını da güncelle (eğer kullanılıyorsa)
        try:
            zirai_tam_liste = []
            try:
                with open('data/zirailacliste.json', 'r', encoding='utf-8') as f:
                    zirai_tam_liste = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                zirai_tam_liste = []
            
            # Tam listede ilacı ara ve güncelle/ekle
            ilac_tam_listede = False
            for i, ilac in enumerate(zirai_tam_liste):
                if ilac.get('ilac_adi') == data.get('ilac_adi'):
                    zirai_tam_liste[i] = data
                    ilac_tam_listede = True
                    break
            
            if not ilac_tam_listede:
                zirai_tam_liste.append(data)
            
            with open('data/zirailacliste.json', 'w', encoding='utf-8') as f:
                json.dump(zirai_tam_liste, f, ensure_ascii=False, indent=4)
        except Exception as e:
            # zirailacliste.json dosyasını güncelleme hatası önemli değil
            print(f"zirailacliste.json güncelleme hatası: {e}")
        
        # Debug log için
        print(f"API: zirai-ilaclar/kaydet, ilaç: {data.get('ilac_adi')}, işlem: {'güncelleme' if ilac_mevcut else 'ekleme'}, timestamp: {timestamp}")
        
        # Önbellek kontrolü yapan başlıklar ekle
        response = jsonify({'success': True, 'timestamp': timestamp})
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
        response.headers['ETag'] = f'W/"{timestamp}"'
        response.headers['Last-Modified'] = datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
        response.headers['X-Timestamp'] = str(timestamp)
        return response
    except Exception as e:
        print(f"API hata: zirai-ilaclar/kaydet, hata: {str(e)}")
        response = jsonify({
            'success': False, 
            'error': str(e), 
            'timestamp': timestamp
        })
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
        response.headers['X-Timestamp'] = str(timestamp)
        response.headers['X-Error'] = str(e)
        return response, 500

# Uygulama başlatıldığında çalıştırılacak işlemler
@app.before_request
def before_request():
    # İlk istek geldiğinde çalışacak kontroller
    if not hasattr(app, '_initial_setup_done'):
        check_pesticides_file()
        app._initial_setup_done = True

# ----- KRITIK STOK API -----
@app.route('/api/kritik-stok')
@login_required
def kritik_stok():
    """Kritik seviyede olan ilaç ve gübreleri döner."""
    kritik_ilaclar = Ilac.query.filter(Ilac.miktar < Ilac.min_stok).all()
    kritik_gubreler = Gubre.query.filter(Gubre.miktar < Gubre.min_stok).all()
    
    return jsonify({
        'kritik_ilaclar': [{
            'id': ilac.id,
            'ad': ilac.ad,
            'miktar': ilac.miktar,
            'birim': ilac.birim,
            'min_stok': ilac.min_stok,
            'durum': 'KRITIK'
        } for ilac in kritik_ilaclar],
        'kritik_gubreler': [{
            'id': gubre.id,
            'ad': gubre.ad,
            'miktar': gubre.miktar,
            'birim': gubre.birim,
            'min_stok': gubre.min_stok,
            'durum': 'KRITIK'
        } for gubre in kritik_gubreler],
        'toplam_kritik': len(kritik_ilaclar) + len(kritik_gubreler)
    })


# ----- BİLDİRİM (WhatsApp) -----
CRON_SECRET = os.environ.get('CRON_SECRET', '')


@app.route('/bildirim-test', methods=['POST'])
@login_required
def bildirim_test():
    """Kullanıcı dashboard'dan WhatsApp test mesajı atsın."""
    ok, durum = send_whatsapp(
        '✅ Tarım Uygulaması test mesajıdır.\nBildirimler çalışıyor.',
        dedup_key=None,
    )
    if ok:
        flash('WhatsApp test mesajı gönderildi.', 'success')
    else:
        flash(f'WhatsApp gönderilemedi ({durum}). .env WHATSAPP_TO/KEY ve instance bağlantısını kontrol edin.', 'warning')
    return redirect(request.referrer or url_for('index'))


@app.route('/cron/bildirim', methods=['GET', 'POST'])
def cron_bildirim():
    """Dışarıdan (systemd timer / cron) tetiklenir. Günlük HÖS + kritik stok WhatsApp tarar."""
    secret = request.args.get('secret') or request.headers.get('X-Cron-Secret', '')
    if not CRON_SECRET or secret != CRON_SECRET:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    kritik_ilaclar = Ilac.query.filter(Ilac.miktar < Ilac.min_stok).all()
    kritik_gubreler = Gubre.query.filter(Gubre.miktar < Gubre.min_stok).all()
    kritik_ok = kritik_stok_whatsapp_gonder(kritik_ilaclar, kritik_gubreler)

    hos_listesi = compute_all_bag_hos()
    hos_yaklasan = [h for h in hos_listesi if h['aktif'] and h['kalan_gun'] is not None and h['kalan_gun'] <= 7]
    hos_ok = hos_whatsapp_gonder(hos_yaklasan) if hos_yaklasan else False

    return jsonify({
        'ok': True,
        'kritik_stok_gonderildi': kritik_ok,
        'hos_gonderildi': hos_ok,
        'kritik_sayi': len(kritik_ilaclar) + len(kritik_gubreler),
        'hos_yaklasan_sayi': len(hos_yaklasan),
    })
