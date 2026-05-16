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
        """Belirli bir yıla ait (veya tüm) ilaçlamada kullanılan toplam su miktarını döndürür.
        Aynı tank/uygulamadaki farklı ilaç satırları tek uygulama sayılır (su 1× toplanır)."""
        q = IlacKullanim.query.filter(IlacKullanim.bag_id == self.id)
        if yil:
            yil_baslangic = datetime.datetime(year=yil, month=1, day=1)
            yil_bitis = datetime.datetime(year=yil+1, month=1, day=1)
            q = q.filter(IlacKullanim.tarih >= yil_baslangic, IlacKullanim.tarih < yil_bitis)
        gruplar = {}
        for k in q.all():
            if k.tank_id:
                key = ('t', k.tank_id)
            else:
                dk = k.tarih.strftime('%Y%m%d%H%M') if k.tarih else 'x'
                key = ('d', k.bag_id, dk)
            gruplar[key] = k.su_miktari or 0
        return sum(gruplar.values())
        
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
    etken_madde = db.Column(db.Text)
    hedef_hastalik = db.Column(db.Text)
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
    tekrar_araligi_gun = db.Column(db.Integer)  # Tekrar ilaçlama aralığı (gün) — ör. mildiyö için 7-10
    ruhsatsiz = db.Column(db.Boolean, default=False, nullable=False)  # BKÜ'de bağ ruhsatı yok — sadece stok takibi
    etiket_foto = db.Column(db.String(255))  # /static/etiketler/<id>.jpg — kutu etiket fotosu
    olusturma_tarihi = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Ilac {self.ad}>"

    def kritik_seviyede_mi(self):
        """Stok kritik seviyenin altında mı?"""
        return self.miktar < self.min_stok if self.min_stok else False

    def etken_listesi(self):
        """etken_madde stringini parse eder, [(isim, slug), ...] döndürür.

        Örn: '%66,7 Fosetyl-Al + %4,44 Fluopicolide'
          -> [('Fosetyl-Al', 'fosetyl-al'), ('Fluopicolide', 'fluopicolide')]
        """
        from utils.etken import parse_etken
        return parse_etken(self.etken_madde or '')


# Etken Madde bilgi sayfası — BKÜ + V2 rehber seed
class EtkenMadde(db.Model):
    slug = db.Column(db.String(80), primary_key=True)
    isim = db.Column(db.String(120), nullable=False)
    grup = db.Column(db.String(80))                      # Fungisit, İnsektisit, Herbisit, Akarisit
    frac_irac_kod = db.Column(db.String(50))             # FRAC 7, IRAC 28, HRAC B/2
    hedef_zararli = db.Column(db.Text)                   # külleme, mildiyö
    doz_aciklama = db.Column(db.Text)                    # 100 lt suya doz, dönüm dozu
    phi_gun = db.Column(db.Integer)                      # hasat öncesi süre (gün)
    ari_toksisite = db.Column(db.String(120))            # zararlı / dikkatli / güvenli
    re_entry_saat = db.Column(db.Integer)                # bahçeye girme süresi
    not_bilgisi = db.Column(db.Text)                     # ek uyarı, ipucu
    bku_url = db.Column(db.String(255))                  # BKÜ aktif madde grup linki
    kaynak = db.Column(db.String(40), default='manuel')  # 'manuel' | 'rehber-v2' | 'etiket'
    kaynak_tarih = db.Column(db.Date)
    # V2 rehber alanları
    etki_mekanizmasi = db.Column(db.Text)                # "Hedef nasıl ölüyor" — enzim, ölüm türü
    bitki_hareketi = db.Column(db.String(40))            # sistemik | kontak | translaminer | yarı-sistemik
    koruyucu_tedavi = db.Column(db.String(80))           # Koruyucu | Tedavi | Hem koruyucu hem tedavi
    koruma_suresi = db.Column(db.Text)                   # 10-14 gün, 2 saatte yağmura dayanır
    mahsul_listesi = db.Column(db.Text)                  # Buğday, üzüm, domates (virgül)
    direnc_durumu = db.Column(db.String(40))             # düşük | orta | yüksek | çok yüksek
    ciftci_notu = db.Column(db.Text)                     # Pratik notlar (multi-line)
    yasakli = db.Column(db.Boolean, default=False)
    yasak_tarihleri = db.Column(db.String(200))          # ithalat/imalat/kullanım sonlandırma
    formulasyon_sayisi = db.Column(db.Integer, default=0)
    rehber_metni = db.Column(db.Text)                    # V2 rehber govdesi (tam markdown)
    olusturma_tarihi = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    son_guncelleme = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<EtkenMadde {self.isim}>"

    def iliskili_ilaclar(self):
        """Bu aktif maddeyi içeren envanterdeki ilaçları döndürür."""
        sonuc = []
        for il in Ilac.query.all():
            for _, s in il.etken_listesi():
                if s == self.slug:
                    sonuc.append(il)
                    break
        return sonuc


# Formülasyon — BKÜ veri tabanından alınan ürün kaydı (örn. "100 G/L CLOPYRALID")
class Formulasyon(db.Model):
    __tablename__ = 'formulasyon'
    id = db.Column(db.Integer, primary_key=True)              # BKÜ ID
    ad = db.Column(db.String(300), nullable=False, unique=True, index=True)
    tip = db.Column(db.String(20))                            # Sıvı | Toz/granül
    bku_url = db.Column(db.String(255))                       # BKÜ etiket linki
    durum = db.Column(db.String(20), default='RUHSATLI')      # RUHSATLI | YASAKLI

    etken_maddeler = db.relationship(
        'EtkenMadde',
        secondary='formulasyon_etken_madde',
        backref='formulasyonlar'
    )

    def __repr__(self):
        return f"<Formulasyon {self.ad}>"

    def envanterdeki_ilaclar(self):
        """Bu formülasyonu içeren envanterdeki ilaçları döndürür (ad alanı tam eşleşir)."""
        return Ilac.query.filter(Ilac.etken_madde == self.ad).all()


# Formülasyon ↔ Aktif madde join (M-N, kombo formülasyonlar için)
class FormulasyonEtkenMadde(db.Model):
    __tablename__ = 'formulasyon_etken_madde'
    formulasyon_id = db.Column(db.Integer,
                               db.ForeignKey('formulasyon.id'), primary_key=True)
    etken_madde_slug = db.Column(db.String(80),
                                  db.ForeignKey('etken_madde.slug'), primary_key=True)
    konsantrasyon_payi = db.Column(db.String(40))             # 100 G/L | %66.7

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
    not_bilgisi = db.Column(db.Text)
    referans = db.Column(db.String(60))  # ör: "IlacKullanim#123" veya "yeni_ekleme"
    tarih = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<StokHareket {self.urun_type}:{self.urun_id} {self.tip} {self.miktar}>"


# Tank (1 doluş = 1 tank kaydı)
class Tank(db.Model):
    __tablename__ = 'tank'
    id = db.Column(db.Integer, primary_key=True)
    toplam_su = db.Column(db.Float, nullable=False)              # toplam su (ilk + sonradan eklenen)
    kalan_su = db.Column(db.Float)                                # canlı: tank içinde şu an kalan
    aciklama = db.Column(db.Text)
    olusturma_tarihi = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    tamamlandi = db.Column(db.Boolean, default=False)

    ilaclar = db.relationship('TankIlac', backref='tank',
                              cascade='all, delete-orphan')
    atimlar = db.relationship('TankBagKullanim', backref='tank',
                              cascade='all, delete-orphan',
                              order_by='TankBagKullanim.tarih')
    su_eklemeler = db.relationship('TankSuEkleme', backref='tank',
                                   cascade='all, delete-orphan',
                                   order_by='TankSuEkleme.tarih')

    def __repr__(self):
        return f"<Tank #{self.id} {self.toplam_su}L kalan={self.kalan_su}>"

    def harcanan_su(self):
        return sum(float(a.su_miktari or 0) for a in self.atimlar)

    def eklenen_su(self):
        return sum(float(s.miktar or 0) for s in self.su_eklemeler)

    def hesaplanan_kalan(self):
        if self.kalan_su is not None:
            return float(self.kalan_su)
        return float(self.toplam_su) - self.harcanan_su()


# Tank içindeki ilaç — canlı: tankta o an mevcut ilaç miktarı
class TankIlac(db.Model):
    __tablename__ = 'tank_ilac'
    id = db.Column(db.Integer, primary_key=True)
    tank_id = db.Column(db.Integer, db.ForeignKey('tank.id'), nullable=False)
    ilac_id = db.Column(db.Integer, db.ForeignKey('ilac.id'), nullable=False)
    kullanilan_miktar = db.Column(db.Float, nullable=False)       # canlı: tankta kalan (ml/gr)

    ilac = db.relationship('Ilac')

    def __repr__(self):
        return f"<TankIlac tank={self.tank_id} ilac={self.ilac_id} {self.kullanilan_miktar}>"


# Bir tanktan bir bağa atım — ilac_paylari snapshot olarak saklanır
class TankBagKullanim(db.Model):
    __tablename__ = 'tank_bag_kullanim'
    id = db.Column(db.Integer, primary_key=True)
    tank_id = db.Column(db.Integer, db.ForeignKey('tank.id'), nullable=False)
    bag_id = db.Column(db.Integer, db.ForeignKey('bag.id'), nullable=False)
    su_miktari = db.Column(db.Float, nullable=False)
    ilac_paylari_json = db.Column('ilac_paylari', db.JSON)        # snapshot: [{ilac_id, ilac_ad, miktar, birim}]
    notlar = db.Column(db.Text)
    tarih = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    bag = db.relationship('Bag')

    def __repr__(self):
        return f"<TankBagKullanim tank={self.tank_id} bag={self.bag_id} {self.su_miktari}L>"

    def ilac_paylari(self):
        """Snapshot'ı döndür. Yoksa runtime hesap (legacy)."""
        if self.ilac_paylari_json:
            return self.ilac_paylari_json
        if not self.tank or not float(self.tank.toplam_su or 0):
            return []
        oran = float(self.su_miktari) / float(self.tank.toplam_su)
        return [{
            'ilac_ad': ti.ilac.ad if ti.ilac else '?',
            'miktar': float(ti.kullanilan_miktar) * oran,
            'birim': ti.ilac.birim if ti.ilac else '',
        } for ti in self.tank.ilaclar]


# Tank içine sonradan su+orantılı ilaç ekleme
class TankSuEkleme(db.Model):
    __tablename__ = 'tank_su_ekleme'
    id = db.Column(db.Integer, primary_key=True)
    tank_id = db.Column(db.Integer, db.ForeignKey('tank.id'), nullable=False)
    miktar = db.Column(db.Float, nullable=False)                  # eklenen su (L)
    ilac_paylari_json = db.Column('ilac_paylari', db.JSON)        # eklemeyle giren ilaç snapshot
    notlar = db.Column(db.Text)
    tarih = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<TankSuEkleme tank={self.tank_id} +{self.miktar}L>"


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
