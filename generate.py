import os

def parse_adif(filename='log.adif'):
    if not os.path.exists(filename):
        return None, 0, {}, {}
    
    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    records = content.split('<eor>')
    total_qso = 0
    modes = {'CW': 0, 'SSB': 0, 'FT8': 0}
    power = {'QRP': 0, 'QRO': 0, 'UNKNOWN': 0}
    bands = {}
    
    for record in records:
        if '<call:' not in record.lower():
            continue
        total_qso += 1
        
        # Estrazione Modo
        import re
        m_match = re.search(r'<mode:\d+>([^<\s]+)', record, re.IGNORECASE)
        if m_match:
            mode = m_match.group(1).upper()
            if mode in modes:
                modes[mode] += 1
            else:
                modes[mode] = modes.get(mode, 0) + 1
                
        # Estrazione Potenza
        p_match = re.search(r'<tx_pwr:\d+>([\d.]+)', record, re.IGNORECASE)
        if p_match:
            try:
                p = float(p_match.group(1))
                if p <= 5:
                    power['QRP'] += 1
                else:
                    power['QRO'] += 1
            except ValueError:
                power['UNKNOWN'] += 1
        else:
            power['UNKNOWN'] += 1
            
        # Estrazione Banda
        b_match = re.search(r'<band:\d+>([^<\s]+)', record, re.IGNORECASE)
        if b_match:
            band = b_match.group(1).lower()
            bands[band] = bands.get(band, 0) + 1
            
    return total_qso, modes, power, bands

def generate_html():
    total_qso, modes, power, bands = parse_adif()
    
    if not total_qso or total_qso == 0:
        html_content = "<h2>Nessun QSO trovato nel log.</h2>"
    else:
        # Calcolo percentuali modi
        p_cw = (modes.get('CW', 0) / total_qso) * 100
        p_ssb = (modes.get('SSB', 0) / total_qso) * 100
        p_ft8 = (modes.get('FT8', 0) / total_qso) * 100
        
        # Calcolo percentuali potenza
        p_qrp = (power.get('QRP', 0) / total_qso) * 100
        p_qro = (power.get('QRO', 0) / total_qso) * 100
        p_unspec = (power.get('UNKNOWN', 0) / total_qso) * 100
        
        # Bande ordinate
        sorted_bands = sorted(bands.items(), key=lambda x: x[1], reverse=True)
        band_colors = {'20m': '#e8a33d', '40m': '#6c3483', '80m': '#1a9e77', '30m': '#e186a8', '15m': '#2e7fd6', '10m': '#c0392b', '17m': '#1e8449', '12m': '#7f8c8d', '160m': '#d35400'}
        
        band_bars_html = ""
        band_legend_html = ""
        for band, count in sorted_bands:
            p_band = (count / total_qso) * 100
            color = band_colors.get(band, '#333333')
            band_bars_html += f'<div style="width:{p_band}%; background:{color};"></div>\n'
            band_legend_html += f'<span style="display:inline-block; width:10px; height:10px; background:{color}; margin:0 4px 0 12px;"></span>{band} ({p_band:.1f}%) '

        html_content = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>My Operating Style</title>
</head>
<body style="background: #eef2f3; padding: 40px 0;">
<div style="font-family: Arial, Helvetica, sans-serif; background:#f0f0f0; border-radius:12px; padding:24px 28px; max-width:640px; margin:0 auto; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">
  <h2 style="text-align:center; font-size:24px; color:#333; margin:0 0 20px 0;">My operating style</h2>

  <!-- Barra Modi -->
  <div style="width:100%; height:26px; border-radius:13px; overflow:hidden; border:1px solid #000; display:flex; background:#ddd;">
    <div style="width:{p_cw}%; background:#c0392b;"></div>
    <div style="width:{p_ssb}%; background:#1e8449;"></div>
    <div style="width:{p_ft8}%; background:#e67e22;"></div>
  </div>
  <div style="margin:6px 0 22px 0; font-size:13px; color:#333;">
    <span style="display:inline-block; width:10px; height:10px; background:#c0392b; margin-right:4px;"></span>CW ({p_cw:.1f}%)
    <span style="display:inline-block; width:10px; height:10px; background:#1e8449; margin:0 4px 0 12px;"></span>SSB ({p_ssb:.1f}%)
    <span style="display:inline-block; width:10px; height:10px; background:#e67e22; margin:0 4px 0 12px;"></span>FT8 ({p_ft8:.1f}%)
  </div>

  <!-- Barra Potenza -->
  <div style="width:100%; height:26px; border-radius:13px; overflow:hidden; border:1px solid #000; display:flex; background:#ddd;">
    <div style="width:{p_qrp}%; background:#2e7fd6;"></div>
    <div style="width:{p_qro}%; background:#c0392b;"></div>
    <div style="width:{p_unspec}%; background:#7f8c8d;"></div>
  </div>
  <div style="margin:6px 0 22px 0; font-size:13px; color:#333;">
    <span style="display:inline-block; width:10px; height:10px; background:#2e7fd6; margin-right:4px;"></span>QRP (&le;5W) ({p_qrp:.1f}%)
    <span style="display:inline-block; width:10px; height:10px; background:#c0392b; margin:0 4px 0 12px;"></span>QRO (&gt;5W) ({p_qro:.1f}%)
    <span style="display:inline-block; width:10px; height:10px; background:#7f8c8d; margin:0 4px 0 12px;"></span>Non specificata ({p_unspec:.1f}%)
  </div>

  <!-- Barra Bande -->
  <div style="width:100%; height:26px; border-radius:13px; overflow:hidden; border:1px solid #000; display:flex; background:#ddd;">
    {band_bars_html}
  </div>
  <div style="margin:6px 0 0 0; font-size:13px; color:#333;">
    {band_legend_html}
  </div>
  <div style="margin-top:15px; text-align:right; font-size:11px; color:#777;">
    Totale QSO analizzati: {total_qso}
  </div>
</div>
</body>
</html>
"""

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print("Pagina index.html generata con successo!")

if __name__ == '__main__':
    generate_html()