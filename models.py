import datetime
import json
import os
from app import db

# Bağ modeli
class Bag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(100), nullable=False)
    alan = db.Column(db.Float, nullable=False)  # Dönüm cinsinden alan
    aciklama = db.Column(db.Text, nullable=True)  # Bağ ile ilgili detaylı açıklama
    ekim_tipi = db.Column(db.String(100), nullable=True)  # Üzüm çeşidi, dikim türü vb.
    gps_koordinat = db.Column(db.String(100), nullable=True)  # GPS koordinatları (ör: "38.123456, 27.123456")
    aktif = db.Column(db.Boolean, default=True)  # Bağın aktif/pasif durumu
    fenoloji_durumu = db.Column(db.String(30))  # Mevcut fenolojik dönem kodu (uyuma, tomurcuk, cicek, ben_dusme, olgun, hasat, hasat_sonrasi)
    fenoloji_tarih = db.Column(db.Date)  # Bu döneme girdiği tarih (manuel)
    olusturma_tarihi = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    son_guncelleme = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    def __repr__(self):
        durum = "Aktif" if self.aktif else "Pasif"
        return f"<Bag {self.ad} ({durum})>"
    
    def ilaclama_sayisi(self, yil=None):
        """Belirli bir yıla ait (veya tüm) ilaçlama sayısını döndürür."""
        query = IlacKullanim.query.filter_by(bag_id=self.id)
        
        if yil:
            yil_baslangic = datetime.datetime(year=yil, month=1, day=1)
            yil_bitis = datetime.datetime(year=yil+1, month=1, day=1)
            query = query.filter(IlacKullanim.tarih >= yil_baslangic, IlacKullanim.tarih < yil_bitis)
            
        return query.count()
    
    def gubre_uygulama_sayisi(self, yil=None):
        """Belirli bir yıla ait (veya tüm) gübreleme sayısını döndürür."""
        query = GubreKullanim.query.filter_by(bag_id=self.id)
        
        if yil:
            yil_baslangic = datetime.datetime(year=yil, month=1, day=1)
            yil_bitis = datetime.datetime(year=yil+1, month=1, day=1)
            query = query.filter(GubreKullanim.tarih >= yil_baslangic, GubreKullanim.tarih < yil_bitis)
            
        return query.count()
    
    def toplam_su_kullanimi(self, yil=None):
        """Belirli bir yıla ait (veya tüm) ilaçlamada kullanılan toplam su miktarını döndürür."""
        sonuc = db.session.query(db.func.sum(IlacKullanim.su_miktari)).filter(IlacKullanim.bag_id == self.id)
        
        if yil:
            yil_baslangic = datetime.datetime(year=yil, month=1, day=1)
            yil_bitis = datetime.datetime(year=yil+1, month=1, day=1)
            sonuc = sonuc.filter(IlacKullanim.tarih >= yil_baslangic, IlacKullanim.tarih < yil_bitis)
            
        toplam = sonuc.scalar()
        return toplam if toplam else 0
        
    def taral_sayisi(self, yil=None):
        """Belirli bir yıla ait (veya tüm) taral sayısını döndürür. (400lt/dönüm baz alınarak)"""
        su_miktari = self.toplam_su_kullanimi(yil)
        return round(su_miktari / (400 * self.alan), 1) if self.alan > 0 else 0
    
    def son_ilaclama(self):
        """En son yapılan ilaçlamayı döndürür."""
        return IlacKullanim.query.filter_by(bag_id=self.id).order_by(IlacKullanim.tarih.desc()).first()
    
    def son_gubre_uygulamasi(self):
        """En son yapılan gübrelemeyi döndürür."""
        return GubreKullanim.query.filter_by(bag_id=self.id).order_by(GubreKullanim.tarih.desc()).first()
        
    @staticmethod
    def json_dosyasina_kaydet():
        """Tüm bağ verilerini JSON dosyasına kaydeder."""
        try:
            baglar = Bag.query.all()
            bag_listesi = []
            
            for bag in baglar:
                bag_listesi.append({
                    'id': bag.id,
                    'ad': bag.ad,
                    'alan': bag.alan,
                    'aciklama': bag.aciklama,
                    'ekim_tipi': bag.ekim_tipi,
                    'gps_koordinat': bag.gps_koordinat,
                    'aktif': bag.aktif,
                    'olusturma_tarihi': bag.olusturma_tarihi.strftime('%Y-%m-%d %H:%M:%S'),
                    'son_guncelleme': bag.son_guncelleme.strftime('%Y-%m-%d %H:%M:%S') if bag.son_guncelleme else None
                })
            
            os.makedirs('data', exist_ok=True)
            with open('data/baglar.json', 'w', encoding='utf-8') as f:
                json.dump(bag_listesi, f, ensure_ascii=False, indent=4)
            
            return True
        except Exception as e:
            print(f"Bağları JSON'a kaydetme hatası: {str(e)}")
            return False
    
    @staticmethod
    def json_dosyasindan_yukle():
        """JSON dosyasından bağ verilerini yükler."""
        try:
            if not os.path.exists('data/baglar.json'):
                return []
                
            with open('data/baglar.json', 'r', encoding='utf-8') as f:
                bag_listesi = json.load(f)
            
            return bag_listesi
        except Exception as e:
            print(f"Bağları JSON'dan yükleme hatası: {str(e)}")
            return []

# İlaç modeli
class Ilac(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(100), nullable=False)
    etken_madde = db.Column(db.String(100))
    hedef_hastalik = db.Column(db.String(100))
    miktar = db.Column(db.Float, nullable=False)  # Toplam stok miktarı
    birim = db.Column(db.String(20), nullable=False)  # Stok birimi (ml, lt, gr, kg)
    dozaj = db.Column(db.String(200))  # Doz açıklaması (ör: 20 ml/100 L su)
    grup = db.Column(db.String(50))  # İlaç grubu (Fungisit, İnsektisit, vb.)
    hasat_suresi = db.Column(db.String(50))  # Son ilaçlama ile hasat arası süre (metin)
    hasat_suresi_gun = db.Column(db.Integer)  # HÖS gün sayısı (hesap için)
    uyari = db.Column(db.Text)  # Uyarı bilgisi
    adet = db.Column(db.Integer)  # Şişe/paket sayısı
    min_stok = db.Column(db.Float, default=100)  # Kritik stok seviyesi (ml/mg)
    ambalaj_miktari = db.Column(db.Float)  # Bir ambalajdaki miktar
    ambalaj_birimi = db.Column(db.String(20))  # Ambalaj birimi (ml, lt, gr, kg)
    birim_fiyat = db.Column(db.Float)  # TL / birim (maliyet hesabı için)
    alim_tarihi = db.Column(db.Date)  # Son alım tarihi
    son_kullanma_tarihi = db.Column(db.Date)  # SKT
    lot_no = db.Column(db.String(60))  # Parti / lot numarası
    acilma_tarihi = db.Column(db.Date)  # Ambalaj açılma tarihi
    tekrar_araligi_gun = db.Column(db.Integer)  # Tekrar ilaçlama aralığı (gün) — ör. mildiyö için 7-10
    olusturma_tarihi = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Ilac {self.ad}>"
    
    def kritik_seviyede_mi(self):
        """Stok kritik seviyenin altında mı?"""
        return self.miktar < self.min_stok if self.min_stok else False

# Gübre modeli
class Gubre(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(100), nullable=False)
    formulasyon = db.Column(db.String(50))  # N-P-K oranları (ör: 18-18-18)
    miktar = db.Column(db.Float, nullable=False)
    birim = db.Column(db.String(20), nullable=False)
    min_stok = db.Column(db.Float, default=10)  # Kritik stok seviyesi (kg)
    kullanim_alani = db.Column(db.String(100))
    uygulama_dozu = db.Column(db.Float)  # Damlama dozu: lt/da
    yaprak_dozu = db.Column(db.Float)  # Yaprak dozu: ml/100lt su
    kategori = db.Column(db.String(50))
    not_bilgisi = db.Column(db.Text)
    birim_fiyat = db.Column(db.Float)  # TL / birim (maliyet hesabı için)
    alim_tarihi = db.Column(db.Date)  # Son alım tarihi
    son_kullanma_tarihi = db.Column(db.Date)  # SKT
    lot_no = db.Column(db.String(60))  # Parti / lot numarası
    acilma_tarihi = db.Column(db.Date)  # Ambalaj açılma tarihi
    olusturma_tarihi = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Gubre {self.ad}>"
    
    def kritik_seviyede_mi(self):
        """Stok kritik seviyenin altında mı?"""
        return self.miktar < self.min_stok if self.min_stok else False

# İlaç Kullanım Kaydı
class IlacKullanim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ilac_id = db.Column(db.Integer, db.ForeignKey('ilac.id'), nullable=False)
    bag_id = db.Column(db.Integer, db.ForeignKey('bag.id'), nullable=True)  # Hangi bağda kullanıldı
    kullanilan_miktar = db.Column(db.Float, nullable=False)  # Kullanılan ilaç miktarı
    su_miktari = db.Column(db.Float, nullable=False)  # Kullanılan su miktarı (litre)
    tarih = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    tank_id = db.Column(db.String(50), nullable=True)  # Hangi tank şarjından kullanıldı (gruplamak için)
    
    # İlişki tanımları
    ilac = db.relationship('Ilac', backref=db.backref('kullanimlar', lazy=True))
    bag = db.relationship('Bag', backref=db.backref('ilac_kullanimlari', lazy=True))
    
    def __repr__(self):
        bag_bilgisi = f" ({self.bag.ad})" if self.bag else ""
        return f"<IlacKullanim {self.ilac.ad}{bag_bilgisi} - {self.tarih}>"
        
    @staticmethod
    def grup_kayitlari(kayitlar):
        """
        Aynı tank, bağ ve zaman diliminde kullanılan ilaçları gruplar.
        Yeni kayıt formatını destekler (çoklu bağ ve çoklu ilaç kayıtları).
        
        Parametre:
            kayitlar: İlaç kullanım kayıtları listesi
            
        Dönüş Değeri:
            Gruplandırılmış kayıtlar dictionary'si
            {
                "grup_id": {
                    "tarih": datetime,
                    "bag_id": int,
                    "bag_adi": str,
                    "su_miktari": float,
                    "tank_id": str,
                    "ilaclar": [IlacKullanim, ...]
                },
                ...
            }
        """
        gruplanmis = {}
        
        for kayit in kayitlar:
            # Gruplandırma için benzersiz kimlik oluştur
            # Öncelikle tank_id'yi kontrol et
            tarih_str = kayit.tarih.strftime('%Y-%m-%d %H:%M') if kayit.tarih else "bilinmeyen_tarih"
            bag_id = kayit.bag_id if kayit.bag_id else 0
            
            # Yeni kayıt formatı için tank_id kullanımını öncelikle kontrol et
            tank = kayit.tank_id if kayit.tank_id else f"tank_{tarih_str}_{bag_id}"
            
            # Benzersiz grup tanımlayıcısı oluştur
            # Aynı tank ID, aynı bağ ve aynı saat/dakika için aynı grup
            grup_id = f"{tank}_{bag_id}_{tarih_str}"
            
            # Yeni kayıt formatı için verileri hazırla
            if grup_id not in gruplanmis:
                gruplanmis[grup_id] = {
                    "tarih": kayit.tarih,
                    "bag_id": kayit.bag_id,
                    "bag_adi": kayit.bag.ad if kayit.bag and hasattr(kayit.bag, 'ad') else None,
                    "su_miktari": kayit.su_miktari,
                    "tank_id": tank,
                    "ilaclar": []
                }
            
            # Kaydı grup içindeki ilaçlar listesine ekle
            gruplanmis[grup_id]["ilaclar"].append(kayit)
        
        return gruplanmis

# Stok hareket logu — her giriş/çıkış/düzeltme bu tabloya düşer
class StokHareket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    urun_type = db.Column(db.String(10), nullable=False)  # 'ilac' | 'gubre'
    urun_id = db.Column(db.Integer, nullable=False)
    tip = db.Column(db.String(15), nullable=False)  # 'GIRIS' | 'CIKIS' | 'DUZELTME'
    miktar = db.Column(db.Float, nullable=False)  # + giriş, - çıkış (her iki yönde de mutlak değer yazılır)
    birim = db.Column(db.String(20))
    birim_fiyat = db.Column(db.Float)  # o anki birim fiyat (snapshot)
    not_bilgisi = db.Column(db.Text)
    referans = db.Column(db.String(60))  # ör: "IlacKullanim#123" veya "yeni_ekleme"
    tarih = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<StokHareket {self.urun_type}:{self.urun_id} {self.tip} {self.miktar}>"


# Fotoğraf / dosya eki — herhangi bir kayıt altına bağlanır (bag, ilac_kullanim, gubre_kullanim)
class Photo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    parent_type = db.Column(db.String(30), nullable=False)  # 'bag' | 'ilac_kullanim' | 'gubre_kullanim'
    parent_id = db.Column(db.Integer, nullable=False)
    s3_key = db.Column(db.String(300), nullable=False)  # MinIO objesi (bucket içi yol)
    mime = db.Column(db.String(100))
    caption = db.Column(db.Text)
    ai_teshis = db.Column(db.Text)  # Claude Vision teşhis cevabı
    tarih = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Photo {self.parent_type}:{self.parent_id} {self.s3_key}>"


# Kullanıcı / rol
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    ad_soyad = db.Column(db.String(120))
    rol = db.Column(db.String(20), default='isci', nullable=False)  # 'admin' | 'usta' | 'isci'
    aktif = db.Column(db.Boolean, default=True)
    son_giris = db.Column(db.DateTime)
    olusturma_tarihi = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<User {self.username} ({self.rol})>"


# Audit log — kim ne yaptı
class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    username = db.Column(db.String(80))  # snapshot (user silinse bile iz kalsın)
    action = db.Column(db.String(60), nullable=False)  # 'ilac_ekle', 'bag_sil' vb.
    resource = db.Column(db.String(120))  # ilgili kayıt bilgisi
    details = db.Column(db.Text)
    ip = db.Column(db.String(45))
    tarih = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<AuditLog {self.username} {self.action} {self.tarih}>"


# Hasat kaydı — parsel başına toplanan ürün + varsa satış
class Hasat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bag_id = db.Column(db.Integer, db.ForeignKey('bag.id'), nullable=False)
    tarih = db.Column(db.Date, nullable=False, default=datetime.date.today)
    urun = db.Column(db.String(100))  # ör: "Sultaniye", "Kokulu"
    miktar_kg = db.Column(db.Float, nullable=False)  # kg cinsinden
    birim_fiyat = db.Column(db.Float)  # TL/kg (satıldıysa)
    alici = db.Column(db.String(120))
    satis_tarihi = db.Column(db.Date)
    not_bilgisi = db.Column(db.Text)
    olusturma_tarihi = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    bag = db.relationship('Bag', backref=db.backref('hasatlar', lazy=True))

    @property
    def toplam_tutar(self):
        if self.birim_fiyat and self.miktar_kg:
            return round(self.birim_fiyat * self.miktar_kg, 2)
        return None

    def __repr__(self):
        return f"<Hasat {self.bag.ad if self.bag else '?'} {self.miktar_kg}kg>"


# İşçilik kaydı — yevmiyeli işçi + yaptığı iş
class IscilikKayit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bag_id = db.Column(db.Integer, db.ForeignKey('bag.id'), nullable=True)  # bağımsız (toplu) iş varsa null
    tarih = db.Column(db.Date, nullable=False, default=datetime.date.today)
    isci_adi = db.Column(db.String(120), nullable=False)
    is_turu = db.Column(db.String(100))  # ör: budama, ilaçlama, hasat, çapa
    saat = db.Column(db.Float)  # çalışma saati (opsiyonel)
    yevmiye = db.Column(db.Float, nullable=False)  # TL
    odendi = db.Column(db.Boolean, default=False)
    not_bilgisi = db.Column(db.Text)
    olusturma_tarihi = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    bag = db.relationship('Bag', backref=db.backref('iscilikler', lazy=True))

    def __repr__(self):
        return f"<IscilikKayit {self.isci_adi} {self.tarih} {self.yevmiye}₺>"


# Gübre Kullanım Kaydı
class GubreKullanim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    gubre_id = db.Column(db.Integer, db.ForeignKey('gubre.id'), nullable=False)
    bag_id = db.Column(db.Integer, db.ForeignKey('bag.id'), nullable=True)  # Hangi bağda kullanıldı
    kullanilan_miktar = db.Column(db.Float, nullable=False)
    alan = db.Column(db.Float)  # Uygulanan alan (m²)
    tarih = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # İlişki tanımları
    gubre = db.relationship('Gubre', backref=db.backref('kullanimlar', lazy=True))
    bag = db.relationship('Bag', backref=db.backref('gubre_kullanimlari', lazy=True))
    
    def __repr__(self):
        bag_bilgisi = f" ({self.bag.ad})" if self.bag else ""
        return f"<GubreKullanim {self.gubre.ad}{bag_bilgisi} - {self.tarih}>"
