"""Resmi Zirai İlaç Defteri PDF üretimi (reportlab + DejaVu TTF — Türkçe)."""
import io
import os
import logging
import datetime
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

_DEJAVU_DIR = '/usr/share/fonts/truetype/dejavu'
_FONT_REGISTERED = False


def _register_fonts():
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', os.path.join(_DEJAVU_DIR, 'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', os.path.join(_DEJAVU_DIR, 'DejaVuSans-Bold.ttf')))
        _FONT_REGISTERED = True
    except Exception as e:
        logger.exception(f'DejaVu font register hatası: {e}')


def _parse_doz(ilac):
    """'20 ml/100 L' gibi metni aynen döndür; yoksa '-'."""
    return (ilac.dozaj or '-') if ilac else '-'


def _hos_gun(ilac):
    if not ilac:
        return '-'
    if ilac.hasat_suresi_gun:
        return f'{ilac.hasat_suresi_gun} gün'
    return ilac.hasat_suresi or '-'


def zirai_ilac_defteri_pdf(kullanimlar, baslangic, bitis, uygulayici='-'):
    """IlacKullanim listesi → Resmi Zirai İlaç Defteri PDF (bytes)."""
    _register_fonts()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=14 * mm, bottomMargin=12 * mm,
        title='Zirai İlaç Defteri',
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], fontName='DejaVu-Bold', fontSize=14, alignment=1, spaceAfter=4)
    h2 = ParagraphStyle('h2', parent=styles['Normal'], fontName='DejaVu', fontSize=9, alignment=1, spaceAfter=8, textColor=colors.grey)
    body = ParagraphStyle('body', parent=styles['Normal'], fontName='DejaVu', fontSize=8, leading=10)

    story = []
    story.append(Paragraph('RESMİ ZİRAİ İLAÇ KULLANIM DEFTERİ', h1))
    donem = f'{baslangic.strftime("%d.%m.%Y")} — {bitis.strftime("%d.%m.%Y")}'
    story.append(Paragraph(f'Dönem: {donem} · Düzenleme: {datetime.datetime.now().strftime("%d.%m.%Y %H:%M")}', h2))

    header = [
        'Tarih', 'Parsel', 'Ürün / Çeşit', 'İlaç Adı', 'Etken Madde', 'Grup',
        'Doz', 'Kullanılan', 'Su (L)', 'Hedef Hastalık', 'HÖS', 'Uygulayıcı',
    ]
    data = [header]

    for k in kullanimlar:
        ilac = k.ilac
        bag = k.bag
        data.append([
            k.tarih.strftime('%d.%m.%Y %H:%M') if k.tarih else '-',
            Paragraph(bag.ad if bag else '-', body),
            Paragraph((bag.ekim_tipi or '-') if bag else '-', body),
            Paragraph(ilac.ad if ilac else '-', body),
            Paragraph((ilac.etken_madde or '-') if ilac else '-', body),
            (ilac.grup or '-') if ilac else '-',
            Paragraph(_parse_doz(ilac), body),
            f'{round(k.kullanilan_miktar, 2)} {ilac.birim if ilac else ""}'.strip(),
            f'{round(k.su_miktari, 0)}' if k.su_miktari else '-',
            Paragraph((ilac.hedef_hastalik or '-') if ilac else '-', body),
            _hos_gun(ilac),
            uygulayici,
        ])

    if len(data) == 1:
        story.append(Spacer(1, 20))
        story.append(Paragraph('Bu dönemde ilaç kullanım kaydı bulunmuyor.', body))
    else:
        col_widths = [20*mm, 25*mm, 28*mm, 32*mm, 30*mm, 18*mm, 22*mm, 20*mm, 14*mm, 28*mm, 14*mm, 22*mm]
        tbl = Table(data, repeatRows=1, colWidths=col_widths)
        tbl.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'DejaVu-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'DejaVu'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7.5),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5f2d')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f6f9f6')]),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(tbl)

    story.append(Spacer(1, 14))
    footer_style = ParagraphStyle('f', parent=body, fontSize=8, textColor=colors.grey, alignment=1)
    story.append(Paragraph(
        'Bu defter T.C. Gıda, Tarım ve Hayvancılık Bakanlığı denetimlerinde ibraz edilmek üzere '
        'tarim.kenanturkoz.cloud sistemi üzerinden düzenlenmiştir. '
        'Kayıtlar elektronik ortamda tutulmakta olup çıktının altı ıslak imza ile onaylanmalıdır.',
        footer_style,
    ))
    story.append(Spacer(1, 18))
    sig_style = ParagraphStyle('s', parent=body, fontSize=9, alignment=1)
    sig_data = [[
        Paragraph('Düzenleyen<br/>_______________________', sig_style),
        Paragraph('Tarih<br/>_______________________', sig_style),
        Paragraph('İmza<br/>_______________________', sig_style),
    ]]
    sig_tbl = Table(sig_data, colWidths=[90*mm, 60*mm, 90*mm])
    sig_tbl.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(sig_tbl)

    doc.build(story)
    return buf.getvalue()
