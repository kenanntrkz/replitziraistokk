"""Claude tabanlı bağcılık tavsiye chatbot'u — stok + HÖS + hava bağlamıyla."""
import os
import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    'Sen deneyimli bir bağ-bahçe ziraat uzmanısın. Türkçe cevap ver. '
    'Verilen bağlam (stoktaki ilaç/gübreler, HÖS aktif parseller, hava tahmini) '
    'çerçevesinde somut, uygulanabilir tavsiye üret. '
    'Kurallar: '
    '- Sadece bağlamda verilen ilaç stoğundan seç; olmayan ilaç önerme. '
    '- HÖS (hasat öncesi süre) aktif parselde hasat önerme; yaklaşmışsa uyar. '
    '- Yağışlı/rüzgarlı havada ilaçlama önerme. '
    '- Dozajı çiftçi açık diliyle ver (ör: "100L suya 200ml"). '
    '- Cevap 250 kelimeyi aşmasın, markdown kullanma. '
    '- Emin değilsen "kesin teşhis için foto at" de.'
)


def tavsiye_al(soru, baglam_metni):
    """Soruya Claude ile cevap — baglam_metni user içinde bağlam olarak verilir."""
    if not soru:
        return None
    try:
        from anthropic import Anthropic
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            logger.warning('ANTHROPIC_API_KEY yok, tavsiye atlanıyor')
            return 'AI tavsiye servisi yapılandırılmamış (API anahtarı yok).'
        client = Anthropic(api_key=api_key)

        user_text = (
            'Bağlam (şu an sistemde):\n'
            f'{baglam_metni}\n\n---\nSoru: {soru}'
        )

        model = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-5-20250929')
        resp = client.messages.create(
            model=model,
            max_tokens=900,
            system=_SYSTEM,
            messages=[{'role': 'user', 'content': user_text}],
        )
        return resp.content[0].text if resp.content else None
    except Exception as e:
        logger.exception(f'Claude tavsiye hatası: {e}')
        return f'Hata: {str(e)[:200]}'
