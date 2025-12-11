const express = require('express');
const bodyParser = require('body-parser');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

// Çalışma ve tanılama bilgisi
const startupTime = new Date().toISOString();
let requestCount = 0;

const app = express();
const PORT = 3000;

// Middleware
app.use(cors());
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));

// JSON dosyalarının yolu
const ilaclarJsonPath = path.join(__dirname, 'data/ilaclar_autocomplete.json');
const zirai_ilaclarJsonPath = path.join(__dirname, 'attached_assets/zirailacliste.json');

// Tüm ilaçları getir
app.get('/api/ilaclar', (req, res) => {
    try {
        requestCount++;
        
        // Dosya kontrolü ve data oluşturma
        if (!fs.existsSync(path.dirname(ilaclarJsonPath))) {
            fs.mkdirSync(path.dirname(ilaclarJsonPath), { recursive: true });
            console.log(`'${path.dirname(ilaclarJsonPath)}' klasörü oluşturuldu.`);
        }
        
        if (!fs.existsSync(ilaclarJsonPath)) {
            fs.writeFileSync(ilaclarJsonPath, JSON.stringify([], null, 2), 'utf8');
            console.log(`'${ilaclarJsonPath}' dosyası oluşturuldu.`);
        }
        
        const ilaclarData = fs.readFileSync(ilaclarJsonPath, 'utf8');
        let ilaclar = [];
        
        try {
            ilaclar = JSON.parse(ilaclarData);
        } catch (jsonError) {
            console.error('JSON ayrıştırma hatası, dosya sıfırlanıyor:', jsonError);
            ilaclar = [];
            fs.writeFileSync(ilaclarJsonPath, JSON.stringify([], null, 2), 'utf8');
        }
        
        console.log(`API: ilaclar, ilaç sayısı: ${ilaclar.length}, istek timestamp: ${Date.now()}`);
        res.json(ilaclar);
    } catch (error) {
        console.error('İlaçlar dosyası okuma hatası:', error);
        res.status(500).json({ error: 'İlaçlar verisi okunamadı: ' + error.message });
    }
});

// Zirai ilaç listesini getir (arama için)
app.get('/api/zirai-ilaclar', (req, res) => {
    try {
        if (fs.existsSync(zirai_ilaclarJsonPath)) {
            const ilaclarData = fs.readFileSync(zirai_ilaclarJsonPath, 'utf8');
            const ilaclar = JSON.parse(ilaclarData);
            console.log(`API: zirai-ilaclar, ilaç sayısı: ${ilaclar.length}, istek timestamp: ${Date.now()}, yanıt timestamp: ${Math.floor(Date.now()/1000)}`);
            res.json(ilaclar);
        } else {
            res.status(404).json({ error: 'Zirai ilaçlar dosyası bulunamadı' });
        }
    } catch (error) {
        console.error('Zirai ilaçlar dosyası okuma hatası:', error);
        res.status(500).json({ error: 'Zirai ilaçlar verisi okunamadı' });
    }
});

// Zirai ilaç arama
app.get('/api/zirai-ilaclar/search', (req, res) => {
    try {
        const query = req.query.q?.toLowerCase() || '';
        
        if (!query) {
            return res.json([]);
        }
        
        if (fs.existsSync(zirai_ilaclarJsonPath)) {
            const ilaclarData = fs.readFileSync(zirai_ilaclarJsonPath, 'utf8');
            const ilaclar = JSON.parse(ilaclarData);
            
            const filteredIlaclar = ilaclar.filter(ilac => 
                ilac.PREPARATIN_NAME.toLowerCase().includes(query)
            ).slice(0, 10); // Maksimum 10 sonuç döndür
            
            console.log(`API: zirai-ilaclar/search, sorgu: ${query}, sonuç sayısı: ${filteredIlaclar.length}, istek timestamp: ${Date.now()}, yanıt timestamp: ${Math.floor(Date.now()/1000)}`);
            res.json(filteredIlaclar);
        } else {
            res.status(404).json({ error: 'Zirai ilaçlar dosyası bulunamadı' });
        }
    } catch (error) {
        console.error('Zirai ilaçlar arama hatası:', error);
        res.status(500).json({ error: 'Zirai ilaçlar araması yapılamadı' });
    }
});

// Yeni ilaç ekle veya güncelle
app.post('/api/ilaclar', (req, res) => {
    try {
        const newIlac = req.body;
        
        if (!newIlac || !newIlac.ad) {
            return res.status(400).json({ error: 'Geçersiz ilaç verisi' });
        }
        
        let ilaclar = [];
        
        // Dosya varsa oku
        if (fs.existsSync(ilaclarJsonPath)) {
            const ilaclarData = fs.readFileSync(ilaclarJsonPath, 'utf8');
            ilaclar = JSON.parse(ilaclarData);
        }
        
        // İlaç zaten var mı kontrol et (ad'a göre)
        const ilacIndex = ilaclar.findIndex(ilac => ilac.ad.toLowerCase() === newIlac.ad.toLowerCase());
        
        if (ilacIndex !== -1) {
            // Varsa güncelle
            ilaclar[ilacIndex] = newIlac;
        } else {
            // Yoksa ekle
            ilaclar.push(newIlac);
        }
        
        // JSON dosyasına kaydet
        fs.writeFileSync(ilaclarJsonPath, JSON.stringify(ilaclar, null, 2), 'utf8');
        
        console.log(`İlaç ekleme: '${newIlac.ad}' başarıyla JSON'a eklendi/güncellendi.`);
        res.status(200).json({ 
            success: true, 
            message: `İlaç '${newIlac.ad}' başarıyla ${ilacIndex !== -1 ? 'güncellendi' : 'eklendi'}` 
        });
    } catch (error) {
        console.error('İlaç ekleme/güncelleme hatası:', error);
        res.status(500).json({ error: 'İlaç eklenemedi/güncellenemedi' });
    }
});

// Sağlık kontrolü endpoint'i
app.get('/api/health', (req, res) => {
    requestCount++;
    const uptime = Math.floor((new Date() - new Date(startupTime)) / 1000);
    
    // Dosya kontrolü
    let ilaclarFileExists = false;
    let zirai_ilaclarFileExists = false;
    
    try {
        ilaclarFileExists = fs.existsSync(ilaclarJsonPath);
        zirai_ilaclarFileExists = fs.existsSync(zirai_ilaclarJsonPath);
    } catch (error) {
        console.error('Dosya kontrolü hatası:', error);
    }
    
    res.json({
        status: 'Aktif',
        uptime: `${uptime} saniye`,
        startedAt: startupTime,
        requestCount: requestCount,
        filesCheck: {
            ilaclar: ilaclarFileExists ? 'Mevcut' : 'Eksik',
            zirai_ilaclar: zirai_ilaclarFileExists ? 'Mevcut' : 'Eksik'
        },
        timestamp: new Date().toISOString()
    });
});

// Zirai ilaç kaydet
app.post('/api/zirai-ilac-kaydet', (req, res) => {
    try {
        requestCount++;
        const { ilac } = req.body;
        
        if (!ilac || !ilac.PREPARATIN_NAME) {
            return res.status(400).json({ error: 'Geçersiz ilaç verisi' });
        }
        
        let yeniIlac = {
            ad: ilac.PREPARATIN_NAME,
            etken_madde: ilac.ACTIVE_INGREDIENT || '',
            hedef_hastalik: '',
            dozaj: 0,
            birim: 'ml'
        };
        
        // İlaçlar JSON'a ekle
        let ilaclar = [];
        
        // Dosya varsa oku
        if (fs.existsSync(ilaclarJsonPath)) {
            const ilaclarData = fs.readFileSync(ilaclarJsonPath, 'utf8');
            ilaclar = JSON.parse(ilaclarData);
        }
        
        // İlaç zaten var mı kontrol et (ad'a göre)
        const ilacIndex = ilaclar.findIndex(i => i.ad.toLowerCase() === yeniIlac.ad.toLowerCase());
        
        if (ilacIndex !== -1) {
            // Varsa güncelle
            ilaclar[ilacIndex] = Object.assign({}, ilaclar[ilacIndex], yeniIlac);
        } else {
            // Yoksa ekle
            ilaclar.push(yeniIlac);
        }
        
        // JSON dosyasına kaydet
        fs.writeFileSync(ilaclarJsonPath, JSON.stringify(ilaclar, null, 2), 'utf8');
        
        console.log(`Zirai ilaç ekleme: '${yeniIlac.ad}' başarıyla JSON'a eklendi/güncellendi.`);
        res.status(200).json({ 
            success: true, 
            message: `Zirai ilaç '${yeniIlac.ad}' başarıyla ${ilacIndex !== -1 ? 'güncellendi' : 'eklendi'}`,
            ilac: yeniIlac 
        });
    } catch (error) {
        console.error('Zirai ilaç ekleme/güncelleme hatası:', error);
        res.status(500).json({ error: 'Zirai ilaç eklenemedi/güncellenemedi' });
    }
});

// Sunucuyu başlat
app.listen(PORT, '0.0.0.0', () => {
    console.log(`API Sunucusu http://0.0.0.0:${PORT} adresinde çalışıyor`);
});