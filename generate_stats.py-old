#!/usr/bin/env python3
"""
Genera index.html con le statistiche QSO gia' calcolate (nessun fetch/JS
lato client necessario), a partire da log.adi.

Contenuto della card (senza titolo, senza sfondo, senza padding laterale:
la barra delle bande parte esattamente dal bordo sinistro dell'iframe, cosi'
resta allineata al titolo che sta fuori, sulla pagina QRZ):
  - Bande: vengono mostrate solo quelle presenti nel log. Se almeno due bande
    hanno una percentuale sotto MIN_BAND_PCT vengono raggruppate in "Other"
    (impostare MIN_BAND_PCT = 0 per mostrarle tutte separatamente).
  - Orari: istogramma dei QSO per ora UTC (campo TIME_ON) con evidenziate
    le TOP_HOURS fasce orarie piu' frequenti.
  - Mappa: planisfero completo (Antartide e Artico inclusi) con evidenziati tutti
    i paesi collegati. Il paese viene ricavato dal campo DXCC (numero) e, se
    manca, dal campo COUNTRY (nome).

I confini dei paesi (Natural Earth, pubblico dominio) e la tabella delle
entita' DXCC sono incorporati in fondo a questo file (MAP_BLOB): non serve
nessun altro file ne' accesso a internet durante la build.

Uso: python3 generate_stats.py
Legge log.adi nella stessa cartella, scrive index.html nella stessa cartella.
"""

import base64
import difflib
import html
import json
import re
import zlib
from datetime import datetime, timezone

MIN_BAND_PCT = 1.0    # bande sotto questa % raggruppate in "Other" (0 = disattivato)
TOP_HOURS = 3         # quante fasce orarie UTC evidenziare
TOP_COUNTRIES = 3     # quanti paesi mostrare nella riga "Top" sotto la mappa
LEFT_OFFSET_PX = 0    # ritocco fine dell'allineamento a sinistra (anche negativo, es. -1)

BAND_COLORS = {
    '20m': '#e8a33d', '40m': '#6c3483', '80m': '#1a9e77',
    '30m': '#e186a8', '15m': '#2e7fd6', '10m': '#c0392b',
    '17m': '#1e8449', '12m': '#7f8c8d', '160m': '#d35400',
    '6m': '#9b59b6', '2m': '#3498db',
}

# Entita' DXCC che nella mappa vengono mostrate come un altro paese
ISO_ALIAS = {'XI': 'GB'}          # Northern Ireland -> Regno Unito

# Nomi alternativi usati da alcuni logger nel campo COUNTRY (usati solo se
# manca il numero DXCC). Chiave = nome, valore = codice ISO.
NAME_ALIASES = {
    'Fed. Rep. of Germany': 'DE', 'Federal Republic of Germany': 'DE',
    'United States': 'US', 'USA': 'US', 'Hawaii': 'US', 'Alaska': 'US',
    'European Russia': 'RU', 'Asiatic Russia': 'RU', 'Kaliningrad': 'RU',
    'England': 'GB', 'Scotland': 'GB', 'Wales': 'GB', 'Northern Ireland': 'GB',
    'Sardinia': 'IT', 'Sicily': 'IT', 'Vatican': 'VA', 'Vatican City': 'VA',
    'Czech Republic': 'CZ', 'Czechia': 'CZ', 'Slovak Republic': 'SK',
    'Republic of Korea': 'KR', 'South Korea': 'KR', 'Korea': 'KR',
    'Bosnia-Herzegovina': 'BA', 'Macedonia': 'MK', 'North Macedonia': 'MK',
    'European Turkey': 'TR', 'Asiatic Turkey': 'TR', 'Turkey': 'TR',
    'Canary Islands': 'ES', 'Balearic Islands': 'ES', 'Ceuta & Melilla': 'ES',
    'Azores': 'PT', 'Madeira Islands': 'PT', 'Corsica': 'FR', 'Crete': 'GR',
    'Dodecanese': 'GR', 'Shetland Islands': 'GB', 'Ivory Coast': 'CI',
    "Cote d'Ivoire": 'CI', 'Cape Verde': 'CV', 'Trinidad & Tobago': 'TT',
}


def norm_name(s):
    s = s.lower().replace('&', ' and ')
    s = re.sub(r'[^a-z0-9 ]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def load_map_data():
    return json.loads(zlib.decompress(base64.b64decode(MAP_BLOB)).decode('utf-8'))


def build_name_index(data):
    """nome normalizzato -> codice ISO (da tabella DXCC, nomi mappa e alias)."""
    idx = {}
    for iso, c in data['c'].items():
        idx.setdefault(norm_name(c['n']), iso)
    for iso, p in data['p'].items():
        idx.setdefault(norm_name(p[0]), iso)
    for _num, (iso, name) in data['x'].items():
        if iso != 'ZZ':
            idx.setdefault(norm_name(name), iso)
    for name, iso in NAME_ALIASES.items():
        idx[norm_name(name)] = iso
    return idx


def resolve_country(dxcc_value, country_name, data, name_index):
    """Restituisce il codice ISO del paese (se disegnabile sulla mappa) o None."""
    iso = None
    if dxcc_value:
        key = dxcc_value.strip().lstrip('0') or '0'
        entry = data['x'].get(key)
        if entry:
            iso = entry[0]
    if iso is None and country_name:
        key = norm_name(country_name)
        iso = name_index.get(key)
        if iso is None:
            close = difflib.get_close_matches(key, list(name_index.keys()), n=1, cutoff=0.85)
            if close:
                iso = name_index[close[0]]
    if iso is None:
        return None
    iso = ISO_ALIAS.get(iso, iso)
    if iso in data['c'] or iso in data['p']:
        return iso
    return None


def field(record, name):
    """Valore di un campo ADIF (es. <band:3>20m) oppure None."""
    m = re.search(r'<\s*' + name + r'\s*(?::\d+(?::[A-Za-z])?)?\s*>([^<>]+)', record, re.I)
    return m.group(1).strip() if m else None


def parse_log(path, data):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()

    name_index = build_name_index(data)
    records = re.split(r'<\s*eor\s*>', text, flags=re.I)
    total = 0
    bands = {}
    hours = [0] * 24
    countries = {}
    unresolved = 0

    for record in records:
        if not re.search(r'<\s*call\s*[:>]', record, re.I):
            continue
        total += 1

        # Banda
        b = field(record, 'band')
        if b:
            b = b.lower()
            if not b.endswith('m') and 'cm' not in b and 'km' not in b:
                b = b + 'm'
            bands[b] = bands.get(b, 0) + 1
        else:
            bands['unknown'] = bands.get('unknown', 0) + 1

        # Ora UTC (TIME_ON: HHMM o HHMMSS)
        t = field(record, 'time_on')
        if t and len(t) >= 2 and t[:2].isdigit() and int(t[:2]) < 24:
            hours[int(t[:2])] += 1

        # Paese (DXCC o COUNTRY)
        dxcc_value = field(record, 'dxcc')
        country_name = field(record, 'country')
        if dxcc_value or country_name:
            iso = resolve_country(dxcc_value, country_name, data, name_index)
            if iso:
                countries[iso] = countries.get(iso, 0) + 1
            else:
                unresolved += 1

    if total == 0:
        total = 1

    return total, bands, hours, countries, unresolved


def pct(n, total):
    return round((n / total) * 100, 1) if total else 0.0


def bar_and_legend(segments):
    """segments: list of (label, pct, color)"""
    bar = ''.join(
        f'<div class="bar-segment" style="width: {p}%; background: {c};" title="{label}: {p}%"></div>'
        for label, p, c in segments
    )
    legend = ''.join(
        f'<div class="legend-item"><span class="color-dot" style="background: {c};"></span>{label} ({p}%)</div>'
        for label, p, c in segments
    )
    return bar, legend


def build_band_segments(bands, total):
    """Solo le bande presenti nel log; le piu' rare vengono raggruppate in 'Other'."""
    sorted_bands = sorted(bands.items(), key=lambda x: -x[1])

    rare = [(b, c) for b, c in sorted_bands
            if MIN_BAND_PCT and (c / total) * 100 < MIN_BAND_PCT]
    group_rare = len(rare) >= 2
    rare_names = {b for b, _ in rare} if group_rare else set()

    segments = [
        (b, pct(c, total), BAND_COLORS.get(b, '#555555'))
        for b, c in sorted_bands
        if b not in rare_names
    ]
    if group_rare:
        other_count = sum(c for _, c in rare)
        segments.append(('Other', pct(other_count, total), '#95a5a6'))
    return segments


def build_hours_chart(hours):
    """Istogramma a 24 colonne (ore UTC) + testo con le fasce piu' frequenti."""
    total_h = sum(hours)
    if total_h == 0:
        return '', '', ''

    max_h = max(hours)
    top = [h for h in sorted(range(24), key=lambda x: -hours[x])[:TOP_HOURS] if hours[h] > 0]

    bars = ''
    labels = ''
    for h in range(24):
        height = max(2, round(hours[h] / max_h * 100)) if hours[h] > 0 else 0
        color = '#2e7fd6' if h in top else '#b8c4d0'
        title = f'{h:02d}:00-{h:02d}:59 UTC: {hours[h]} QSO ({pct(hours[h], total_h)}%)'
        bars += f'<div class="hour-bar" style="height: {height}%; background: {color};" title="{title}"></div>'
        labels += f'<span>{h:02d}</span>'

    top_text = ' &middot; '.join(
        f'{h:02d}:00&ndash;{h:02d}:59 ({pct(hours[h], total_h)}%)' for h in top
    )
    return bars, labels, top_text


def build_world_map(counts, data):
    """SVG del planisfero: paesi non collegati in grigio chiaro, collegati in blu."""
    land = ''.join(c['d'] for iso, c in data['c'].items() if iso not in counts)

    worked = ''
    for iso, n in sorted(counts.items(), key=lambda x: x[1]):
        title = ''
        if iso in data['c']:
            c = data['c'][iso]
            title = f'<title>{html.escape(c["n"])}: {n} QSO</title>'
            if c['d']:
                worked += f'<path class="worked" d="{c["d"]}">{title}</path>'
            if 'c' in c:   # paese minuscolo: aggiunge un pallino ben visibile
                worked += (f'<circle class="worked" cx="{c["c"][0]}" cy="{c["c"][1]}" r="22">'
                           f'{title}</circle>')
        elif iso in data['p']:
            name, x, y = data['p'][iso]
            worked += (f'<circle class="worked" cx="{x}" cy="{y}" r="22">'
                       f'<title>{html.escape(name)}: {n} QSO</title></circle>')

    svg = (f'<svg class="map" viewBox="0 0 {data["w"]} {data["h"]}" '
           f'role="img" aria-label="World map of countries worked">'
           f'<path class="land" d="{land}"/>{worked}</svg>')

    def country_name(iso):
        if iso in data['c']:
            return data['c'][iso]['n']
        return data['p'][iso][0]

    total_c = sum(counts.values())
    top = sorted(counts.items(), key=lambda x: -x[1])[:TOP_COUNTRIES]
    top_text = ' &middot; '.join(
        f'{html.escape(country_name(iso))} ({pct(n, total_c)}%)' for iso, n in top
    )
    return svg, len(counts), top_text


def build_html(total, bands, hours, countries, data, updated_at):
    band_segments = build_band_segments(bands, total)
    band_bar, band_legend = bar_and_legend(band_segments)
    hour_bars, hour_labels, top_text = build_hours_chart(hours)
    map_svg, n_countries, top_countries = build_world_map(countries, data)

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QSO Statistics - IU3QOA</title>
<style>
html, body {{ margin:0; padding:0; background:transparent; }}
body {{ font-family:Arial,sans-serif; color:#333; }}
.card {{ width:100%; max-width:844px; margin:0 0 0 {LEFT_OFFSET_PX}px; padding:2px 0 0 0; background:transparent; box-sizing:border-box; }}
.bar-container {{ width:100%; height:26px; background:#ddd; border:1px solid #000; border-radius:13px; display:flex; overflow:hidden; margin-bottom:6px; box-sizing:border-box; }}
.bar-segment {{ height:100%; }}
.legend {{ display:flex; flex-wrap:wrap; gap:15px; font-size:13px; margin-bottom:14px; }}
.legend-item {{ display:flex; align-items:center; gap:5px; }}
.color-dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
.section-title {{ font-size:13px; font-weight:bold; margin:4px 0 6px 0; color:#333; }}
.hours-chart {{ width:100%; height:60px; display:flex; align-items:flex-end; gap:3px; border-bottom:1px solid #999; }}
.hour-bar {{ flex:1; border-radius:2px 2px 0 0; }}
.hours-labels {{ width:100%; display:flex; gap:3px; margin-top:2px; }}
.hours-labels span {{ flex:1; text-align:center; font-size:9px; color:#666; }}
.top-hours {{ font-size:12px; margin-top:6px; color:#333; }}
.map-section {{ margin-top:16px; }}
.map {{ width:100%; height:auto; display:block; }}
.map path, .map circle {{ stroke:#fff; stroke-width:0.5; stroke-linejoin:round; vector-effect:non-scaling-stroke; }}
.map .land {{ fill:#dbe2e8; fill-rule:evenodd; }}
.map .worked {{ fill:#2e7fd6; fill-rule:evenodd; }}
.last-update {{ text-align:left; font-size:11px; color:#888; margin-top:10px; }}
</style>
</head>
<body>
<div class="card">

<div class="bar-container">{band_bar}</div>
<div class="legend">{band_legend}</div>

<div class="section-title">Most active hours (UTC)</div>
<div class="hours-chart">{hour_bars}</div>
<div class="hours-labels">{hour_labels}</div>
<div class="top-hours">Top: {top_text}</div>

<div class="map-section">
<div class="section-title">Countries worked ({n_countries})</div>
{map_svg}
<div class="top-hours">Top: {top_countries}</div>
</div>

<div class="last-update">Last update: {updated_at}</div>

</div>
</body>
</html>
"""


# --- Dati della mappa (generati automaticamente: non modificare a mano) ---
# Contiene: confini dei paesi (Natural Earth 1:50m, pubblico dominio, proiezione
# Natural Earth, Antartide compresa, semplificati), pallini per i territori senza confini propri e
# la tabella DXCC (numero entita' -> codice ISO, nome). Formato: JSON + zlib + base64.
MAP_BLOB = (
    "eNpsvc2WJMeRpfkqdrCZTRiO6b9q7cAkAIJAgigkSHZxziwCQDQQTc8MdmQm2UCfXs6TzGJO7+cN6sVG5X6i5p6s6mKTQES4u7mZ"
    "qqjIlXuv/M+P/vHRv/Scj7uPfv7oX3Lq4+6jHz76l//50V/+bP/95qN/+egvj6+/v//+Hw8f3X304/zXl3mkusV+pMue0172vpft"
    "2Ose097m/4W0hT3Ufcwfxj2EPc7/LvPv5s/m/8Y+fz7/pG15i3k7tvnrOLZ47OHY8vyLLYz52lDnr45t/iwM+9/547DFtPU9bLns"
    "zf6gzKvYQ7QX2Bv++tH/uvvoLy/Py75//f3j/fWi4/zzGsZlXs8W7SqbvWr+05b2aJ+kX4x9frc9zqve47zkuKdov2/zuvdk17X3"
    "sWW7uLiXvo2tzX/s23zBfHu7xnmlza452qUe8w+C/rVvIdv12zvOC59/vCf7Gvb5ZR+7btm8gPlBzW5cthtmb6j/3vuW8/yvqk+Y"
    "F7vpU5r9V7T/0lvqV/Oqx2Yf3/asi5sfXrdqb2P3bn5Ktz/TC+25tfmSqlv3b5+uW/dvD68f3qw7V3Ker2g5XuYl6jbNf7P7N/ai"
    "ez+/mD3aeU/07IP9YD7nOu+b/Wr+o/37/OLRVke11TH/MxdBnv/e51/Nv7Nl0bkN86vag0m2PuY931Kzr2Y32b6Rvd38dsm+T53/"
    "HX6dF1jnm/Y8LsGegb3jfJNqH8EX+9PX64v96fHh3Zv71+ur1TrmK2s45lcL8xV5fidWhD0H+5d5w9L88fwy0S5ns79KtgSPLc11"
    "oOVrv7XlHOZNnd9p/v187bxuuzfF7lXq9lTm3ph/3nZ7g3nfNrspLJ5iT0offNhTmTezaIXadxy6t2VeS7Yb5B9vnzHfJdmG0crR"
    "srCbZf80V5X+PtjSCvMDu934+WL7KrZE5r80uyR77byddt+H3XV7dPZhZddW1Ve3189/SH2f39m2eYp2e7nYpBsyPzlotWb+1q7T"
    "VohiQ7BX2aq3/7Prq/Zh1V9uz2n4fijaTTOIzPUa7YtutuEsuvjuj1oZ3ZbDvC4t43nlv87HaCt0hHg57Avb/dwHT/5c0n96ePPw"
    "6/uHyxkQYrd3GDVebCXHwJ61Kwj2fO0iFXjSDAiKNvYn82qiHtDcpFqN0deylrW+frYf27OfDzgpcMVNl5X5KsHeObBV5iO0O1Q2"
    "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"
    "i7/s7GyX29m+jWffvbCz7/74+261sAbOuurr+OdNF8/9esNfPq232/hndWiLZ6Gugv3ka/3k4tNmvtxaJ2AVY/RnRSjyePL6jZ28"
    "ji/8ab65jeeqtnxWNPZzxx/s1PF6923YjsVOMyHPyqap4wUnf7ILTu43i8ftw/xxvKZpuiqOS9vbNSe6Zv15/Zj997NhWC5Wd//D"
    "r3yMl1ZtfIU6VPHSmzO79Gb9ZVjO4+gHDW5lZ95f6EnmX4YNWOz1d/v76TZdeBaXkP3e8S889Gq+2AzPsuv5Jyojmhcvdo/b+XZh"
    "iNDQlPmzomuUxf2rfbpCD3oUv60zuce7BTv222/x2NGnXXa0WI4/GU+WdvLopZ3cy/3GE5U+xXs7cTdf/vH3O3+EuT3D8Sb+91rX"
    "1brBn+J1f/zPg/eJ5xo79/7a7rGcP37R07S6/lzHSHPHg930iMvbefzGdrDXlfrrhwEBgOv5w1rnilzDrOd+eNwOm9v5w/R8s6v5"
    "7uAtC43L60u7fBUvjbeyiy8Xn9dxxhxcqdE6eq0r73aL5ZLfY5x+0eExU2snNE5HF3bCi+F2VKPyTqP3uIhf63P2bvf46Cc1LJf2"
    "tpfD9+y3Ya5xu97F4fBbHzyRRuzDi3i5Hc1uh+zo28ApjduRxm3CENqJfhzQ4/mf19nlbvi21lzQuL2/0In/aibadRqwF9e6bjnM"
    "N4fPFDRKVx/j6au5TXQ7Vk6/uRxW98PiIXs3DL/rnEYprsVnPy1FO1dPf7dZbBeP99nlerO9z47Xm9XAUzf/cMn1+mG+XIz30Bgd"
    "/2oXOFzajk7T6iquhod5Zotimf22Xg06348vaSc2TwcLIx//+GRYDp+GR43V9n7ILtbL3efP84OrNV5nNm2u7tdxGvz14GyYfmjY"
    "bVlJF9GM+OwqNXSv39r5+/nd+vHgj6txusST2/s40ffPavRO/qSzP9kwO62Ru7J1crJcfP06bLbr1f55DdzJOzsv87Z3SqMXTd+z"
    "/9Ly2VXTTEsis2Y8NHinuu1m2Gq0q2Jcsieb9Y9xDvAHk5F6Pi7P5wtNrEqjc2U3ez48Dp/vh/XeY1bV9JfD42YdT++/RVWPT/J8"
    "fTtEIxJvoRMamQubMi/mj7bdLudPvkIrRuXczw2b/Rt245c+X6yGg5fQWJyakXjxl918u94s4myLG+hq0G1rjcqFfauL4a/R9ugg"
    "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"
    "Mmnh1tjxP9lsOFs/rg24+be//T9bcckS"
)


if __name__ == '__main__':
    map_data = load_map_data()
    total, bands, hours, countries, unresolved = parse_log('log.adi', map_data)
    updated_at = datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
    html_out = build_html(total, bands, hours, countries, map_data, updated_at)
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f"Generato index.html - {total} QSO totali - {len(countries)} paesi - aggiornato {updated_at}")
    if unresolved:
        print(f"Attenzione: {unresolved} QSO con paese non riconosciuto (non disegnati sulla mappa)")
