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
    manca, dal campo COUNTRY (nome). Su ogni paese e' scritto il numero di QSO;
    se nel campo COMMENT di almeno un QSO del paese compare "POTA", il paese e'
    colorato di verde (POTA_COLOR) e accanto al totale compare, tra parentesi,
    quanti di quei QSO sono POTA (es. "100 (12)").

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
MAP_COLOR = '#2e7fd6'   # paesi collegati
POTA_COLOR = '#43A047'  # paesi con almeno un QSO POTA

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
    pota = {}
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
                comment = field(record, 'comment') or ''
                if re.search(r'\bPOTA\b', comment, re.I):
                    pota[iso] = pota.get(iso, 0) + 1
            else:
                unresolved += 1

    if total == 0:
        total = 1

    return total, bands, hours, countries, pota, unresolved


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


LABEL_CHAR_W = 54     # larghezza stimata di un carattere (unita' mappa: 10 = 1 px)
LABEL_H = 100         # altezza stimata dell'etichetta
LABEL_MARGIN = 12     # spazio minimo tra due etichette
DOT_R = 22            # raggio dei pallini (paesi minuscoli e territori)
# angoli provati per spostare un'etichetta: est, ovest, sopra, sotto, poi le diagonali
LABEL_ANGLES = [0, 180, 90, 270, 45, 135, 315, 225, 15, 165, 345, 195]


def place_labels(items, width, height):
    """
    items: lista di (iso, testo, (x, y), e_pallino). Piazza le etichette evitando
    che si sovrappongano; se non stanno sopra il paese le sposta li' accanto e
    restituisce anche il punto di ancoraggio per tracciare una lineetta.
    Ritorna lista di (iso, testo, cx, cy, ax, ay, tracciare_linea).
    """
    import math
    placed = []
    result = []
    for iso, text, (ax, ay), is_dot in items:
        w = len(text) * LABEL_CHAR_W + 10
        h = LABEL_H
        candidates = [] if is_dot else [(ax, ay)]
        for k in range(6):
            gap = 50 + 80 * k
            for ang in LABEL_ANGLES:
                a = math.radians(ang)
                candidates.append((ax + math.cos(a) * (w / 2 + gap),
                                   ay - math.sin(a) * (h / 2 + gap)))
        for cx, cy in candidates:
            box = (cx - w / 2 - LABEL_MARGIN, cy - h / 2 - LABEL_MARGIN,
                   cx + w / 2 + LABEL_MARGIN, cy + h / 2 + LABEL_MARGIN)
            if box[0] < 0 or box[2] > width or box[1] < 0 or box[3] > height:
                continue
            if any(not (box[2] <= p[0] or box[0] >= p[2] or box[3] <= p[1] or box[1] >= p[3])
                   for p in placed):
                continue
            placed.append(box)
            # distanza tra il punto di ancoraggio e il bordo dell'etichetta
            dx = max(cx - w / 2 - ax, 0, ax - (cx + w / 2))
            dy = max(cy - h / 2 - ay, 0, ay - (cy + h / 2))
            result.append((iso, text, cx, cy, ax, ay, math.hypot(dx, dy) > 100))
            break
    return result


def build_world_map(counts, pota, data):
    """
    SVG del planisfero: paesi non collegati in grigio chiaro, collegati in blu,
    paesi con almeno un QSO POTA in verde. Su ogni paese il numero di QSO.
    """
    land = ''.join(c['d'] for iso, c in data['c'].items() if iso not in counts)

    def country_name(iso):
        return data['c'][iso]['n'] if iso in data['c'] else data['p'][iso][0]

    shapes = ''
    label_items = []
    for iso, n in sorted(counts.items(), key=lambda x: x[1]):
        p = pota.get(iso, 0)
        cls = 'worked pota' if p else 'worked'
        tip = f'{html.escape(country_name(iso))}: {n} QSO' + (f' ({p} POTA)' if p else '')
        text = f'{n} ({p})' if p else f'{n}'
        if iso in data['c']:
            c = data['c'][iso]
            if c['d']:
                shapes += f'<path class="{cls}" d="{c["d"]}"><title>{tip}</title></path>'
            if 'c' in c:   # paese minuscolo: pallino ben visibile
                cx, cy = c['c']
                shapes += f'<circle class="{cls}" cx="{cx}" cy="{cy}" r="{DOT_R}"><title>{tip}</title></circle>'
                label_items.append((iso, text, (cx, cy), True))
            else:
                lx, ly = c['l']
                label_items.append((iso, text, (lx, ly), False))
        else:
            name, x, y = data['p'][iso]
            shapes += f'<circle class="{cls}" cx="{x}" cy="{y}" r="{DOT_R}"><title>{tip}</title></circle>'
            label_items.append((iso, text, (x, y), True))

    # le etichette dei paesi con piu' QSO hanno la precedenza sulla posizione
    label_items.sort(key=lambda it: -counts[it[0]])
    lines = ''
    labels = ''
    for iso, text, cx, cy, ax, ay, leader in place_labels(label_items, data['w'], data['h']):
        if leader:
            lines += f'<line class="leader" x1="{round(ax)}" y1="{round(ay)}" x2="{round(cx)}" y2="{round(cy)}"/>'
        pos = f'x="{round(cx)}" y="{round(cy)}" dy=".35em" text-anchor="middle"'
        labels += f'<text class="lbl-halo" {pos}>{text}</text><text class="lbl" {pos}>{text}</text>'

    svg = (f'<svg class="map" viewBox="0 0 {data["w"]} {data["h"]}" '
           f'role="img" aria-label="World map of countries worked">'
           f'<path class="land" d="{land}"/>{shapes}{lines}{labels}</svg>')

    total_c = sum(counts.values())
    top = sorted(counts.items(), key=lambda x: -x[1])[:TOP_COUNTRIES]
    top_text = ' &middot; '.join(
        f'{html.escape(country_name(iso))} ({pct(n, total_c)}%)' for iso, n in top
    )
    return svg, len(counts), top_text


def build_html(total, bands, hours, countries, pota, data, updated_at):
    band_segments = build_band_segments(bands, total)
    band_bar, band_legend = bar_and_legend(band_segments)
    hour_bars, hour_labels, top_text = build_hours_chart(hours)
    map_svg, n_countries, top_countries = build_world_map(countries, pota, data)

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
.map .worked {{ fill:{MAP_COLOR}; fill-rule:evenodd; }}
.map .worked.pota {{ fill:{POTA_COLOR}; }}
.map .leader {{ stroke:#555; stroke-width:0.6; vector-effect:non-scaling-stroke; fill:none; }}
.map .lbl, .map .lbl-halo {{ font:700 90px Arial,sans-serif; pointer-events:none; }}
.map .lbl {{ fill:#1b1b1b; }}
.map .lbl-halo {{ fill:#fff; stroke:#fff; stroke-width:2.4px; stroke-linejoin:round; vector-effect:non-scaling-stroke; }}
.map-legend {{ margin:6px 0 0 0; }}
.legend-note {{ color:#666; font-size:12px; }}
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
<div class="legend map-legend">
<div class="legend-item"><span class="color-dot" style="background: {MAP_COLOR};"></span>Countries worked</div>
<div class="legend-item"><span class="color-dot" style="background: {POTA_COLOR};"></span>Countries with POTA QSO</div>
<div class="legend-item legend-note">Number = QSO in that country &middot; (n) = of which POTA</div>
</div>
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
    "eNpsvcuWHNeVJPorvji5k3Su835oRoIkCBKAUAQptXRXD4JANpFFRyYrkRCb7NXD/pIe9Or5/QP92D1mto+7J0slFcXIiPDwxzn7"
    "Ydu27f/xya+f/Kml5K4+effJn1Js/eqTN5/86X988ve/4p+3n/zpk7/fvP/x8uOv159cffJ2vHyReixLaC5ua4prXtuaF7eWNcS1"
    "jv/4uPjVl7WPP4bV+zWMf+bxufG38b+hjb+Pj9QlLSEtbhlvh74Et3q3pPGJxffxXV/GW24Zf/Md/zv+7JcQl7b6JeW14gN5nMXq"
    "A76AA/4+TnD75E//b+ouXYXq3H/9n1ef/P3FfhmX9z/eXI6LCOPrxfdtnN8ScNYVRxn/tsQ14Jf5Rl/Hta5hXMUaxiWENQa8X8d1"
    "rBHnuba+JJxsWHNb+lLHv7ZlfGEcHuc8zrziGgJO3Y0PeL5si0+4HhxxXMj48BpxWfj9vPaVt3CcwPihihuZcANxQP5zbUtK4x+F"
    "vzBOduGvVPwj4B88JN8aZ90X/HxdE09u/HhZCg6Dezl+peFj/CKeYx1fKfutbL5cheICbuXfvpy38m/X769v553MKY0j1BS2ccq8"
    "beMV7mdfM5/NuFA8+nGPuDY8/jDWQRn3EW+Nf8XrcSMCVk/B6hn/HYskjddtfGp8Dsum6baMS8eDilg/4xksseJScdNxhTjcuNqI"
    "6yvjn/73cYJlHLSlvnk8ExxxHKTgJ/YLzaGlK18b18xfXs4L/cvN9cPt5f281FL6OFLxblyqH0dI4xq1YvCc8GLc0Dj+PC4u4PQW"
    "fCpiyboljnXC5Y53sfz9uOnjGsfnx3fHdeBeZdy72PDUxl4aH68rDjDu44KbpMWV8ST5ww5PbdzczBWMa+6813mcS8INs5/Hb4yj"
    "RGwwriwuG9w8/NtYdfy8x9Lz4wcbHsT4Mi4FS2i8qDglfHfcXjyHjqeAR4kfyyu3Ni8d3x//Ets6rhlmIQbcbp1s5A0Zv+y5mpM+"
    "i/PEiqEt8fgWdgX+g/Mr+LFiX8dz67ZfMnfbMDpjPQdc6IINCWtk1iJwpTQsj3FeXObjzH8fjxErtvuwOVww7ufa50ooJeQrn3vl"
    "StiX/F+ub69//3i97QYkNByxl7BhpQevPY4z8njeOGkarjgMCK0VPjLOLvCBjU3N1RpsrXPZ83Yk/BlrYTzwSMMXFp5m0qV5HNlr"
    "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"
    "ra5r9QU/5+v++J+Pnief6+zc+wv7js3y/rPuptf1r3SMtHk+OMy3uLla5ndsB0ddqU/frhCbuFjebnWuqTXMuu/b+4fV7mp5O9/f"
    "4u1y/+gpG43Ly9d2+V2+NH+VXfx6/WmbZ8yjKzVaRy915fV+vdnwe4zTjzo8ZXbthMbp6NxOePHejmpU3mn07tf5bX2q3u3v7/2k"
    "huW1Pe3r1dfq19VS43axz8PhX/3ojjRiH57ly+1odbWqjn5fcUrjdqRxmyGUdmKcBvR4+Zdt9Xq/+n2ruaBxe3+uE//VTLTrNGDP"
    "LnTdZrXcPb6noFF6+1M+/XZpE92Oxfk3N6u7m9X6tnq3Wv2mcxqlvBaf/Gkp2rl2/txu/bC+v6leb3cPN9Xxdne34q67f7jkYnu7"
    "3Kyn79AYHf9iFzj43I7O0+ptXg23y8oWxab6dXu30vlxekg7sfv2aGHU04dPVpvVx9W9xurhZlWdbzf7T5+Wj67WeJ3ZtHl7s83T"
    "4G+Pzob5h1b7B1bSeTYjPruihu7lGzt/s7ze3j/6cJqmSz75cJMn+uFZjd7Jzzr7JxtmpzVyb22dnGzWX76sdg/bu8PzGriTd3Ze"
    "5u3glEYvm74n/6Xls6vmmVYElM14aPBO9bW71YNGOzXTkj3Zbb9Pc4APzEbq6bQ8n641sZJG56192dPV/erTzWp7cJspzZ9c3e+2"
    "+fThU6R2upOn26tVNiL5K3RCI3NuU+bZ8t62483ym6/QxKi88nOr3eEXDtObfrW+Wz16CI3FqRmJZ3/dLx+2u3WebXkDvVvpa1uN"
    "yrm9q/PV37Lt0UFWmt3gszy3d34pM8YW/bP7/Mq4r1Yj8ezSjj7crLdf/HCarM2z/W77ZWWyPJO5aef19Xy5++v+Jhu8013etnVS"
    "o3Bsv/58tbszq24GJi/A7d0NH+/nj+MRHDwbIkC6bPjzZS/zdy1QM7bz45/P/7TKoz5/QafBOcbiAKC3o830aM/znvO9+mF7v/qt"
    "euUvo9MwHR/rQ951YYc1TqfP5x9zL8bOYYpkAVe72z17ZKdB+nB6YGE+rHfX6zuBxuwCBupXLIz1+djB/p88NKPezeNxtv+6XD/8"
    "+8Vyf7WujnbLj+tl9Tqbgd2BKeo0PGe/yBR9swVwMK96Dc2JDcJJ3iR0iFlji/M0787/+eXPVqPXyDx9o3l/mx0x12raf9ysP+kC"
    "jcOFmeRnm7xtbn7Po7fTGZaMzb3T1TYPAr+oATi1uZcdv4dVNr8c1xicPrXjeQzc5+j1+C/s6hf54dc6xvJ4yzcU19F2fz3fC9ud"
    "X2zvrvY73v3QTEOouXKaX9fy7ptO6el+sJf4Q54qPoUGfBZbfwfep5042GJwqmRfTvIv/fG/l1qGA5uyLevsFSx3y+s936kHeXs0"
    "7SE6qCe5tNG/3O8+szOc5Nt4/A5GnBQbhMtdvpur5ZWuvMxOx7V+ddQjHv0k78Ff7Tjvo6erb/fZ+JRddMTXOMUJeYTf8Wk86kGf"
    "nh+8dR3G1tnaOt/ePeTv3C0fdEIv75U9CI7dq/0nXveo5/4wn/mwvvu0yv8tmyAvO5s2HnWcjPvpJtuG7f32kQ9TayiO3ulBC2hQ"
    "J+aXfFpcu/APu/3l1gBFrPmmZnW/Zx7dcoxV/UZvmEZQHW4nDzRfmr2r/Aa3ecC+cZYpfaqz2frdr/w4U/q1jhfj3dTDZCqdpUFH"
    "mdQ/Tdcujtf393hEDV6qfv7FMhuBNUf1yC/sJTlOVQP1Z6zqgfMapu0I4VYdnKfJy9/u/Js1Ci/PcRVX1fa3vK3hEDbzEnj5YA0a"
    "d39yoRrc0hM5IdvN9vajjyH+53sbjZd3D7ZJPKztHqvL7BZ92t7e7m2a2bHqvYV0VX6oq7xF5OB25/evkctBmq3Wu3xL31Z+U/Om"
    "8MPyd34OD1WW7dmnfbFJDR7nD2aUfsjf628Kn1MD/MP25s52yuroYbvh3eB1alL+kN8+G9vvLBptlMvHnn87DbMutw3xj/+8u1p9"
    "f3xZN21JZ3n87rJHtFsyhGHeD86yqdgtD12t5sAdPVvusvlbPF/f3eHM/r7O/tDFNi++TfbhHhnqBjf19BdNsW++jTX4p2d82/fl"
    "55sSuDVxdrTOVrvrfX5Nj7aTBnf07S+yabJ0jCZuqDzNM7O12V16/LnZ1TrLT32rHQXT1OCHntlaOvu2u/72fb4dXFB7c29XOxYG"
    "bueZraWL7T77+mdbd3wa3E690rN9NtTz6zxwNc9u9rv1t2V1zn8ObxLX80Jfnc/mBc96wf18fiY3aPP5zwFPgweqEPHV8vP9zfLq"
    "62r1hVMal1dHOrX1yzUW720M3+/20xDibr76oEsfihnC13x1KZ/x4WZfwt4GR/PI5tKr7U6R2OpwyuBsKvb7sLpbfc/v0j+osXh7"
    "qcgvjx03hYOpr5sbsXRitrLZz/1Wffh2v324//zt8LdwOc/f6JpP7IoNHqe+MR+0Vb1+dIPtPCV+WeXwV/7N4+l74H/Kx/Y70pO/"
    "ttf0ern3aYET+cF+7cPyLnsZflgPe/6Bb7hal+gXl/HS7vhye3ftwXUzmbF88Ze8zA7vF4fx9YnH3ic5tr0q3nWD2/j2VOviy968"
    "tK8H7nvTpYMnyd7eflc+2E7JkvP8MGtlZ3SCjfctHom5oI/m3IH/eP7H/9p9fhQXN7iQ5y/4cJ6Rm8c5DXzGXy51npSZ0gX1P0sv"
    "cKqZ3+ZqszHTMy1gHMa3Nv/frh8+ZSfpsdHoNTjPbW85X3/K4cGqpDPwJLViz9dXX5ffDtYsvuTbA0/87Xbz7eCzGqDntjU8X/+F"
    "XQyP8gcNmq3f9eIyexSL+5v1rX9oNqT5gtUum3R7DL9PJstT+Tqbq61vK8MckZ5v99mPOXq48aWMn3mur9t+X+aNz93GBjdTT/Y6"
    "7095Xz98P8O8A79eZZdop8E6SFs0Q/qnV/xpWuGdXhzLGOaNd/t44Ifu4Eu+/pZv/spOPslB0MfdtD8OrKdn8l+vV35QA/X6vQ6W"
    "ZxqnOfCnHhbljTRMP13I7Su5NrzUkzM+kq31yXb7+dE9jmF6ZW+ul/fZ19k9nukHTu27b/vP3/aPz87j9Obz+m5r0eX8unFqT8m9"
    "3W0//vF/PMfVHaR3NjlCWBNLNXi1em35xO23HVv+D8vd7+v7xz98mCGyFX+ZXeN1/nmsOV6tsn5vV0oDHOat6jlD9DYPS94EVver"
    "6nJ9yysJ7toqdNiZ91w9y6tj545eNgePX3TA71We4+3eEjXVO88RBFzeo6fkLwUd1+E0JRTerX63bNJ1fvdX28dfy/R6oVxkduHv"
    "148yQAEv+OiybBpr/+5+smnvtle7tT3do4/NQ/cub2hXy8V7CPd0UgN3/IxoWYwVSirOI3axXDJKzZyyvlh+3BzuLgHH91hReWGU"
    "03ENx/nzKTgh3OOcxuQ5Ga3dvUdAAf/3RAH2ty8lQXjg815kbyaP7e6PvxPOvd1lp+wqm6zym3NO6Onq/vccwuTo8Wp5/zhrOg/K"
    "yffVp2xhNtkAfS5foVG5uNSvbXNQc7vyn8qzY00sHMLhGO3ySvrMYQ3T0zP9vBFl+mGN0PM3JHe2q8dJWgIlMyzPjEHCRxW3+PlL"
    "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"
)


if __name__ == '__main__':
    map_data = load_map_data()
    total, bands, hours, countries, pota, unresolved = parse_log('log.adi', map_data)
    updated_at = datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
    html_out = build_html(total, bands, hours, countries, pota, map_data, updated_at)
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f"Generato index.html - {total} QSO totali - {len(countries)} paesi - aggiornato {updated_at}")
    if unresolved:
        print(f"Attenzione: {unresolved} QSO con paese non riconosciuto (non disegnati sulla mappa)")
