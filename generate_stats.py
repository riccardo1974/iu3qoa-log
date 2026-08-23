#!/usr/bin/env python3
"""
Genera index.html con le statistiche QSO gia' calcolate (nessun fetch/JS
lato client necessario), a partire da log.adi.

Uso: python3 generate_stats.py
Legge log.adi nella stessa cartella, scrive index.html nella stessa cartella.
"""

import re

BAND_COLORS = {
    '20m': '#e8a33d', '40m': '#6c3483', '80m': '#1a9e77',
    '30m': '#e186a8', '15m': '#2e7fd6', '10m': '#c0392b',
    '17m': '#1e8449', '12m': '#7f8c8d', '160m': '#d35400',
    '6m': '#9b59b6', '2m': '#3498db',
}


def parse_log(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()

    records = re.split(r'<\s*eor\s*>', text, flags=re.I)
    total = 0
    modes = {'CW': 0, 'SSB': 0, 'FT8': 0, 'OTHER': 0}
    power = {'QRP': 0, 'QRO': 0, 'UNKNOWN': 0}
    bands = {}

    for record in records:
        if not re.search(r'<\s*call\s*[:>]', record, re.I):
            continue
        total += 1

        # Modo
        mode_match = re.search(r'<\s*mode\s*(?::\d+)?\s*>([^<>]+)', record, re.I)
        m = mode_match.group(1).strip().upper() if mode_match else 'OTHER'
        if 'CW' in m:
            modes['CW'] += 1
        elif 'SSB' in m or 'USB' in m or 'LSB' in m:
            modes['SSB'] += 1
        elif 'FT8' in m:
            modes['FT8'] += 1
        else:
            modes['OTHER'] += 1

        # Potenza (dal campo NOTES/COMMENT)
        note_match = re.search(r'<\s*(?:notes|comment)\s*(?::\d+)?\s*>([^<>]+)', record, re.I)
        note = note_match.group(1).upper().strip() if note_match else ''

        if 'QRP' in note:
            power['QRP'] += 1
        elif note == '':
            power['QRO'] += 1
        else:
            w_match = re.search(r'(\d+(?:\.\d+)?)\s*W', note)
            if w_match:
                p = float(w_match.group(1))
                if p <= 5:
                    power['QRP'] += 1
                elif p >= 10:
                    power['QRO'] += 1
                else:
                    power['UNKNOWN'] += 1
            else:
                power['UNKNOWN'] += 1

        # Banda
        band_match = re.search(r'<\s*band\s*(?::\d+)?\s*>([^<>]+)', record, re.I)
        if band_match:
            b = band_match.group(1).strip().lower()
            if not b.endswith('m') and 'cm' not in b and 'km' not in b:
                b = b + 'm'
            bands[b] = bands.get(b, 0) + 1
        else:
            bands['unknown'] = bands.get('unknown', 0) + 1

    if total == 0:
        total = 1

    return total, modes, power, bands


def pct(n, total):
    return round((n / total) * 100, 1)


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


def build_html(total, modes, power, bands):
    mode_segments = [
        ('CW', pct(modes['CW'], total), '#c0392b'),
        ('SSB', pct(modes['SSB'], total), '#1e8449'),
        ('FT8', pct(modes['FT8'], total), '#e67e22'),
        ('Other', pct(modes['OTHER'], total), '#7f8c8d'),
    ]
    power_segments = [
        ('QRP', pct(power['QRP'], total), '#2e7fd6'),
        ('QRO', pct(power['QRO'], total), '#c0392b'),
        ('Not specified', pct(power['UNKNOWN'], total), '#7f8c8d'),
    ]
    sorted_bands = sorted(bands.items(), key=lambda x: -x[1])
    band_segments = [
        (b, pct(c, total), BAND_COLORS.get(b, '#555555'))
        for b, c in sorted_bands
    ]

    mode_bar, mode_legend = bar_and_legend(mode_segments)
    power_bar, power_legend = bar_and_legend(power_segments)
    band_bar, band_legend = bar_and_legend(band_segments)

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QSO Statistics - IU3QOA</title>
<style>
body {{ margin:0; padding:0; background-color:transparent; font-family:Arial,sans-serif; color:#333; display:flex; justify-content:center; align-items:center; height:100vh; }}
.card {{ width:900px; height:306px; background:#f0f0f0; border-radius:12px; box-shadow:0 4px 10px rgba(0,0,0,0.1); padding:20px 28px; box-sizing:border-box; position:relative; }}
h2 {{ text-align:center; font-size:20px; margin:0 0 18px 0; color:#333; }}
.bar-container {{ width:844px; height:26px; background:#ddd; border:1px solid #000; border-radius:13px; display:flex; overflow:hidden; margin-bottom:6px; }}
.bar-segment {{ height:100%; }}
.legend {{ display:flex; flex-wrap:wrap; gap:15px; font-size:13px; margin-bottom:14px; }}
.legend-item {{ display:flex; align-items:center; gap:5px; }}
.color-dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
</style>
</head>
<body>
<div class="card">
<h2>My operating style and pwr setting</h2>
<div id="content">

<div class="bar-container">{mode_bar}</div>
<div class="legend">{mode_legend}</div>

<div class="bar-container">{power_bar}</div>
<div class="legend">{power_legend}</div>

<div class="bar-container">{band_bar}</div>
<div class="legend">{band_legend}</div>

</div>
</div>
</body>
</html>
"""


if __name__ == '__main__':
    total, modes, power, bands = parse_log('log.adi')
    html = build_html(total, modes, power, bands)
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Generato index.html - {total} QSO totali")
