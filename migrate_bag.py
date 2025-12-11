from app import app, db
from models import Bag

# Veritabanı tablosunu güncelle
with app.app_context():
    print("Bağ tablosu güncelleniyor...")
    
    # Varolan tabloyu kontrol et
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    columns = [column['name'] for column in inspector.get_columns('bag')]
    
    # Yeni kolonları ekle (varsa)
    with db.engine.begin() as conn:
        if 'aciklama' not in columns:
            print("'aciklama' kolonu ekleniyor...")
            conn.execute(db.text("ALTER TABLE bag ADD COLUMN aciklama TEXT"))
        
        if 'ekim_tipi' not in columns:
            print("'ekim_tipi' kolonu ekleniyor...")
            conn.execute(db.text("ALTER TABLE bag ADD COLUMN ekim_tipi VARCHAR(100)"))
            
        if 'gps_koordinat' not in columns:
            print("'gps_koordinat' kolonu ekleniyor...")
            conn.execute(db.text("ALTER TABLE bag ADD COLUMN gps_koordinat VARCHAR(100)"))
            
        if 'aktif' not in columns:
            print("'aktif' kolonu ekleniyor...")
            conn.execute(db.text("ALTER TABLE bag ADD COLUMN aktif BOOLEAN DEFAULT TRUE"))
            
        if 'son_guncelleme' not in columns:
            print("'son_guncelleme' kolonu ekleniyor...")
            conn.execute(db.text("ALTER TABLE bag ADD COLUMN son_guncelleme TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
            
    print("Bağ tablosu güncelleme işlemi tamamlandı.")
    
    # Tüm bağları aktif olarak işaretle
    try:
        db.session.query(Bag).update({Bag.aktif: True})
        db.session.commit()
        print("Tüm bağlar aktif olarak işaretlendi.")
    except Exception as e:
        db.session.rollback()
        print(f"Hata: {str(e)}")