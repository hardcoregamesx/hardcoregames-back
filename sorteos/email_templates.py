"""Plantilla de correo para el ganador de un sorteo.

Separada de services.py para que el diseño se pueda ajustar sin tocar la
logica de eleccion de ganador. Usa la paleta real de la marca (tokens de
:root en el bundle compilado del sitio, ver skill hardcoregames-architecture
-- fondo morado oscuro, gradiente cian/morado de las pantallas "evento"
como login y rewards, y el dorado que usa el sitio para sus CTA). No reusa
la plantilla de confirmacion de compra (settings.EMAIL_FOR_SALE) porque esa
trae secciones de guias de instalacion que no aplican aqui.
"""

# Tokens de marca (ver hardcoregames-architecture: paleta extraida de
# assets/index-ssfX69jx.css en produccion, convertidos de HSL a hex).
BG = '#150A29'
CARD = '#211339'
BORDER = '#3a2a5c'
TEXT_MUTED = '#c9bce0'
TEXT_BODY = '#e4dcf2'
GOLD_CTA = '#FAD338'
GREEN_CTA = '#42D780'
GRADIENT = 'linear-gradient(135deg,#4C0F85 0%,#2DBEEB 100%)'
GRADIENT_BAR = 'linear-gradient(90deg,#2DBEEB 0%,#4C0F85 50%,#2DBEEB 100%)'

INSTAGRAM_URL = 'https://instagram.com/hardcoregamesx'
WHATSAPP_URL = 'https://wa.link/y72sz9'
LOGO_URL = 'https://www.hardcoregames.co/assets/logo-CYf73ajV.png'


def winner_email_subject(sorteo):
    return f'🎉 ¡Ganaste el sorteo {sorteo.title}!'


def winner_email_html(sorteo, user):
    first_name = ((user.first_name or user.username or '').split(' ') or ['crack'])[0] or 'crack'

    prize_img_row = ''
    if sorteo.prize_image_url:
        prize_img_row = f'''
        <tr><td align="center" style="padding:0 30px 28px;">
          <img src="{sorteo.prize_image_url}" alt="{sorteo.title}"
               style="max-width:280px;width:100%;border-radius:10px;display:block;">
        </td></tr>'''

    return f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>¡Ganaste el sorteo! – Hardcore Games</title>
</head>
<body style="margin:0;padding:0;background-color:{BG};font-family:Arial,Helvetica,sans-serif;">
<span style="display:none;font-size:1px;color:{BG};line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">
¡{first_name}, ganaste {sorteo.title}! Aquí están los pasos para reclamar tu premio.
</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{BG};">
<tr><td align="center" style="padding:40px 10px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
       style="max-width:600px;background-color:{CARD};border-radius:12px;overflow:hidden;border:1px solid {BORDER};">

<tr><td style="background:{GRADIENT};padding:32px 30px;text-align:center;">
  <img src="{LOGO_URL}" width="160" alt="Hardcore Games" style="display:block;margin:0 auto 18px;max-width:160px;border:0;">
  <p style="margin:0;color:#ffffff;font-size:13px;letter-spacing:3px;text-transform:uppercase;opacity:0.9;">Hardcore Rewards</p>
</td></tr>

<tr><td align="center" style="padding:34px 30px 6px;">
  <h1 style="margin:0 0 8px;color:#ffffff;font-size:30px;font-family:Arial,Helvetica,sans-serif;">🎉 ¡Ganaste, {first_name}!</h1>
  <p style="margin:0;color:{GOLD_CTA};font-size:14px;letter-spacing:2px;text-transform:uppercase;font-weight:700;">{sorteo.title}</p>
</td></tr>

<tr><td style="padding:18px 36px 10px;">
  <p style="margin:0;color:{TEXT_MUTED};font-size:15px;line-height:1.6;text-align:center;">{sorteo.legend}</p>
</td></tr>
{prize_img_row}

<tr><td style="padding:0 30px 28px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{BG};border:1px solid {BORDER};border-radius:8px;">
  <tr><td style="padding:22px 24px;">
    <p style="margin:0 0 14px;color:{GOLD_CTA};font-size:12px;letter-spacing:2px;text-transform:uppercase;font-weight:700;">Para reclamar tu premio</p>
    <p style="margin:0 0 12px;color:{TEXT_BODY};font-size:14px;line-height:1.7;">
      <strong style="color:#ffffff;">1.</strong> Sube una historia a Instagram etiquetando a
      <a href="{INSTAGRAM_URL}" style="color:#2DBEEB;text-decoration:none;font-weight:700;" target="_blank">@hardcoregamesx</a>,
      mostrándote como ganador del sorteo y agradeciéndonos. 🙌
    </p>
    <p style="margin:0;color:{TEXT_BODY};font-size:14px;line-height:1.7;">
      <strong style="color:#ffffff;">2.</strong> Escríbenos por WhatsApp para coordinar la entrega de tu premio.
    </p>
  </td></tr>
  </table>
</td></tr>

<tr><td align="center" style="padding:0 30px 34px;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
  <tr><td align="center" style="padding-bottom:12px;">
    <table role="presentation" cellpadding="0" cellspacing="0"><tr>
      <td style="background-color:{GOLD_CTA};border-radius:6px;padding:13px 28px;">
        <a href="{INSTAGRAM_URL}" style="color:{BG};text-decoration:none;font-weight:700;font-size:14px;" target="_blank">📲 Subir mi historia</a>
      </td>
    </tr></table>
  </td></tr>
  <tr><td align="center">
    <table role="presentation" cellpadding="0" cellspacing="0"><tr>
      <td style="background-color:{GREEN_CTA};border-radius:6px;padding:13px 28px;">
        <a href="{WHATSAPP_URL}" style="color:{BG};text-decoration:none;font-weight:700;font-size:14px;" target="_blank">💬 Escribir por WhatsApp</a>
      </td>
    </tr></table>
  </td></tr>
  </table>
</td></tr>

<tr><td style="height:3px;background:{GRADIENT_BAR};font-size:0;line-height:0;">&nbsp;</td></tr>

<tr><td align="center" style="padding:22px 30px;background-color:{BG};">
  <p style="margin:0;color:#5a4a7a;font-size:11px;font-family:Arial,Helvetica,sans-serif;">
    Copyright &copy; 2026 Hardcore Games. Todos los derechos reservados. &middot; Colombia
  </p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>'''
