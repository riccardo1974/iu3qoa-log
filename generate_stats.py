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
  - Mappa: planisfero con evidenziati tutti i paesi collegati. Il paese viene
    ricavato dal campo DXCC (numero) e, se manca, dal campo COUNTRY (nome).

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
# Natural Earth, semplificati), pallini per i territori senza confini propri e
# la tabella DXCC (numero entita' -> codice ISO, nome). Formato: JSON + zlib + base64.
MAP_BLOB = (
    "eNpsvc2SJcd1rfkqYZj0pAIW/u+hGQgCRRBVIIQCySu29eAAyAukGJVJZWWRF3Wth/0kPWi7834DvVj7Xt/2OKfYMkkQkOcvwsN9"
    "/6619v/85B+f/EvPeXvxyS+f/Eva2/7ikx8/+Zf/+clf/mz/fPjkXz75y/3bHy4//OPukxef/DT+83XeU11S2Mqx5rTWta952da2"
    "RvuPtoa0hDXUdR9/jGsIaxz/LGuxv43/H/v4e15CW8oSxweX8XLcl7itYVvyeMcS9vHZUMdL2zL+ZfzvYn8NS0xLX8OSy9rs9fH5"
    "8Z9xCX0dP9k/fPJ/vvjkL6/Pq768/eH+cr3mON6+x3CMy7Hrs68anxqXtqQ1bkvY7IW4r3UZ1zMueo3jiuOaor0+bm683S5r7fuS"
    "7driWvq4vDb+tS/jA+Nzi11MGX8a1xztUoNdf7f/HP/Idv32jePCx7WsyW7Dfr+suy1UHT+7NNZnLGXRQgb7kjB+OOe1L9VWYSxT"
    "XPQrzf4R7a+Lrcaml4pdpb2ljVW2qxu/XpdqC2WLN36m2+v6ZLHnNt5btXb/9sVcu3+7e3v3MJeu5DxucMv5GNeodRq/bBe3ryXa"
    "wxp3Zo92LIouebM/jJsZe0Qv5TVm/f5YwKbna/8+3pbsv/t413if3XYf6zBe62MXjI8lnm9aUluyXfFY63V8WDtorM94Qx3/3D6M"
    "C6xj8UMJh335Yt84vqTZT3Bjf/pm3tif7u+eHy5v563Vuo872kM8bJnr+Nl9ZUvYg7D/CPbExpNrtlfHD9u7ku3BbUnjoWj7jvWz"
    "Z5HH01tSHi+POx7fkGxtiq1V6vZY2mpPo40zYq/H8eGysnuKPSkWRVuorrY/QrJntmtty2KHbCyQ/fz4jP3G2JbJDowOm/bFeIut"
    "yLgMu/Zsm2XsIp3QZitrn0vaHOO/ml2TfXhNmy28LXsa/6kjWFad1XEJdrR5eOMKNv1HivZurjZpRexr7MvGV1T7kF2obRH9dLBP"
    "jXfYc052geMtdh98fGzq8WZORNF5StroSXdqR67rqev8R7tGWzA7TUH7eFz5h/EcbYvGkI/N7tgWdN159Oee/tPdw92H93fHaRJi"
    "t7uINR9mC8bZi3Zq7AqCPWC7yN2Oz7iLRfZmvEUHVPt/7Ag7YEEWzvb82AOrbt93b7DtMQzbuHR7YsXOgm4l2DcHzsqwMpwJfS7Y"
    "gUg6G+NdhR8PWkN74MGubFzEsBbj9mw1mwymG9hsZjTocmzhhknq9optN9sQw0pm2Va7fj3fOlaSXZDMNJkN5ngX+7rdtpfd3TLO"
    "qV2hmeHVHpYuerGjK9NmzwGLUuzfsz0imSCZaPuw9vI4z832bNbDtuNVtfGzTNhqF2P3vdrmi/rSbPs/mvHzLx875MPr2JL9dR/m"
    "yGycbSztirH3eeKfnU/88nz/4+W0Y8OMjQVMpY5NEmxLfvhEru5/txdejBfa/2Ef/+P14w/vL8/v58f71scW6Lttl2DntfrzGQfg"
    "w3h1t6cd2xHcxppRC7Yl4ng1jLVMWxjex258PBR72f5ud7i3dNjGkrFbs/48nsuet4Nza2s1/u6XO35qexH3bbfL/eNf5uX+8cMP"
    "d3+9f/d8veHShokKKbdDPyeHYSbMPB6eynxS1AEcO3P8im1TsxjYYlkC20DmPuwP3e17M+uzmFnG+JsDNMNiRg3TZa5m3On4j6yH"
    "F2yvyD/axmnaaXbouuxYmBu1mtMdO8Y29C5rtNl12YqZKdWxsP0cbF30SdnrsenG1++8O+F47bflOKo5U7n0fRiOIOu2j/Bl2vTi"
    "5l0WM/qCyPk028Q4Vdn4sTq6HXOCi061DsL43bEtS6vjwWd7xLrQ1XYsO/KP/3Y+o6f3P7+//DofUNqSeYxhtiygsXXpdnnNFkSb"
    "P2slkvvWanGKvGuRRZeH3fGdmWAjycTY6nbZsr7Kz4//TdnsV1lwMTt/H69wiV+eYdPr+x+fHh/u3l1Dp7bbqiS7M4vsos7sNnfj"
    "eDW+iInd+Pp359dcnt79cjmO5at3n54nKJqFTVs8inZKMEN57uoYs31P0vd8O7/nm0+X8VX3l4fL7Te1upm57unQpk3XszxeGYdj"
    "61ln+atz4T998+nyp/unn+8fbr8nNpn9UA7zGvF6V+OFcTVb0Ne8PE3Cy/fX2KEVswch1cM8/mJeYtjL8zrGqy/Gq8G+4LM38ws+"
    "e3v3ZDZpeXN5+3j1RMUOZh/bIMudnt8Sy/iSzs18+938km/f3z09Py7f3f/4eH5DbWP37Wacipymhd37dVlitcvZNl3OH8/L+ePD"
    "/fPdT8ub58vz3bvl8b8vfn3Xr822eVo+qsWO1Xb7Yu612LmxLRVtT9pV61hUhZxNkcYwGu6tmxzgbvs1mLuz5aqyN0mhhVv6Igda"
    "9JKF01lRhsVRCi0ICpK2s50v82r2vfYt2Bt7kXNjMbwZKTO0FrqYObDjXBRrB/sBmQtFSOPzmMa1yuU1TNmq6Gg48dViSXOFFpjo"
    "As0omBszi8FWHicwybVHOx7akUGW0O7V9jlxWOQ6MeoK63b75qz7zvIm8v5V1lGBU5JViDPA15ua+Ut7qwWSZsO3lZCt4UTNIXok"
    "pvXKlo0o8LAV3BQ5WipQMKYEjVotc6n2jRYFdLl4RUJRUdCqw89eJ47EZClcXbJ+Rrdm37XZPlaoXBTzVwUPiqs3Hmjgcdmfgqyo"
    "/VI1P74QKGY/Dv7Eg0IYe2Sb2+Zk14tttCdU5HGx2ONJ2YmMugU7EEqLlo11Vswllxb1hKv+rFCOraMLGi5HK9xWwmadKDmtZn4m"
    "aCuae5Q7t0NhCY8imU3RbrRNXZXkNPanr4ntjd0uOtif9aCKNhYmWb+nK/JwX8FyWYgYLZ3bCDTnYbScpOgm9dXJ9xfv00bq5iq1"
    "44JuXyFvJKdaPZ3Vtts86wkWqVkSZjtkLCnBO1tiTTIFUZtDYa6toa1Q1Ymwfw7DqujYgrxkwSYBLO5M0WmxMNYebLH/SmYeYrrG"
    "suP6lGokO7BJG1BlBgsQFKaUoiceCb+jcimLeS3hHHe42yuZWDboQ4oZOPZ66uahdxyqPVY923G9u2VqZGirwmDb51EBuCWLI12y"
    "HVHt1Jl1GoFgXxQoBXtYOzlV0a4Zu9ROeCdLj0XnqpGmkYiRcG3m/e0Qcd6V3CvQUn7RdBKy7Fnm6I+nUJo9LH1YJQvZhooVjuRI"
    "FhaZbdSZXpW/jh+x4LR0S6sToYC50KCjK2OaieO1oln2ylIEC52VrJoh6t22v4VVYeam2Y66FXH6h9ehlnHf5p3NOAWVV7R+FsfJ"
    "anLS7fQHGTC7eZUF7N5IOpXgYIY3DrdtVxURsDK2ke28BnIeuwELyrvFkDpUYaGEk7E3VfHotuA6KA/Yo1D0GpWVbKyolyt2zESQ"
    "PwuZVGNnm2uLFsVrbnttR7GP7UFGHRvSvWnzZVRX7ca4zBLIIrNKVC3/pOeZF27eIjrZSVvCuFIUkwWxC7H167Z3LQxWMUyh4ngy"
    "0U+THGjmdFhZbU2Fg9/sMgM1JnlYpYxm9SKWeVNyVpRTji3HVlWQrMysuJ3G6SaLBULWgbEk095nRzTybauqBTIwluVgwsyS5N1v"
    "LNm+Nculqwlx9Udr120GwF5RCmupqvaELe1GoJMpuNiztP23KutZNrYGlRJyHt2xbHRT1ama3yZ336jzWI5T1+B5XVlVvFvdGAaV"
    "aaJZtKYftP/pq68dn7PSZVMwWBYV8ZTorlrboFVpcri4XF2kbJm8lk44ngaDKmNl6W+XNdcWt3vgqvUAbGXs6adAGr8GVk2ZsX2x"
    "Tj5GQ1s76ZFSeCh6IdvFKQtLHpvZBVdVrmxrZUUWGZuV8RX2e53/0jnEH9umCCrXkv7IiQe2sr5dxi9qaxHN2brqkNs+sN1jy6zU"
    "T3EdFaroZ9BMFXtWnj+agaybFVLNsGXtfyu1UpRqGPeN71QlYiwrO2RRHFFnXUMxWHfrl/QNUZ8z0yTzuSlpz9qxll+Ngylf3ahS"
    "yt+p9Due3WZZZV/k8KNbm4WNqyqL5YZe3NiUTNltd95hsWPURRTiRs7XMjLMEIfJ3tN+7Mqc7D0y0asO/5IpSSlSVkxGZVtuMWqj"
    "RMo5nYMViPW0KwNfF7jH+OF1tfO89+1QSGhrpjTXTraq0GlcjuU/e2uH7tlKzHI5Oo9sSwXCygH07x5GZoVYhTqBDHVTci/ruqnI"
    "Pi4gbFbC7eVQi6B7/XyN/igKPtoyNruQ8TxiP2RFuv6ZZJQtep3VPFnTNXOs0yxk2LPXj43fGLeSKk7bghI5gtW8WWnj7osSe6+0"
    "2oWqbCsP4gmLvaI0PmT70D48XdoOVfMJqYMevLyBljPKFH94vVeLnUI87NlkJVLW1/gw0q9qQd+4MGr/9oNp8wqiXMhuztbiuH0/"
    "VHO1PR6wLlWbTHejx7WPJ123Q0EY1dUoq2X2g0ByfFvvZojyuG6FVjIUiuyb+SIZcR6pGSnbk+bpYzowLMpveKH0sVlrPuyw29ku"
    "JFxRFfue7bLK2F4xu1+rGG+7n/Fdexv3o7DVfk++d2xK65/ssRx2UuviBWc9o7Kbod7qQYSsTKWNT+x2N32k6GbhzALsep7WTwj5"
    "KLK/KujLXo/vqfoe2/cLgQhFx9Y2+6ZajoC3VlqY7KDYs9s3bT7bVePZVxXjrUCp3GuY0vGMLUxqmyofgUzDdqgezPhNe347R8RO"
    "em2WrllBwGvE3e7ernq3EqIqdmNBWm/m48ZtK2IKVtWpVsSwosWZ5L/5dHl59/jpcnn4aXn+5e62/pGyBYLj2qxsQNVaMYvZyH3W"
    "DpKVR9MeVTv46g/za3/z9Ony1cNP95eH5Q8/3o1/fn/3dH5xsfuNdR9XptzbM8Tx5fNbxzvyi/GOYt/65qwbvbncPzwvv7s77h6u"
    "vbut71Zb1QlXIn5WbrfeX4xXVHz69uzyfHv//OPl/umjUk+IuzUtS7crskTwLLLYKy/GK/qSz86S0WcPP7+/P27aBc26TNsWDrmw"
    "dL2K8Uo+iytffj2/4MvL8dfDFv12wbdxFlIfx1DZqMx8VH5jYYG6QEVmVEmikmqZS6WBa6FMayXiuA/rO74oYCBVqW84x9WzdQv9"
    "2/U2x0+P2xx70K7y67Mk+fnl17eXj4tiSX2CFg9FNNcS3Xihvxgv6D5/c1YMf3P39Pb9TzfrZCakBusOqzRzU1Rr7cV4hTr7y+tG"
    "un++f/fLf1meS6pqFSqPH31V3Mel7NW+6vvP51d9//7pr++00T+/3P/4+O6jLyvNYuAtUWW7qf+PV+oLe0Wlx/PcvH58eH539/R0"
    "eb65NfPZwzpaheejcmEPYwfkaN/w+7Pl9Pu7p3d3Z7U3B7M74/4Pel3np8cL4/eHHVex8eW12Hj39PDR5804hZI5U+H2C+pY2FB0"
    "lr46H8xX7447K+q9vumBhGTWK7ZDwW6+aYIEW9EtcRG/+acK4df3Dz//9Pj25lZk4qoM+K5oo6nspRoS4bbq/Gl2BRNZ+uLexqOr"
    "ICzADBCabGJoMr6z+Wofs9xK/YQog6++Q/VIouqjlnl0VRyt5K040oo6NCcxrI3wsJKXWTgaFZv3M72m7ET9Jq8EYHYuzdmnrmPa"
    "zVXsCmuUazfS6kSdTNlusHahcAr2J3MLxK1ql9DZsijKegpJ7exF2c+myminXXL2+bOaj8VjZvoRGehCURZDCSbqinbFrd5u1J2q"
    "+kJDOlMbU4K7E2aRQylis2bnSoUwCI5h22s8581SjWSOOnik1tSG18dIjhqBrVce1cpceE7DReXN4qAorxWU22lJltkmDyyjra3e"
    "PBY3p2OslPJb4RaUtpg3z+OMLr3uByEgQVVTMavqt4YnVESqnaNkVIU7xXhjf9sVlnSoOdTMz3JxvR2b5yWbMpAoB/rZF/90Bj57"
    "uvywfPH2/smK5VdwxPiK0Ib7VhGpKgRT/cseYiNM8bxibEjLL62sRXra6ZKac1Si7zdsbShSMvXMAk2ks635x78+DSd5onHKph0V"
    "uqotVk9alFVHIlUZO1UrdEabV+XsmGrxfJmCFy8LKZsjdNRvp6CVFT3bYQvksCojs8OBAuwcb0p1wFfkjmxHKDDMVG2s8LAqPaVE"
    "31VopUesR61YUnG6gseqZqQjcHSZhpWQ4WhspuCtSiqKq3qC0bKGoIRZyWRUemIpj5ARQtCo5OoFs32Wjy3QjRyhZsWyoNp18Ywm"
    "6KkGlWhofVsirjYCBkdVWhXJVYUwi2EJZAPUojpTxw4oqxIqA5TKH0/L/8efhwu73Dxgu7cRZK8tKaP1Bae4UdW6rJvdZvI6BEXg"
    "uKvIsjuWogtpUrgXPSrKZrqppmxNiCPQSyqeqreqAnykT/j961tX+/bu4eOGc1aK19KRMg9FtRIVk7WbVVXqajdnQQeUGSWlaZUr"
    "sMJWUV+JLmtQrzYpN86qoVqD1j7TLUqt2ORChhdUXjQQwkKaZHa+qwCnDRyVfG3Cc2UaKNpJwkpoW6v+aFthV5GYQnkgy86Z98j3"
    "Upnx8qRuMOJaKHKbza7Ya+BLNE/sy+g/FW/12C82ldDjBo5GbxYsjjos8fz3392u/DUqKEFrXtsRAX0llSL0ldq6ery7PHBS31cL"
    "G71wx4JXsstA/38H42EP0BoXdteURDu9ZvAcga6FeTt7RYmNilQrEQGNDhJCcDEqIdhBDsqSzakn6xSps61OjpoktPGbtwa8lLaC"
    "JaNWaF9njduzs2ZXlAnJ9JJuwG4Lp6T8PHuprRORqCETvfofZqxBFSv6YY9ULc2PgzJcdcYtHMiVGpF9idURLKxSFVUdUtX6Ft19"
    "tE4oOBZt5hG7566CeClH9eO2UyQMHnEIYbQETo5297aSs1P6F6THba7dZWGHfHPdIeNc3mAfs6WJZU+HqrhRl5zmIdKPzNZRkHHV"
    "gmUdCcf1yUgGgVq8EUK7gx0dzGHJuxftqSaAIo3dnXOh487qNCzPuMkU1YEJwuMsyod1aLid78/bebp/uP/p8pMC++8ff7j8fO17"
    "txExxChYpzaEp6+bGov2yK4huqFmYlCQ//2ZxX7/+PDzuVBhH899GwEGJd4TcRP2/iJt5D3fv7x+9HodOeZgoCSlqOYvMKTUB60+"
    "V2QOdj9IDmzRRkxqM0QKsG2doI+AZZqL8er81fu3j0/rq7t3z2cE0EK2A22JQVRZSgbeHDRF9khR9MN4oz24VrYjr/Qix247EQsj"
    "AXkxMi4lEd+fCfn3v1zuLYs9IZNlszRqBGlqOihgIbKrYHYLMACVFPvqJVJVxs2mKobtdPeFEFMJWNYoysbb3jdXJuyKWa0GWilu"
    "8nSGNrA+hhkglkz4NyFu7NyvhNwWh0Tl0pvskrdR1I4Gjmv/F+UaFGYsCk9D5tiqXqXYXgdQ7ta7wPplRRjJn6TKbdiYIL+SAD7J"
    "dI1bkLUDWWnmTm3GqlBH3XNFRbvykEpg1M0mxuhxrzqSVkKxZuMqqPHsoxEZfn9CwL6/PHy4PNzfRg4Gcyr7yPboY8np6YbGzQWH"
    "FOkoV2BWAgutdO3M3Heh0ja6u/JiQTiwKBferG/RxyprE4w93LXswf5F1WUBDiuBELGoUh87GnipQGekK15TCKjWacfh0iXcV/6g"
    "AFItoA2sOcvzYfhAOwC1hENYiGbJQhmJ8vhb3FXvAdVoXoIl+/11yf79/p9Rc5tVHK34FuT/+Eb7sJ6dJYeeYcqX6sRFnaWk6wPP"
    "ssr0Kchn422CY1nyKBvQafurrLrQbNtkGBXG0r9NQsR2AmFVh/IZGUUZW5lMbXjLtXUaEytVPILG4zmW3BoXhN7RNlijl7jNwrg8"
    "7O4Qbc+9K6Bvlu3P12W7/8d1yereLRbu4SAN6BxF8D7Jwl25QOXEZ1lxfCi8CL2oHvXmrEe9+fXpdgNvBqANZpGjElxFCrqkjqVp"
    "IMXVx5x0ADM35Cpltm63pc6mzgiS+zDwVKpn+53e57UkAM5BCAsh7XT/n1/LlP+4f/5w93RrGHNWHrZZNklcW7z3EYU2or0uu69e"
    "kxqk9APc6+pCwcmoRbmB5c7OcTD7uNMS19W8+eJ6NXc/3d3gXEfEsW/9UFlAffSu6C6rqtIAIpv1lPEjnSjgCWXcFPcoD4x+/kMC"
    "emgFizq7rwJ10EFWFSBQ8ZhI88T9C+dVleKB2ibidPSMtttCzVNIhS5ElLacNqCdISE9Vb+JDrfKqq4Utfi8lWLRyA7iPi8Ox6M1"
    "u4Cr7bL9ZrV2VVMKSKUlg33WXpEDIi+Ly4nj8B5FgYciWJG3zPHxuz3OSN8/eOp6/mwEckBxJasdlR0WG8i0BX5N6rWO2LDsI51L"
    "/fAOe9dji6ChbK1l3HLJVumwaAOMSFRhiG1xuoO7N/+4PI/Q6cqByeO64haPqAoDwINM+L1jV/249LMsuKf0IsXQdUrPHOTN+xGT"
    "Xd6eIUjci+WIRXWenSJVxNhj+9K2enFOudFK7Ni8XCTnVJwrlIg9tWYWiAmH5GE35aYsyIYgd+ZlSE3f3DY83rz/6caib5Y4Gg56"
    "+LwlN6goAluoSyjPy0Exh2x5dKCDDtqkqHctuM8KQm86J3Pk4gopTFB6o7Vc1NCMjs5ICxedqOiLHrSBOiRRdwvZvUumY66KqQVA"
    "+uvmcAYFynnz925uBc30AQ1SqiC/G+Ul7Pz48vz2+uw+WhsLCWMabrKQ1naCKquvkJCCPytCeMqZNassJPWgPACDltK9uboouduU"
    "pNg7tXSkuQp0obGASLJUHExVIDRRJLKvjsYArxHBdoO1Vz2Jmq6MlAIi+a+quo2ZHLM0SaVO+cjxKIq64L4h7d9Vxa1CfkfHWal4"
    "p/qP1XQiZszBAUbvIV4PXhuJuNoCZlVr/Ors/bx5ul9eXR7+enqyunX7pbQdYE3g+agWpo1RdCJxul5mUO+zkaRDEhIyQb/0xXWz"
    "/+1yf1Pe71YMCPXoQjOpsLhP0IYH5ToyHeCG7BO+pXp1EHKClZE3AGKdAovAAZEuvg5FEA8mq4bVCW0UHGErs2iBXvXXotEX0EKr"
    "SK+qjNhLC5UY6g+EyAuoPSFn7Pgl4VP3WTzehSwNAAfgKKi8Vj3sl/eNAol0Ei+AsMN0xm5YgpCPJhsCfaqrIrF9eJ16sR5+sLBR"
    "NXZ1xdO+Wa3fOpC6RkfPWrs69WbrYCVyxZlVubqd6mKfE+tixASCSQalyyNgzUne3nhnuhPK5/ZldufN0lmZB2CgeuJfX23v4/vn"
    "X5avH5/uLjcBmD3c2g+5+UiZfzdLkYkpvb6nRJ3idKXwD+a0roBiqndYugCqwJEKmEmMUFY24GAAod0AcRczjl1RttMjVNEfsbSt"
    "onWtzUt5cSie1Ii/fPbxXX3232/h57nvhle24rrSy/E5MX0SSEEvE2MIVXBRRCFao8IGESG0GYu8s6rqVsXbLWMxGFSnBmslZvXZ"
    "g2yd6tHAipU6dFLQTtMprzRAolZJMBrl3XOvxzNrjArskipnGfpiAieoemdwvmhRI8gB6Y51FNwAVhXWpgAOigrQzFHaltF9dxie"
    "Qp8GAf+EVAvB76YrVKMequrT2OHJbITKdZj7StCuvpqtWoWx0084wZs/XB/U28txE6IHIz6VbBRK0Lvjt7TPUnHAtr7UEuClDguh"
    "FCZZSjuWBHw2tiRQNhcPUbFjoM1pjw3gVhP8KtvjHJFMKQaWiTQ7gv1cHrdXUlUlJowgJ4vslsRkM6KrnI16EuaVt2n+IMyIainX"
    "4FhzCJyBbtCb31zv/3h8+/hRn7rtVmZoeRw/tQVEW46EC4KntL2N59iiMV+6J3PZa9iOOw7V3lbMI5mZmcBgAI8QJfVF3RgKRhjr"
    "cOI2Jc2GBRlnJdaeDFlAxGJfsNtnNv24da2VfuwODbDv6/o+4/bQTXWDM7k9ZX8RG8S4N1fndjz+/fLXm/pi7bbnajWYEhVFlW4C"
    "dERam4B8RCKJaXWsb9FpABcWnEQsWlJR5gsOvQhpzVP46vYa7m5KHbkYiGoEeYc8SVwmpUROSchlZ34Aa6VUtToePIFWlQ/Ugxca"
    "O67g5m7YTrmkkbTGLEbOm7MU+Ob+4efL34ZFvhKLjdKTq3BB0fuvZy1yvJpfxAzi5M2r67cY2mB5dfd47e6lvVsrwNZWHHkxqFbo"
    "z5tnD9512MknVVbKXriuRPhWG21UCkKnasfKyuWJGh/7fngHA4fz5kRVvLn79cdf7o7jputZLLCsY0uJmXiD6hkvvBgvqMr63TVI"
    "uXu65eKLrBRH+iIknFnR4kjWIl6lkxMrgBfFvAE2EF6ne96u9ByifhMKr6plQzhOGaTJazVMtIK1oA4mP+JI50CpalcrfvJI33xz"
    "vfqHu58vx/WRWN5h+C71/z19xazrazdf8kRfRFiCbfVCkT8bXRBw2+g8+V2XWhYvbRoiHrR5MYa2ivRV6aSgDuAgAJdbEKGUg6aA"
    "mFlyhBTfhCEl6Ny8Ms8dXp3v5f1P92pw3xh21TPAgLbJWlZwFYFYqG6U1MPFQYpGo3Skk6olRfL5SvkwU7XxvJy33rkj+Qjdpt66"
    "O1ykeJdpbOlM301uJU6yVKdIm1Z4LJH1pbVj1jFLM6KOAz8eTaLKq2xssjqNwrZDsaFIKORDUj0pOao1qjw9Nljg8YLKLsb5DLvw"
    "QPEIoDiIR0eGruU9Gxhv/vP/fly+f3z7n/9LLYxvR+784/3frnoaybzD8MuAcsK18TBeKcNQ7NTIXl8f14NYkQ+PN9xmu2YDp0UA"
    "2Tfk5vJivCJcz5+vJ/Ij/qGFSr1Gw12o7iTfYHDj2IFTKMOi+302VEJ8MT4kBNafrrbi2XiWD6ANXz7dPdyAuXar/CYVLVSkvGnN"
    "NONK6qteff4xFPDV+x/vbyj7mx2LkD3YTtelGi+l8SVBNvXrb26v5+v752dQYd/c/f3+3fWCmj0987bF8WXx5vZaMyJp1EV9dxY+"
    "v/vHbWs+7+aey/A61W0HRLUEikfYdsFoNxr+eYm+voXkVx0CVfquD2yP4UUs1EW/O6mn371/d8vJ3VQ7z/XwThFMcx2zZoUwUXLM"
    "ZTTI2bC4soO5V6La6r1rsf2TV5cWKjVqJevCrTGpxC5GN7nQsEGbONZjbPpxMy7+kHX2FfEi8hABlyrEKt5LsNS6Ld4RUyOE3goM"
    "Ba5MybjdU3eik1HEi6rwSlIwECJpKVsBn2X+n1tTdznry/wvgmPI5AdI0jCy6O+o2m2pQ9zo6Ui7hJ6H8JlaBuFZMrkewKzdw2wX"
    "JFimrQtQMqEFeSJc6K3yvxW6tzZIdsKeNBZIIUnMrN09ssZiPAchtzJGFtu5o9eQFgIaZdJtobZcvQ3fod1lvZXVWBI1mjjtbCcO"
    "iuoxK9uyLxFlhcbM+OLm5QlvQagsWaEBLrDkwhKc8iugXMCWkuqszlJX1g6FJfZJ8VBzXm1beF20K/gv/WqcjbdAR1o8nQZRqxEH"
    "iBgfF7/+hhtSuUEaHhs03w28AwGmJ1nTMez0pUQGUaXNPqCyVr3WjCuZ8eK5ruINCByFVoyYCruSNRVRom7Hz/nuZUPdtENYQEsm"
    "EFPRiZFB7gxoCjIt5vxUhMzGR1T0ChJfdWKFvGBt5F6hd6kvRXtPkC+IyEp5VbbewJJuQuXQthQuS91XO8uJs4zQCPwyoALOo+QO"
    "MmTWK72CkgCkrqZqrnllAc4SMClhzeFaBqoKZYUfRY28Yy2VlzhhV60LIT1VUtQabatn+06cFkQRc5a9uJMoX0RnTgnZwy7f9IsJ"
    "0apk6hC5edXR2QzoAaVJBwcuVzCjwYnciscT1bToPVadw+pbXiQaJeXZ9z2lJ6nhTCUGZWxgRLA1tt4i1aiKkYGTNNV0hCnRKlqz"
    "ZkGISF+bXBDKgeWL19dEVhyh9UbrvGpNjQlKqVGRb4FHnv3hRGAc7vWrVUyzoC27kksesHYEm4zy8QgApZWTiUadfCu1IfYkGaE1"
    "PYU5oeUp7rUaVdPDmAdQXyerUrJ7izi5uBUJQiTELV6pEcQJWKUqPpz0MvcSzW05euSXotPqKx0bQ73qDtrqwWDU5RUPqrNyFTn5"
    "xQF0yuycMCR4bNy8PKNwcbhhFZkxrxJySf6vWV2PQhci+idhQHVXEBBjEwY2ICKLezu8QtVnwHc5frEI87WJUEf2fNKvtTS76r7q"
    "nmeHmaD3BFBNdL1dDTwXh9ocgOLF9yDnE6DhUcNZ4PV0/X8zfNHjhUKrSvsDn5Ucxl3kkGFLba5wko3lbdTk2UrcIA12nvUm9GR1"
    "yHhwmSCws0bqW9Qu7E4a3WbPsnjLLTruIHuED6YprNMa1FNNQNV3kbS9Z9tWkHGisst4VwmqFRdBC0r6QHmgBODNE63UzmbGjtPI"
    "2dyUy3aNx6EqQ0U4xKvWipQ6kDravgW6aUblS9VB7Ke85wZRNCn76A4rAmdhR9rCkoIN212uJokHmARoF4JRHSlhPtgyzrXVotlG"
    "iF7RSnSutYfRdVpA6ibgaKozxpkfJcnPkLHaxWSXz1H9YV62ToC6qTAfrRy0A5tqQosJi9PRIUjqtJRlttfrNHAxTjmJAFIPYmPl"
    "GBsUpTo4E04gSaxzswnNFYgrllIApwZ4jpMSKzwfqI/E0ofVW7kw0UD3uyxJx9eEBd0qA6P6junayNUDaLkh+tRWhpJYRTOgWOZG"
    "ZMamTp8IamVbcBmVJ5zQ/9lkkJuTEdDKc30OqRwo8sY/JcKUSkgjhqoWJIHfK0Ae2SQosyn7RcOwyWLa/68TCVVc7XGT0lkjgtqn"
    "RcyCC4A1ozuwoZfkTkon1mXP4gJO16kXqkbOdutmdhRkR/WAfJPkk3ZxBqicgIxq12C7oI066tYIzKyjAC4qu9gm5fBpneV93Z7Q"
    "WJJZLBbMFRGW8R8i1Qt/E10UjsYg9occxq3uuBq1TVf6L5HGeMZDI+3nVmvD5Gn5FQOVho7IkkVjkVdN9A1VF50ANEuKKJosjuBp"
    "rJJqUGpvVic7U3EujrzefR/HxGmyzR3dFnrsLnMgI9qpjQoB0p0toBgxLDws6MiqyPBok9DUye0VGQ8CJJsaTWpzKq6UvQc4qx5R"
    "dJkqCNyVriVhibddy5TX6SruArjPIBBFEl1PvHLFEwI2a47W2xTEwEBq7uM59Zt5jU1OSbFbdT09fOEsGzYSIgE9BSZ3XB5EvaDk"
    "hJoXFWSB3F13x/HeKqASQ+2WcGBfadpE2kguiGouK2WdOSBNyIN4CxXT06bgl0LkDX25AsYCGMOsMlKiUgZTwBYrAbCfU7i6uKjY"
    "grXzSBbLmqa8mnkkcVhMUgzSimhdu2PdBGXq6s2IOgwx2onNekiyx0rcdle7UTAg4xVcNQj2uLl6DleHEyZXMTLTiCCCuBQJKxxm"
    "2ArfQb/jSpESJhTvXs4m8W/em1J8iHYGmgDKKwgUlGOu1aFaG5ghccZNgLQegHoU7CTHd5CitzU697/SW0WLVbHY7rIryXUny8Ii"
    "4BAqVV8OLjJErFxzWHtwxKByZTklJPBUMhf+QuUoShIRMSYgpkVxTaI96jKTCcVFbdG5kuCQ539UF+hUonqVIIGRJycekQylGyUQ"
    "5+5IGcrDaJ3SH8I8V9+UoPoq2KPuzPIsiYGSzONZXTRswo0Q9Bf6vhQ8BM1RVWdDj1AAU51vV1+yL+xnaUOWGi2Q5CCExVu/YHYC"
    "mnoAq5ZJbgLeHwTBC36ohbuxr7aqOkH5vqJbmfE7s/Ruptn6e1tLsC+T9HeExl7qbv8b/OcKUBn1YeWNdiUmrr8JjpokE8qaNwqz"
    "eszBwcPSPjL3KbUqNVABUufJWSEy34STtcQuH2mb3aIKDQHFTcWI3cUSvYfvJCwQjsVrMS4HlLWHHQgllZk4+V0ZIpB3qaJHMapi"
    "7BJQNG8aD0W/mAOg49o2rrYhrxRlM+Wm5UpU9ynLLJZ0ml9SVxZFY0XMw6qE099/eF2LQbJ6PwQOg+OiqKO689kW2ijIbDRuFiGt"
    "hLOujuPcdVTRWJMDdXivLwD6XmhjSMtHSmhcmBYRZDXqISq9lybwSTHcg10P1U/Oe6GXuIPAqfKzrpVWUX4lX/NI1hXNxnf2ajLE"
    "8dhcE2gj2He2gpi5PH1pUDdHQBDWRs8KCyGKJcJxZq+NhAPRORmyD8htW59UTIO4AXoLIgRHVLJ2x78H1rcLdlWUATuaRA7ZaJr7"
    "bs++H5G7dGgD0lREQRuRkmSFplWiyqssbPGShyCkQdoJtbbhhmM4IqJ3Sp5Bi4qzK6+eHY0l3ARSD1s+KDFE35nSvcquf4JccOKi"
    "4PjZT41P5laO2L0JZ5t/vxLjZOu2Zs8iHdqjMThcu9uFeOmpmLBGMZKKLQa1neQIgEz5tk4cVSIrVFNd3mpE0KVUuwTvdSWK73aB"
    "JQpQbXa2CPJe2WYBmA/CNkl/F9rewsVkcAK4DpViLyfCuRK2oLIudmbzJi+JRwdpBknRldBcGwriRZD0STFl7pjKgYw8sYuTrQ0A"
    "u1f773bITBb44I3jCalCRtS+yPBedRvvdBoSdLDNWWP2vA01EqzZpb4SFQRtVSywTpWpbaRiGsa7oEy765zb7dmBzcOKFLXfOn5U"
    "ltQEQuybcxHh3h5po1tgMZr/bKimoROydzOyczBMdSRaxmPMXtgg8IMlUavuo2IHQ/Oq3+w1HR32ca3mT6rdUHelG9dnb+AgKBsX"
    "XcVW7eY3JxATGGNzzW6UOlxfCodDDuRtJWttRtTEWnKLx+otYFr348m3vI0NZsASq854XT/o52qxBCMeEOsoZmkbhp60Gg5cQi+K"
    "hrhdRx9HIMx2JDhQSxHsK7NpTjQTnNs9sEDJzx5blttIOrewbDwA2kwgppiB2wwMpXiX8qiejKUj++GNfMeDjE8MX7lkwwc2Z+sA"
    "IrCdZsyo1A4vnCVgW/bKlsRSO6BWNFfosMckwEtvR0fqnANQVz3ePB7zWCZ0lagIaZVMsT9uxzzxQurZGpjM6fh5s+5CwPuDSEJb"
    "2A508UcVtorWxgjw1VqycfNrW2j+2Rf2bZzWInFi2kR2Ag00VAQu3oatkn2xKqJdcI8zWnMQnayIPbkRvRVthW0WuTN4VFPuqRZB"
    "tcN7UvgxfWovLHRwWIrDk9Qsk/8eB6v2wztsMqKGLMlpP4i+dEo24QDtQarCoD9JCUTaNAmklMSCqmUztk7Jq1o6sLay40ra1iXe"
    "DY8h4EK6FWYdKqroCvGj8egs9ktuvODajffb746ncZSJUExyzJuUGxsiPqRsSBEN62ugdYVDZL22Xtm6SulYoccL6Cq8wXcnRO+7"
    "x7e3NLDclRiVfihigpKv4jvVeGqXip9EImemAAAaK4QU78S4jmpRy6QD2u8qGGfXxw3I656zDGRKpL3pRcNN+VFFhDKuoOGshms7"
    "FsX+fz1RKf96eb48nXCUZLjdHpubaEnM5onid+jyibAa784vQt9EW/j2BGJ8+/j0/P4GypM3K1slU8WSA1VRBExOh3lTncnQ6Yx4"
    "acl7IoINSyeXzDOcJGr1IvZlqm6s4G/lLekyVFc32IWUQTsFIHQMi3fT4rAQqRa7BBOekjdHwdaQwsYtqFs84FwqXNL6ffvqercf"
    "8ZMkYTWyjyNEZyhLJLKCpYmFLjnZ3oqLynLpO11jBdNNCafkdsnpVL/ZXT4lAohF2nJx+PdOubV5MQ+ycQeJ1VxTDEEJYTV3BOIV"
    "HmWo3tJMqC6Nu9QyleSVjiGVzBMJDsT/9iRqffvL/XH/t7/dP1zBa21Tn2EPB0TQNTsbMdA5idVzWw+NU/TyGfVkZOUrCQoVTYnL"
    "FLrI4qYsLniaEOotcOiDs/4dbmTgVCVrgI8bJ9B9n9RHF+8ahonTSGKUQJVWm9aObszG7DUwbRxeGn+UZgV49/ZaPWEPPOe+Enar"
    "geRLi1QcYqHS5IV94Z15+ppIQ0u7ozuhvrpaAS2tWB3i4VIGjKABR5AhtIWZvyfawwueyFykScKBCMiEWJ0ik9dzNLREZT67ZStX"
    "j+z16MvZM+AiafJAos7erNZvSMa05SN6c9OHuTRXRFT+ZqKsFhiYunvMRdJxEYxZkvqp5tlMaSOFgvYANivoWcCg3qaPO0iUFDTU"
    "wK7YQsowUs6OMiIZPSRYz54kzU8QL2AlKkTjwNnHN1tnmwoRvMKQhE5TkUlf39kD3ulYZ6ZUucJuRcqRVNI3RP6Sp93FDbdTYHEF"
    "ZSjQ9fqcxRWhIjwnJZ4mYrHFcJRfVdyxPxvn1hYBZyLhYvvqYjm7me7iEPjNXPN4u1T8d8Xm0ZVnOMAnt/Hbu6f3Vwkvu5QaAsFC"
    "B4QAYl5mM2ZwFqhbbNMsoKwTIcRUe4xlmV1oDHx0Qof5Zcu5C730HGdaQlE6IdVMgVvfUeGMC1CswGtfuyu1OxIoOcZj7OVmxfQo"
    "6i2GnhqxBLKJsGgCjzhFZeUcJ1aSejY9RrR9nYek35TCLkKiUwIzONMsea1YFi3Bn1RCE7sLJIOtaouLooEQcKlVtfDwgZ1BLbyP"
    "IpwDKc8a++YtYcQ4BF7lYZ7k3m8vT5fbARgjNwsWzJisotlZkY6kN4k+IvIQ6K+K7ofph2Ji2WB1/Yo2+3myYBbhl00Fx0JFPMxs"
    "XBpCFtIYFV+pEICchK5vCutUUCqiHGwoYek2Xl5v42/vL8s3d/9YXr4fnuWKyiv2UFrOhyRrmU+Qkncl6kz+xcMR90EuJrtGAqhU"
    "ldQXpGfVMFL7UliQzcGrxRt0dQ5viQuMci9L5eLQOEiU7nhjdnmlneQbHVevktCnTY4okoOheFmUkxTPItU2qLLXrekoboc6bY3G"
    "q4C4HiWhDk3bH+0HgTp4UimR0mTvWTWcitLxaLSEau0RI7hWVwI45yxtPr1NFqQbtaEG5XbyuJ5C6/5TYYQRg7tQXDNzVIsVwoar"
    "0RQrMxx2P+ZNTBpDIQ0z2ezP0hyqFvt7Z5J45HytiXQVlaoCQLFcsLV9PLyRQB3hqok63mr2xzKqAi7cfCB767Pr3nq4vL0CXk1R"
    "KY47PKhmo6hC6WQFAy0bgM5TAwEALgX+o8ftc+GAXjYigwiiQWumgq6gLyuqSGsk1WnOihXXO5MT0MFjCpLqKb6z09T4ZbKG6mIE"
    "9d/++Xp/x+U06C1ZTTLu5wwVsUxP+kmq7cV4VdDlb7++fsM/CTbsW0YkQI0lR1gpZtgccBZne6idpW21rBYutGl0UfPOeHa1firW"
    "VRMRdrW5wCN2gSKgTE59nui+fM7JaqftMlNInFypMQvLkTnrDFYA6zXpz3QopzfYXAt6Q65J0cfi9XXnR41vAzCENNPuTDDmxyGz"
    "13wamPGKJUwGAZyqesan2MHeXeI7+EQJVwA7Zaya84o8WZlqWLv8CKAf7a8JbKwzNUJAMeIsAlruThOUBps2yR9OgPsf3l7+q/GD"
    "BtAdG68hA21WXL++UqeMUK5ZZ9jGSCtWBk5ZULBfG/hyWWZurHC30ojPiK24YIwL5XfHcGf/t6iyxan7B98I4KNVAkuzNp/l7dGp"
    "fBZp6ga/OTP0bx6f/nF1g9lKHdUqVMrLNE8AGTQdiuRC7m3GxZCt++KdQrUt6U9Rg4YeJN+R3Kkk50pujuBQ1RsIoSxGn2LZeZ0S"
    "INk1DGZtVW3f5cwB8xx8QxRCBplmoU/QweTRa3K8qeOmnRW2e8OQphsK4Srl7si+BGZ/OgJNjYe0ulCmmuTI+mcfqLlJj2FNDuZH"
    "RwaNPFBmwO2ryrtV1hfJKIl+YMjqjGYC4qjbnGgWXU8JHTcdR3KGfM4Iq8rluzPMHJgbmGeAqQeH6fAsWfA028YrcVV2OTW1IgV4"
    "BA8njXoQMQ4XWpAe371bLW/AYIQG/0MSKLyp80mIhsivytoJSMsQHvVHVya37Ax5JMStMydkShFEauntM+JxShFO1anuAUWc2qdp"
    "ddwOneTi4OMARdkHTThDPK0+44aW3+bq8MnvAZUkDihCOBXkKJ7I+3TnYIPsUK2lrDO8UgRFMKKOnsuxuu6jgAqBdLjhFFxNpE+F"
    "fYrcPpIHddbdtxpzEuKsfXlqIsSSfIkL8Hg9Bdi4mhTSux9GTvnm0ZDTqhN7W2a3S6UyJ30qI1FDUl3/c3ABvTExO7pzKgMYeGe1"
    "duA0G1J92SQeYkN/zIfeMdMjozNtNNuK3BOkZbp3MSngpqU6hww4sbK5CjyY++qBShSCMKtM1RC5sTlUaP5JwfUc4bMJm08kvyFw"
    "u8BuozKyFnJrFDnTVLaV8hkEXo8+XH1QRJMkMGgSSln6KUbY3RjW6NRfKJSauLBelWlsD0apglXsI2UCkCqimDszHPh7IfSKNLiL"
    "dmKYIImEPlQXUxMVTmkyal3iCi4EOUNJvFgVLByRiwrejUd6qlmiNBG0FRbNVI/ToCpnGU4+hCs5baIZZ6vH19yPjnogeKjkRang"
    "45F382a52J9DO3af4Yb61ZzexiiqqI7vcHxL2e2du482ZQOa5vvY3ptJMZRDcla4FMIbkc05AGPbjkywLT7LS72DXMfTKz4NQOgK"
    "W1P7e7PEiHKLvJDeOz5oav8+pVKSwn2cRWtQQZLfFZ7n4XGXStlXaFDbE7WOG5D4n0s3cwFFjPgCkVeHeSVm//rbG2/+z4oMFBlz"
    "dk5fdGpnduGbjPztaeyTx9w+xxFhoITBlfcNPunXu908Jwynq5HJq8cFIoXPS9vncLdOiF8QcOlzQmkGhujQp90zg3Mq5DdnxvvN"
    "/c93T7ds6ySsRj4A1kGd2YA4NRLoxiCx5NPRFk0nUME+IeaF9rFAGuQt3Q2IyAoRUcQsMkrwkRybY4sYl8bY2OSVdtfeCD4fGciu"
    "m4fswGjoG+o9QY5GG03dqqg0YXU2Fw2aptODns2JUcKHhz7pHRslyt3j8Qx5vKxTo6yA1V9F1ZCSIVeL2oOiEBvbDRmOUsM3X3y0"
    "8P//ZWeilCqk0SVV5/x04r1tvSkz7bMa0Bm042oW8cwmA7oSK9BtVOD6HK/h9BjO88bvyEDneYQnY6uBCTUeDYPQ0DLVjPEkzZBO"
    "AdvYglbOAfZEaKsypRByKWI1h0mTqlaiVgar9puvrkvzI+WkM1ke5pJ6ohy+p8eqdCl10wbzqb3qTjhEHNi7JGrSlXxHjmWmeTjJ"
    "wuAhcGazluQwBxEyomTaucJTgMsqRH+5u9x2YZradzXUI6Z1dySgSjEypjuKxK4PXasVI1UM5n6m4Pbmc9DovXnZfTc5jHGtGb+s"
    "aMdpBxKF7iIZMbjP4VHMA0emIlCula+akYAD3VfJKvZpJ9T8YXKXNwM0vHGpUcpLYOklkrtocFHfTHcs56pCiVN+yhTIZxvqjPt+"
    "pMCw0iHYsJ6gTyKSLmQ4EfrFbspMzjhRU9AKXcZcXunpbD7gMPkIrZiAiATGBoSKEcXinGGlYkTtkOyZwQZ8grSnO9AX2m+g5Koj"
    "t2AXyinFmhi0rUTe60wJrVbvgERw047fGh6njb9X493PGWNRcsL4HgMx4g7cRv/xeh7eX2UjtsK8aQh/+ToEpLxIPtb287Oi8vnj"
    "419v9UxKsRaznObHkzLGCyaEK3WHb15dt/nzL2ghvrtS2qU7ZJCHU32PWgTjuxwe0BYnbwZXi6fsEggsUYKRj0gaK1td8tJBP34G"
    "1Q/NadMonHJMJqlYaSj5n8Wnz57e/3AzddcUUzQRhkkE8SP+d9nDC2svaanOb/j8/dPlP/+fy83gXfV9qvTTTrzvdeyuDbkJVZq6"
    "31zjhbu/XXvQNaqnkAzRhfJOIAUHX1KQ44ouPLQvLo9X18mUang4FP6FW06odyP3uCRmdHjxPs2xbTkgwqhzuHuxXw8cRAvVsejz"
    "J3yovdvgU4vqm8v7a3umB2v0F6sJfzytZbwwlmG8oGX47Prht/cfyYLshnUd8dvu5E3N3fR8Qa46mSFWw3bb8CzWga8gYfCGCdKh"
    "q4I356lXlzjqrjkhhK8cp8VLWRKMmZongZ+os8RZtEYZuEX9fpbiaW+8/st1YsyHy9sf7v/jeg7zbgU325axezoDAUme+MyFsstn"
    "0fqMG6TSsZXoyF/liJOrTZ7PLFRyAlkf5kdq5OiiXRDylDySI0/MFxKAvnvIGEj58+LRF91jzL3QTU7g2OGTOd1Y2bu7DzlFiI8R"
    "HAzybYK2eaOSySh6NlMCS1kx421jgESYRfCYuAnUS2hwkcacKp9tPUdVQd6m6hMFW1HoI9dAWfH1Z9fn8/T443VoNlNsSg4HzAXD"
    "1EJodBi6q++1WUyU+ZemIZGF5AEWH2FsYWzyefJ5ci0UADm2eHE5A6ot++SFb56qJ8HqkpJt+0xkXh+qsPpYSj6mGCkzwNPRWaK2"
    "MoLvBMZ/7i4LOtn20YmpoS+Tjx6k4qjHtpYNQsTGpD1wzBtB9bDEiA6eqIo/f7q8ufwyoq8bII0lAjkfyuSNftsqcwH39cRQqtq8"
    "rTtVb5LnZvwqNfWMaKjwMKmOFk7ZZLsxL0Qimo10JLhPSpY86C9uRzeZaM/T9VlXq46nkI5YGdRCuF8n0D86iqydKEn23Xoac0tF"
    "XwwTx5iob25+6+fHG0G0Ksk7Q/JCE6co5iMRNN18gdpTmDQE01LZW3ZFoswUH3QaHK6LqwTeP+HPmnfsgPVMM4OuYZ0cLp8Bu0Of"
    "wmLAFDGEQq540coIy92LVE2omo2uHNzyRGubXgS16ewac1TwFbgpzIKBRRt4m/whMVCUcZBceb+9YeGjC61btLXxNmq/zcdhMNlM"
    "sqpSQQhzKiuRrcYJoSgkgu3ucwuiZFSRPlCmn1RzK5J35kxkb41ai6SgPgtRfWPiDRvrt9eHffz0+PfrtjcJmRB6O2SrGIIbSarL"
    "BJFBLYxldSRCB2Uffc6xLb3lHCa3cm61PuKGMKIPbbXPb7ba5TRfV4mgZvo+0mh7/d/Ot979j/urpQtVFmLEg4U6bTHp9iRppI1h"
    "1EnaF6IYql8KxX73jiEPH028ABmV8eCCHcsuWhlAjQjVfIPPiy1gutVcWxm13Kk3NpdZAmYN488bY1DyBDHuU8ZBfRGpyqPY4MOA"
    "AwOHNdFXLLxOTK2EprqAgqRJDO2/VB84lRxA0QEtoqrWMF2ms7oxjmSHs6nSgCpk6PEFlR5gNe4i6vmUaJ3o5rW91QVuVefPdHOU"
    "RmrsQER9PyBbhTxWBHzpIg2uISPNkOjNG+GtcBRUTMBkQ0rhOiYV81pCSme6rqYFlI0NmLpKwivoPChaE2zWfP6u6iveTMyRHCf7"
    "e5inUr3EInkM5tjCHSVpFXQkUlpvCBg4WXR1bjTCBpFRn/LnUPXcUCr+Uh9zkzjzFEIhqQjnJStZc9qNMt8VAq1qs8FnLSYKU2j7"
    "oGgi6OFOFSUxDs5mcO62pw3STytEubfmkxqJq9nQTRbM4EDN/m4c3R7VEWxQRPOUWnt9ZmmvR8R8/3z//kZLz7JjG0zmLGhRceo1"
    "5cp55FyZ8/3dx19zi/JNu1HFmMknBZk5YSjOAHCKSgh8LqFddBgWBxNAe7RdKSQ8hNHdMylomQDXLSsYDkulFE0UH0fKyiR+WsRg"
    "YSby2l3/Ts427lNrNbEX6XCwQt9fb+14vqk02i+XqGwYoZH4kRxjf2Gtfy3Oq5tvuL8ui0VSIwU7Et0XpA5U5wveR2+e1VP15Wgz"
    "VgESa/Axg8VmXWyLL5yP6ZDKrq2OWcp6pk/J2eKJkUVtDhQyA9c2IAQgOcLsijhfDf/mk6fC6h199rDTngNtpK7GiKoIVEnmiCRX"
    "2GI8AkHHenISvChBLwimFBpD4k71E0CzeIq5M1JJ4eBCbWMSjrqfMn+Ef7p5AD/d//1GL3LPVnjp4UBk7TqV1F55MV4RxuP1v918"
    "weXXG72zujeDd/d00ANP2zmTxOyGLIzXVNtC056JBwz4DRXq8OawBXj3og0qz4qO3k2otHnH2IcN2HmkkCjRtECkw4Bo5lU3pl9l"
    "73ASsxRv0zqwa1c2AW4NUbT5sPJVdkPDlVWZjYTEixslz/filG8xhGqp5jxjOGCe+vyqxAg+zJLT0BzgLD1J2yVmpXegwUk5MlUV"
    "yk3VBNNSdVJids2t4o/4z7dP6B83owWs9CqxQCnQe1NMrX5P3r1+viM/gxVmwlcgAZw4ogw8zhOBgJx9FmSMCRKilKssvE8ibpxa"
    "Iq4UJfDsvrighOjuoCO4i5fXu/jp8vPl3Y+3PINm4Mik1oYk6mw50AtbXUlMtODqWyJrtkGhDoEqYZ0BH+JK6MF10hgl/UK8pUJN"
    "vTP4K5ZrepaFPSTWnjN5urAszadwMSxDJXpv4E9JMR0AOXsfIuwtgVmt+PrjrtXry493Pz3eskUYOl7iIdk/FFJdiNXnk8haoaa7"
    "c6bSjeBk7XUEpNS8Xp1+79X7/3H39ofH908//1ONMLXDexZQxpHxuSpg5vIihCwix6vTR7y6f/7l/Uccl2r0SRNz3KYmoYiTGhSn"
    "MWlZSyWJ6UZ9cWc4fHNpoeJhCjo3riVDni3UsxT+v7pewd2Pv4wk893z3Y3+fpaIUGAMmDm7qwxn2C2ilxt/9W/Xb/nh15s5beYg"
    "q7Ea3SOoZNKBfjQfwRIQxpA6cU4uOmclayXuidkQabpZjc+Y8hSd6oROm45NIh7riluzi4MoSieMK4L2bFN/1yyXJtRHl5g7ZZai"
    "IDSVWSboXjC/F6JHgnSfZknm1Xc3C3DbWBze2nLWbT80buP0aq6DHhliuZRJb27u4yrBZUJvx6zopoxQeVWkfPHqFD99dffu8fmX"
    "a22gN5sNLwJkZbY6eoEdZjvCRhs9PDFlr3laGcFZYvL3q99cv/+Hy8Pjw0cDPMMI5I7dZ840X3J04Dwr3hy9d7rG8bER3FBtf3X6"
    "1leX57/f7PtminU2a57bFWUmnxN9KQGh3esjq5zUIrgAk/w2F4FJDA4AsiK3cY78YNylLAxr+dn1ch7fXWfDFassdBHNZPfwRlOm"
    "3mXCdqqMdOMAuFD1TnSDJB4VICob4nFzto2PZYO+hoxz9upXO6e4MDaHKir8euFbLMAHeS9IPhm/TzAMwHS8n7mDTJMzFMOA2pX6"
    "xm5bmnz25gO+XMl5Sc5iL66NyVhQIbXAC5xe5+tfn37+9cPHQ8eKBQQj2xD0sANmQU9vqllEqETolkSGpCzBK9pluc6+ioiq4Hir"
    "zrJVcOxU6LS7TgE6UbH7fCwXw3eJDg+RZ+Ey08Ty+ZvqKCQXQwT0spOLFpEyYpnovOya1jvi4xjRr88g4uv3/7jcP19dr5hporYi"
    "heBpMe4U+YTOlEmU9wo6n6YUslktfN8Op8zYul1zqLhvL8arShP+2+kAv3589/j3mwqhUYFTigcLm53LBawwALK48jTk/q4+r5rP"
    "S4gPnz7i6/un+x8uz/fXGzQYneZbO6PV4X9X2mJ4Md6gntPXZzXz67uHX/+LacBBOKOI6q3n4HFKpO7sVVq6Zuk3zWNYJl6Rqp2H"
    "gwJxMrGrO5lL3VUqcIpARW7cEPONTiFGCQkMC6068QSkphPUhGr+NDwL/vrslHx9+XD56y8fnwCBcw03m1zhIxQfaLsBktlW4GTR"
    "g1PxDNXfNd+zJBc6UXdBIhDF/80mfghFq9u2MLi7zOwp2ad2UpkTOFakmZKsSnPxIY+FM8UI9aIdElEZa4SuG7RRVIrl8xoJY/NB"
    "VkKJ6Leyl4Q7sytjdlEML/uUORFnd71OsIsMTlaWMOnnZOSLxnezeYXvbPIxPpYz7C6PxOheKfIxIBxifpi6XFPYRkJxnbmFhKZz"
    "WGWUEjFaSSICnnMpMbphHpS4Tvkc5dfNBTijZPhKmEIECdUVoKYTL+PTq4R0mK1IZmuTHy0IJYn6S+KQp3p+pUUi87UgeSS4h7pY"
    "tRuBtMt8OOUfByxkSHYVS4rTwVkO8jWnXVdxSxnmcuZd2zmkwEe7CVLYVxcNYmxM0vBgK0N2x57rWTT0vcgIM7QqqwWUFVuHulqm"
    "BL4yzzprOFSaIpDCby6o7W1TRExH7vcn5Pz3j0//PPcr1K0cwC2AOstfSXBIojGSltPDKy5O6HBw6iShQ2VoktgeUQe/eLa5f3/5"
    "2/UHWzT56FT7MYXAaTSp9qsasMYKQNITP21hj7okUfVRHqihSDC5Ab44BxExoVmCWOvUvCWc7+sM7HeXrg4e06itJ4CLzmt2LPRO"
    "BslkyBlB+cQsxM/bch1wrQKxT42PqBZB5V4c8aCkv4FA208lfdcgd+hDc/F1zd1GDba7UjE5M6ZGBaYdiS8hzo1YFCXxsLcjMtee"
    "NzZ/sLuLL23kEsUJGCIaBsa4VeKfSqBdlrMsqrxPcIIUACvqAx3o7Yq0a/U2qDioZrd7hBammadTcCZzSCNa6pBGZSf3FcWKQMt+"
    "8ZmlDgLNDmeEnV+8fFAYhp2Fi3HGUWfcjVRESlUo5c0Xl+bZyMhRJxZLBU3p9RrjqtDeF3hPURodwdpprWm0YXWsTyRxzAwfsydg"
    "ZcpsIg6Cq4A4Fy/b8jUrCreVDRx9ErOlEqZukRglZbue8/P6en7eXm6mYcVsx2Hf05Ey57VN/cA2Z9nL0zr2JKfyIm6b0oevzsz5"
    "q+fLcSWeGP8qxCzqFBXePA8gGC2ITFIXX1xaCIJBnySPwnQ1WUep+AIYQavDZXJmOhLcXld4pIhbdR9n60PxMprWLlGTy/mSUwSD"
    "R4WQUbw+ER0MPUUtvGmA4m0I3kuJ/aSyCI7pyqvRZXmF9Ip6V7wKWqBZECXE5GraWCDKK40zOks5rtjXTdEsl2KeujC7J+BF8xzZ"
    "pDwiVcAqdaojeaNN0iVMlE0tH2rrCvatgVd0PpfuTByVjJpgLctUgfjqLIZ/9e7pcnf8Uy7a25G8SrBAXUmuvbhM209wIGumM5qb"
    "OB+7NbHatQRfti2O2DorBf72zQ3N7+7d8/11kNH4YWuphWz6Y2V1f928Z8N5uvnOEU7XqGLJV2cc/NXT3UeCFluXDI1R9IsLOHTv"
    "9jXJie5q/yDUSjyJsotPskWJx9mthVEDzqvzV4MPkMJtxBU2UUWOUVnQLLU18kpYnd3HpcBFYT6hCk+bA5SDJzcU4SPkVYaGtIkB"
    "/upfr/d9+Y/ruDWrXo0FOhjYBhJI5FCfOtoXCqrVCdQi5e56yl7KabO5KtW3zaXUReaOkwzpUY832nRSraygxlGJ9q+qnKP3xtBT"
    "5brFoTeCLfqNfHdzI9cAJBmBLvdxI4zwQQfFIes+NKKo7IPa2ubuA5zEru66ejNi/LsoBjSwOe59srSwKCp8ifOPfxPMITIF1JuU"
    "bc79YdBBmljcyCxLhE1UFKSBFBVuba6o0cmXRb9gErxaaZq+0EkB6H2jkY7UrzSzYQ9C458k5hlXomLOxCuXSUG6TANL5CBdzdF1"
    "8JNPi92F/JEbLbNjFZIPN9iRiD25plFQDOGSJFLBYVHrSy0Inygj4myddBQ12DsTMzxu6DR3bcY2VASItSJM2h4zRTIfVKtjUEGn"
    "2jY5QRZfPfz0+HB32/0Rm3qYw0ORG9te2Q6jRZAVVgReF5D68mMd/9jOCXSbz8VJdPskHuOF3qkbDflLVkRSuIFjwqxERaW7A+1l"
    "eJFgpuzSfExqVpjfXZRcCHLkAdH8J1XYkJ1xyJ2mEZYVx4ZA0GT2NZ9/0Z1N70h/nw+MTNMUXlwhZlWHKlSE2ecsbNgStMe1zavJ"
    "mTV74iUf0QWvhW7YhcQD9tfAHk9di+Al53ZKQ7g8mRycOJAw6ARrd/BH9x4OJ41ewuLnli/c+ZspiKG1tuvOCyFndF5xVN0LpA7I"
    "Rnr4iUedmSEcVAJFGTX5ntc8AzqZMfnEPGcZBkma2f1WxNtGtMfMYqUZ2YVfhZBA/dyGHMI5VgiYoLtBPnSUGi1SRRgV9Xg9ruyz"
    "3Jj5GM+RtxKc9WmI6+xIMCerw2MB5oEOtCACHudE6uEuWF3Z6Kp0+jmL0DfOsuTiEH6WHlqqq89FaN7IObsS846qcEDQ3LZ+RUbB"
    "hGPjiHFErVJotcxZPrYfhcFQJByV1Ht/y7UhZL9R4MYldkj6AD0dzAqVCGepfdnnp4IXk7NkMXaOwVRaEEUIld/KKOIYfKQcZl4X"
    "ttOaj0y1tcQyZY/4JLdGraNrl1af06HJ5fRp1YhR2tf8WSRXW4GMtDCMSGQfCx6tY9ukt1WkGT3LW7oLjw2lswnBVeNds8/lUMCk"
    "EdAIhqhQsl2nZQm8w6ibCNKHodpel5Xjip7TdVetRF7SZlvX/SDGDz4UcpsSDoQG8nYN1QvK9YtGDpbVh+YmJhI6Qm8HO7KYZuq4"
    "YevPWwS7Ly6bI859xHyCt1IhDHlqTZH2gY3S0TDd0qjpypmW0krpASQIMDCZqZ3SdIf2szvwCtseTSOyMjo1qr67xLPbDrOsuLJf"
    "wRNWlz6XqdqXOcsiyyoFymySoDKUdNoPtDRhXPoQb8ftZrgkXSGpiQC2TSPj1PWMyOy7kkdFvlVJiuvQJsctiUTZsik/Ngt4NZAB"
    "lhoVYGRe22awalMxCXP8gCPEgg8lgsvSkWUy/kMZERhZGroydHTV6bIcpu6StAnlgIaPBrRHr6aBuJs6g60qco/MolmB5mvWdW1F"
    "Eir7gRigWOkC6UnUKhmwoxYhQxyvUlVpamqqiIVau+2CaszOyJRFtEKsECxdrMIw0rX6nAwsjABHVddQ7C2WiYHa9pK+pNOq4a9i"
    "MX2J7jptroMpLLRJY0ULP8bDPjgcDtiWIJM2uY12z3tF66Vz6hTKZ0YsaDP5mhs1ySDnQsQiWsWTszHK1SZ/y0A1l/mwFdKA5WCi"
    "QswVIQpwhF9UASiYskwzbeLdp7WDyBWFFZWVahWM84THlTuT28vhoOMDK1KPxeTYiilpNpS21QFS5WKTjLTRVRzAdcbdhblsiw80"
    "HF9vGIecNBi4OOhDWmNJm2ryrxeGu6qQVRkmHQCQrQjhjl1mj9jAeBzVEKeBiFKxsjqm4g5mFiC9b+Uz+3A21bCcjM6kQBx4j3am"
    "cdoMMYeiQ3JVWQFn9Nztu+2Dxefo7a7nbLfV6uFiACQZts/qZo2BbNrIPhyc+5XSuz3cnTEntr9l3UyrbI8HY9qSVOyLfKtpquR6"
    "iORiaHApVltF1CSi3U92yZY2HeMonVbFNLan7VSV1g8wWkFSvabYpG3qpWfNZ7fRozXnKc0mbyNxVXvKQehHkWtkN1TTkk6q3MaK"
    "5LtV5XTRtlypWwdndUpodmE6y60odmngmn2JKTzZc0uqxkksREtr0zAaOC92lcxmy1VLmA/vxwjtSeLwzU3icDO/thkipGcrOHsP"
    "yaXFsk53Ed/RjEE5J0MHhzUIHobWus+cij7mKU6gujhVRU1gJpsw+6i45Aglnsh4u0nHltNEXVMFF7kp+O4pMbBQBDjVijYfmxQQ"
    "dOtoggWGmgluTrTX3CgwXAla73aitBM9CqI5GaKimlpl6oRodFqUBsGrkghl4ZgZo1gCKKTNB2f5ImRvmXjmnZYzLCs+OIbBCMy0"
    "CR4hi2zgUi0ucj7nfu8ur0Ck4+i7U9KueMuA4iIoDbCWDPPzORdA1JWbixkELlyD7Srol8QAAdG0gWYriW4OFhZGdFIt8cCZznNm"
    "0JzPNZNGigxdpojIkcyOmwsub6Kso89CqdDuAWF+h61oyA1xHlPoFDtq5sucrVHoOzRHGXiAVxeErK1/yfBnpeWrU4p2fV7FrezR"
    "DemsNK5mfCKqkVHUmOblMw0BHvhUWBrfNBNy8mpdIg0a3+Zwc0G1XVJ0lzbd7lIUoH/KHC4BMDAApdOxQWU0nVIzSvSSRlgkZMmU"
    "9BWp4ppdZBeyPBQw6gKZN66eqsXmulwqlCrdZtIAAG9HJRSfI+4ct+awZae0o2qCXiqwc6Y1ZDSQGOOKyoFEsYgNQdHa/xvWLNnw"
    "9tAl1rxPWmrS8DPzS+Zz0ya6ZEJYs2oUtLTYZxknTTN31la/+vGjOmgyjqEitO6o3IW5CAyQinSAA9ImQqjowAhcahdlXqVAQ0Eb"
    "IfloJcVPiZldICw98qAkqhPiEz4EmT2FLDK90AbwMvidJ9jYGUCnMjLIybDyV/pl0YVcod/Qu4oeU4ot1WcvuixeGWwT9lt9QMwO"
    "y9V/kjFjPiSow/bafJyb2T+qlL87kYq/e//w8+Xp1xtkoZma8RDDKf8i3popSCrPyN472ryl76zVOadM65pcjgf2bV0mPZ/Ckiv9"
    "urAHDGK7ptOz/e7x4af3T5d3/4XUQXJR6ilfFTLGongSRbkp6rG3OfG3wzpH/VwlpH1KaVPtTY4sKIwWChDxff6K9GpD9Y44DVeh"
    "jjNj+rj4s+X0u8v9FQNjYoomvq5dX9fJi2wLI5Pgo0whzuhSyKhbnibCYW4q1011ke2KohmBU3kRdjDlL0+s5cv3v14eLh+PI0+F"
    "oReKxp36J7RooHSGXndgIHRfXOy/knVGhtxTJ7Oc0keTuWaYGNTCMbM0jK4qi9ccJi6a+XRtmZiPm8lMDkJldMYpn+3aNHOdX/75"
    "eoMmRrr+5v7du6vEYupqB9SRcTDWtxgQYpvcTgya5oy4Uy0u5ZTghkzhIG9ayKvCjdNQ3FNYoLdoTHchoF5+8/ElXS2V7dqR7R2E"
    "OGUGFQjbUhVz3okPrsm8ZWpgd4wsSAGVfTTeblMrN5/+F57jtkxUb0aE33uZRajG4GOFHNetwkNkMJt65hXxWyQcp8TOHHS6QEPv"
    "msgWaEHHNXiZ15WC5wAvoercpia1uWyNvr+u0eX57u3luG7NzWqyYWQ7BUwXY+aC+kfKLh0cSx4nkRCLQ0vy2AtfJsO0n40EwVvc"
    "OlgPnqs4i+4vn+4eLj/dHA/LKKVrgAjhVRihdWkaqDn38rubz9/9eOW928dDqvEA6sohz9Ch26yaqeRI5SRPrTmFS5WsBeIm0K/i"
    "k8aRwLXZViqTi/AlVrbQhik6ezChfDQlY/OcusMxo+ziOL7swFaKLnmlZOt6AzJpFLKTw2Q3MChquG6nZm72GU59oaCoMorq85R/"
    "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"
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
