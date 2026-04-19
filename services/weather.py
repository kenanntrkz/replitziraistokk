"""Open-Meteo hava durumu servisi — API key gerekmez."""
import re
import time
import logging
import requests

logger = logging.getLogger(__name__)

_CACHE = {}  # {(lat,lon): (expire_ts, data)}
_CACHE_TTL = 1800  # 30 dakika

OM_URL = 'https://api.open-meteo.com/v1/forecast'


def parse_gps(gps_str):
    """'38.123, 27.456' -> (38.123, 27.456); geçersizse None."""
    if not gps_str:
        return None
    parts = re.findall(r'-?\d+\.?\d*', gps_str)
    if len(parts) < 2:
        return None
    try:
        lat = float(parts[0])
        lon = float(parts[1])
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return (lat, lon)
    except ValueError:
        pass
    return None


def fetch_forecast(lat, lon):
    """5 günlük tahmin. Dönüş: {daily: [...], hourly_today: [...]} veya None."""
    key = (round(lat, 3), round(lon, 3))
    now = time.time()
    if key in _CACHE:
        expire, data = _CACHE[key]
        if expire > now:
            return data

    params = {
        'latitude': lat,
        'longitude': lon,
        'daily': ','.join([
            'temperature_2m_max', 'temperature_2m_min',
            'precipitation_sum', 'precipitation_probability_max',
            'wind_speed_10m_max', 'weather_code',
        ]),
        'hourly': ','.join([
            'temperature_2m', 'precipitation_probability',
            'wind_speed_10m', 'weather_code',
        ]),
        'current': 'temperature_2m,precipitation,wind_speed_10m,weather_code,relative_humidity_2m',
        'timezone': 'Europe/Istanbul',
        'forecast_days': 5,
    }
    try:
        r = requests.get(OM_URL, params=params, timeout=8)
        if r.status_code != 200:
            logger.warning(f'Open-Meteo HTTP {r.status_code}')
            return None
        data = r.json()
    except Exception as e:
        logger.exception(f'Open-Meteo exception: {e}')
        return None

    result = _parse_meteo(data)
    _CACHE[key] = (now + _CACHE_TTL, result)
    return result


_WEATHER_CODES = {
    0: ('Açık', 'fa-sun', 'text-warning'),
    1: ('Çoğunlukla açık', 'fa-sun', 'text-warning'),
    2: ('Parçalı bulutlu', 'fa-cloud-sun', 'text-info'),
    3: ('Bulutlu', 'fa-cloud', 'text-secondary'),
    45: ('Sis', 'fa-smog', 'text-muted'),
    48: ('Sis (donlu)', 'fa-smog', 'text-muted'),
    51: ('Hafif çisenti', 'fa-cloud-rain', 'text-primary'),
    53: ('Çisenti', 'fa-cloud-rain', 'text-primary'),
    55: ('Yoğun çisenti', 'fa-cloud-rain', 'text-primary'),
    61: ('Hafif yağmur', 'fa-cloud-showers-heavy', 'text-primary'),
    63: ('Yağmur', 'fa-cloud-showers-heavy', 'text-primary'),
    65: ('Şiddetli yağmur', 'fa-cloud-showers-heavy', 'text-danger'),
    71: ('Hafif kar', 'fa-snowflake', 'text-info'),
    73: ('Kar', 'fa-snowflake', 'text-info'),
    75: ('Yoğun kar', 'fa-snowflake', 'text-info'),
    80: ('Sağanak', 'fa-cloud-bolt', 'text-primary'),
    81: ('Şiddetli sağanak', 'fa-cloud-bolt', 'text-danger'),
    82: ('Fırtınalı sağanak', 'fa-cloud-bolt', 'text-danger'),
    95: ('Gök gürültülü', 'fa-bolt', 'text-danger'),
    96: ('Dolu (hafif)', 'fa-bolt', 'text-danger'),
    99: ('Dolu (yoğun)', 'fa-bolt', 'text-danger'),
}


def _code_info(c):
    return _WEATHER_CODES.get(int(c) if c is not None else -1, ('Bilinmiyor', 'fa-question', 'text-muted'))


def _parse_meteo(data):
    daily = data.get('daily', {})
    current = data.get('current', {})
    gunler = []
    dates = daily.get('time', [])
    for i, d in enumerate(dates):
        code = daily.get('weather_code', [None])[i] if i < len(daily.get('weather_code', [])) else None
        kod_txt, ikon, renk = _code_info(code)
        tmax = daily.get('temperature_2m_max', [None])[i] if i < len(daily.get('temperature_2m_max', [])) else None
        tmin = daily.get('temperature_2m_min', [None])[i] if i < len(daily.get('temperature_2m_min', [])) else None
        yag = daily.get('precipitation_sum', [None])[i] if i < len(daily.get('precipitation_sum', [])) else None
        yag_prob = daily.get('precipitation_probability_max', [None])[i] if i < len(daily.get('precipitation_probability_max', [])) else None
        ruzgar = daily.get('wind_speed_10m_max', [None])[i] if i < len(daily.get('wind_speed_10m_max', [])) else None

        uygunluk = _ilaclama_uygunlugu(tmax, tmin, yag_prob, ruzgar)
        gunler.append({
            'tarih': d,
            'tmax': tmax, 'tmin': tmin,
            'yagis_mm': yag, 'yagis_ihtimal': yag_prob,
            'ruzgar_kmh': ruzgar,
            'kod': code, 'kod_metin': kod_txt, 'ikon': ikon, 'renk': renk,
            'ilaclama': uygunluk,
        })

    anlik = None
    if current:
        code = current.get('weather_code')
        kod_txt, ikon, renk = _code_info(code)
        anlik = {
            'sicaklik': current.get('temperature_2m'),
            'ruzgar_kmh': current.get('wind_speed_10m'),
            'yagis': current.get('precipitation'),
            'nem': current.get('relative_humidity_2m'),
            'kod': code, 'kod_metin': kod_txt, 'ikon': ikon, 'renk': renk,
        }

    return {'anlik': anlik, 'gunler': gunler}


def _ilaclama_uygunlugu(tmax, tmin, yag_prob, ruzgar):
    """İlaçlama uygunluk skoru: YESIL / SARI / KIRMIZI + gerekçe."""
    sebepler = []
    if yag_prob is not None and yag_prob >= 60:
        sebepler.append(f'yağış %{int(yag_prob)}')
    elif yag_prob is not None and yag_prob >= 30:
        sebepler.append(f'yağış %{int(yag_prob)} (orta)')
    if ruzgar is not None and ruzgar >= 20:
        sebepler.append(f'rüzgar {ruzgar:.0f} km/h')
    elif ruzgar is not None and ruzgar >= 15:
        sebepler.append(f'rüzgar {ruzgar:.0f} km/h (sınırda)')
    if tmax is not None and tmax >= 30:
        sebepler.append(f'yüksek sıcaklık {tmax:.0f}°C')
    if tmin is not None and tmin <= 5:
        sebepler.append(f'düşük sıcaklık {tmin:.0f}°C')

    kotu = (yag_prob is not None and yag_prob >= 60) or (ruzgar is not None and ruzgar >= 20)
    orta = bool(sebepler) and not kotu

    if kotu:
        return {'durum': 'KIRMIZI', 'renk': 'danger', 'metin': 'İlaçlama önerilmez', 'sebep': ', '.join(sebepler)}
    if orta:
        return {'durum': 'SARI', 'renk': 'warning', 'metin': 'Dikkatli ol', 'sebep': ', '.join(sebepler)}
    return {'durum': 'YESIL', 'renk': 'success', 'metin': 'İlaçlamaya uygun', 'sebep': 'yağış düşük, rüzgar sakin'}


def forecast_for_bag(bag):
    """Bağ objesi alır, tahmini döner — GPS yoksa None."""
    if not bag or not bag.gps_koordinat:
        return None
    coords = parse_gps(bag.gps_koordinat)
    if not coords:
        return None
    return fetch_forecast(coords[0], coords[1])
