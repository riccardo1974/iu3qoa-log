#!/usr/bin/env python3
"""
Genera index.html con le statistiche QSO gia' calcolate (nessun fetch/JS
lato client necessario), a partire da log.adi.

Contenuto della card:
  - Titolo "Bands and most active hours" allineato a sinistra con la barra.
  - Bande: vengono mostrate solo quelle presenti nel log. Se almeno due bande
    hanno una percentuale sotto MIN_BAND_PCT vengono raggruppate in "Other"
    (impostare MIN_BAND_PCT = 0 per mostrarle tutte separatamente).
  - Orari: istogramma dei QSO per ora UTC (campo TIME_ON) con evidenziate
    le TOP_HOURS fasce orarie piu' frequenti.

Uso: python3 generate_stats.py
Legge log.adi nella stessa cartella, scrive index.html nella stessa cartella.
"""

import re
from datetime import datetime, timezone

MIN_BAND_PCT = 1.0   # bande sotto questa % raggruppate in "Other" (0 = disattivato)
TOP_HOURS = 3        # quante fasce orarie UTC evidenziare

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
    bands = {}
    hours = [0] * 24

    for record in records:
        if not re.search(r'<\s*call\s*[:>]', record, re.I):
            continue
        total += 1

        # Banda
        band_match = re.search(r'<\s*band\s*(?::\d+)?\s*>([^<>]+)', record, re.I)
        if band_match:
            b = band_match.group(1).strip().lower()
            if not b.endswith('m') and 'cm' not in b and 'km' not in b:
                b = b + 'm'
            bands[b] = bands.get(b, 0) + 1
        else:
            bands['unknown'] = bands.get('unknown', 0) + 1

        # Ora UTC (TIME_ON: HHMM o HHMMSS)
        time_match = re.search(r'<\s*time_on\s*(?::\d+)?\s*>([^<>]+)', record, re.I)
        if time_match:
            t = time_match.group(1).strip()
            if len(t) >= 2 and t[:2].isdigit() and int(t[:2]) < 24:
                hours[int(t[:2])] += 1

    if total == 0:
        total = 1

    return total, bands, hours


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


def build_html(total, bands, hours, updated_at):
    band_segments = build_band_segments(bands, total)
    band_bar, band_legend = bar_and_legend(band_segments)
    hour_bars, hour_labels, top_text = build_hours_chart(hours)

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QSO Statistics - IU3QOA</title>
<style>
body {{ margin:0; padding:0; background-color:transparent; font-family:Arial,sans-serif; color:#333; display:flex; justify-content:center; align-items:center; height:100vh; }}
.card {{ width:900px; height:284px; background:#f0f0f0; border-radius:12px; box-shadow:0 4px 10px rgba(0,0,0,0.1); padding:20px 28px; box-sizing:border-box; position:relative; }}
h2 {{ text-align:left; font-size:17px; font-weight:bold; margin:0 0 14px 0; color:#222; }}
.bar-container {{ width:844px; height:26px; background:#ddd; border:1px solid #000; border-radius:13px; display:flex; overflow:hidden; margin-bottom:6px; }}
.bar-segment {{ height:100%; }}
.legend {{ display:flex; flex-wrap:wrap; gap:15px; font-size:13px; margin-bottom:14px; }}
.legend-item {{ display:flex; align-items:center; gap:5px; }}
.color-dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
.section-title {{ font-size:13px; font-weight:bold; margin:4px 0 6px 0; color:#333; }}
.hours-chart {{ width:844px; height:60px; display:flex; align-items:flex-end; gap:3px; border-bottom:1px solid #999; }}
.hour-bar {{ flex:1; border-radius:2px 2px 0 0; }}
.hours-labels {{ width:844px; display:flex; gap:3px; margin-top:2px; }}
.hours-labels span {{ flex:1; text-align:center; font-size:9px; color:#666; }}
.top-hours {{ font-size:12px; margin-top:6px; color:#333; }}
.last-update {{ text-align:left; font-size:11px; color:#888; margin-top:10px; }}
</style>
</head>
<body>
<div class="card">
<h2>Bands and most active hours</h2>
<div id="content">

<div class="bar-container">{band_bar}</div>
<div class="legend">{band_legend}</div>

<div class="section-title">Most active hours (UTC)</div>
<div class="hours-chart">{hour_bars}</div>
<div class="hours-labels">{hour_labels}</div>
<div class="top-hours">Top: {top_text}</div>

<div class="last-update">Last update: {updated_at}</div>

</div>
</div>
</body>
</html>
"""


if __name__ == '__main__':
    total, bands, hours = parse_log('log.adi')
    updated_at = datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
    html = build_html(total, bands, hours, updated_at)
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Generato index.html - {total} QSO totali - aggiornato {updated_at}")
