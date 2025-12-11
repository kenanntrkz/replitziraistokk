#!/bin/bash

# Mevcut API sunucusunu durdur
pkill -f "node api_server.js" 2>/dev/null || true
sleep 1

# API sunucusunu arka planda başlat
echo "API sunucusu başlatılıyor (port 3000)"
node api_server.js &
API_PID=$!

# API sunucusunun başlaması için bekle
sleep 3

# API sunucusunun çalıştığını doğrula
echo "API sunucusu durum kontrolü yapılıyor..."
if ps -p $API_PID > /dev/null; then
    echo "API sunucusu PID: $API_PID ile çalışıyor."
else
    echo "API sunucusu başlatılamadı, yeniden deneniyor..."
    node api_server.js &
    API_PID=$!
    sleep 3
fi

# Flask uygulamasını başlat
echo "Flask uygulaması başlatılıyor (port 5000)"
gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app

# Not: Flask uygulaması kapandıktan sonra API sunucusunu da kapat
kill $API_PID 2>/dev/null || true