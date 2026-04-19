"""Claude Vision ile bitki hastalık / zararlı teşhisi."""
import os
import base64
import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    'Sen bir bağcılık / bitki koruma uzmanısın. Verilen fotoğrafı incele ve '
    'şunu Türkçe olarak kısa, somut bir şekilde cevapla: '
    '1) Fotoğrafta görülen hastalık/zararlı (mildiyö, külleme, kav, bağ zararlısı vb.) '
    '2) Belirti açıklaması (ne gördün) '
    '3) Kullanılabilecek ilaç grupları/etken maddeler '
    '4) Uygulama zamanı/koşulu tavsiyesi. '
    'Teşhis belirsizse "net değil" de ve ek foto/bilgi iste. Cevap en fazla 200 kelime.'
)


def teshis_et(image_bytes, mime='image/jpeg', user_note=''):
    """image_bytes → Claude Vision cevabı (str) veya None."""
    if not image_bytes:
        return None
    try:
        from anthropic import Anthropic
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            logger.warning('ANTHROPIC_API_KEY yok, teşhis atlanıyor')
            return None
        client = Anthropic(api_key=api_key)

        b64 = base64.standard_b64encode(image_bytes).decode('ascii')
        content = [
            {
                'type': 'image',
                'source': {'type': 'base64', 'media_type': mime or 'image/jpeg', 'data': b64},
            },
            {'type': 'text', 'text': user_note or 'Bu fotoğrafta hangi hastalık/zararlı var, ne ilaç önerirsin?'},
        ]

        model = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-5-20250929')
        resp = client.messages.create(
            model=model,
            max_tokens=500,
            system=_SYSTEM,
            messages=[{'role': 'user', 'content': content}],
        )
        return resp.content[0].text if resp.content else None
    except Exception as e:
        logger.exception(f'Claude vision hatası: {e}')
        return None
