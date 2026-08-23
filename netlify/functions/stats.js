const fs = require('fs');
const path = require('path');

exports.handler = async function(event, context) {
    try {
        const filePath = path.resolve(__dirname, '../../log.adi');
        let text = '';
        if (fs.existsSync(filePath)) {
            text = fs.readFileSync(filePath, 'utf8');
        } else {
            const res = await fetch('https://raw.githubusercontent.com/riccardo1974/iu3qoa-log/main/log.adi');
            text = await res.text();
        }

        const records = text.split(/<\s*eor\s*>/i);
        let totalQso = 0;
        let modes = { CW: 0, SSB: 0, FT8: 0, OTHER: 0 };
        let power = { QRP: 0, QRO: 0, UNKNOWN: 0 };
        let bands = {};

        records.forEach(record => {
            if (!/<\s*call\s*[:>]/i.test(record)) return;
            totalQso++;

            // 1. MODI
            let modeMatch = record.match(/<\s*mode\s*(?::\d+)?\s*>([^<>]+)/i);
            let m = modeMatch ? modeMatch[1].trim().toUpperCase() : 'OTHER';
            if (m.includes('CW')) modes.CW++;
            else if (m.includes('SSB') || m.includes('USB') || m.includes('LSB')) modes.SSB++;
            else if (m.includes('FT8')) modes.FT8++;
            else modes.OTHER++;

            // 2. POTENZA (Cerca QRP nelle note/commenti o nel tx_pwr)
            let noteMatch = record.match(/<\s*(?:notes|comment|app_[^>]+)\s*(?::\d+)?\s*>([^<>]+)/i);
            let pwrMatch = record.match(/<\s*tx_pwr\s*(?::\d+)?\s*>([^<>]+)/i);
            
            let powerText = (pwrMatch ? pwrMatch[1] : '') + ' ' + (noteMatch ? noteMatch[1] : '');
            powerText = powerText.toUpperCase();

            if (powerText.includes('QRP')) {
                power.QRP++;
            } else if (pwrMatch) {
                let p = parseFloat(pwrMatch[1]);
                if (!isNaN(p)) {
                    if (p <= 5) power.QRP++;
                    else power.QRO++;
                } else {
                    power.QRO++; // Default a QRO se c'è un valore numerico alto o non specificato ma non QRP
                }
            } else {
                power.UNKNOWN++;
            }

            // 3. BANDE (Supporto flessibile per qualsiasi formato di banda ADIF)
            let bandMatch = record.match(/<\s*band\s*(?::\d+)?\s*>([^<>]+)/i);
            if (bandMatch) {
                let b = bandMatch[1].trim().toLowerCase();
                // Normalizzazione standard delle bande (es. 40m, 20m, ecc.)
                if (!b.endsWith('m') && !b.includes('cm') && !b.includes('km')) {
                    b = b + 'm'; 
                }
                bands[b] = (bands[b] || 0) + 1;
            } else {
                bands['unknown'] = (bands['unknown'] || 0) + 1;
            }
        });

        if (totalQso === 0) totalQso = 1;

        let pCW = ((modes.CW / totalQso) * 100).toFixed(1);
        let pSSB = ((modes.SSB / totalQso) * 100).toFixed(1);
        let pFT8 = ((modes.FT8 / totalQso) * 100).toFixed(1);
        let pOther = ((modes.OTHER / totalQso) * 100).toFixed(1);

        let pQrp = ((power.QRP / totalQso) * 100).toFixed(1);
        let pQro = ((power.QRO / totalQso) * 100).toFixed(1);
        let pUnspec = ((power.UNKNOWN / totalQso) * 100).toFixed(1);

        let sortedBands = Object.entries(bands).sort((a, b) => b[1] - a[1]);
        const bandColors = {'20m': '#e8a33d', '40m': '#6c3483', '80m': '#1a9e77', '30m': '#e186a8', '15m': '#2e7fd6', '10m': '#c0392b', '17m': '#1e8449', '12m': '#7f8c8d', '160m': '#d35400', '6m': '#9b59b6', '2m': '#3498db'};

        const maxW = 844;
        let wCw = (modes.CW / totalQso) * maxW;
        let wSsb = (modes.SSB / totalQso) * maxW;
        let wFt8 = (modes.FT8 / totalQso) * maxW;
        let wOther = maxW - (wCw + wSsb + wFt8);

        let wQrp = (power.QRP / totalQso) * maxW;
        let wQro = (power.QRO / totalQso) * maxW;
        let wUnspec = maxW - (wQrp + wQro);

        // Generazione barre bande SVG
        let currentBandX = 28;
        let bandsRects = '';
        sortedBands.forEach(([band, count]) => {
            let bW = (count / totalQso) * maxW;
            let col = bandColors[band] || '#555555';
            bandsRects += `<rect x="${currentBandX}" y="0" width="${bW}" height="26" fill="${col}" />`;
            currentBandX += bW;
        });

        // Generazione legenda bande su una o due righe
        let bandLegendItems1 = '';
        let bandLegendItems2 = '';
        let lx1 = 28, lx2 = 28;
        let countBands = 0;

        sortedBands.forEach(([band, count]) => {
            let pB = ((count / totalQso) * 100).toFixed(1);
            let col = bandColors[band] || '#555555';
            let itemHtml = `<circle cx="${countBands < 7 ? lx1 + 5 : lx2 + 5}" cy="-4" r="5" fill="${col}" /><text x="${countBands < 7 ? lx1 + 15 : lx2 + 15}" y="0" font-family="Arial, sans-serif" font-size="13" fill="#333">${band} (${pB}%)</text>`;
            
            if (countBands < 7) {
                bandLegendItems1 += itemHtml;
                lx1 += 110;
            } else {
                bandLegendItems2 += itemHtml;
                lx2 += 110;
            }
            countBands++;
        });

        const svgContent = `<svg width="900" height="306" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <filter id="shadow" x="-5%" y="-5%" width="110%" height="110%">
      <feDropShadow dx="0" dy="4" stdDeviation="5" flood-color="#000" flood-opacity="0.1"/>
    </filter>
  </defs>

  <rect x="0" y="0" width="900" height="306" rx="12" fill="#f0f0f0" filter="url(#shadow)" />

  <text x="450" y="32" font-family="Arial, sans-serif" font-size="20" font-weight="bold" fill="#333" text-anchor="middle">My operating style and pwr setting</text>

  <!-- BARRA MODI -->
  <g transform="translate(28, 50)">
    <rect width="844" height="26" rx="13" fill="#ddd" stroke="#000" stroke-width="1"/>
    <svg width="844" height="26" overflow="hidden" style="border-radius: 13px;">
      <rect x="0" y="0" width="${wCw}" height="26" fill="#c0392b" />
      <rect x="${wCw}" y="0" width="${wSsb}" height="26" fill="#1e8449" />
      <rect x="${wCw + wSsb}" y="0" width="${wFt8}" height="26" fill="#e67e22" />
      <rect x="${wCw + wSsb + wFt8}" y="0" width="${wOther}" height="26" fill="#7f8c8d" />
    </svg>
  </g>
  <g transform="translate(28, 97)" font-family="Arial, sans-serif" font-size="13" fill="#333">
    <circle cx="5" cy="-4" r="5" fill="#c0392b"/><text x="15" y="0">CW (${pCW}%)</text>
    <circle cx="115" cy="-4" r="5" fill="#1e8449"/><text x="125" y="0">SSB (${pSSB}%)</text>
    <circle cx="225" cy="-4" r="5" fill="#e67e22"/><text x="235" y="0">FT8 (${pFT8}%)</text>
    <circle cx="335" cy="-4" r="5" fill="#7f8c8d"/><text x="345" y="0">Other (${pOther}%)</text>
  </g>

  <!-- BARRA POTENZA -->
  <g transform="translate(28, 125)">
    <rect width="844" height="26" rx="13" fill="#ddd" stroke="#000" stroke-width="1"/>
    <svg width="844" height="26" overflow="hidden" style="border-radius: 13px;">
      <rect x="0" y="0" width="${wQrp}" height="26" fill="#2e7fd6" />
      <rect x="${wQrp}" y="0" width="${wQro}" height="26" fill="#c0392b" />
      <rect x="${wQrp + wQro}" y="0" width="${wUnspec}" height="26" fill="#7f8c8d" />
    </svg>
  </g>
  <g transform="translate(28, 167)" font-family="Arial, sans-serif" font-size="13" fill="#333">
    <circle cx="5" cy="-4" r="5" fill="#2e7fd6"/><text x="15" y="0">QRP (${pQrp}%)</text>
    <circle cx="115" cy="-4" r="5" fill="#c0392b"/><text x="125" y="0">QRO (${pQro}%)</text>
    <circle cx="235" cy="-4" r="5" fill="#7f8c8d"/><text x="245" y="0">Not specified (${pUnspec}%)</text>
  </g>

  <!-- BARRA BANDE -->
  <g transform="translate(28, 195)">
    <rect width="844" height="26" rx="13" fill="#ddd" stroke="#000" stroke-width="1"/>
    <svg width="844" height="26" overflow="hidden" style="border-radius: 13px;">
      ${bandsRects}
    </svg>
  </g>
  
  <!-- Legenda Bande Riga 1 -->
  <g transform="translate(0, 246)">
    ${bandLegendItems1}
  </g>
  
  <!-- Legenda Bande Riga 2 (se presente) -->
  <g transform="translate(0, 268)">
    ${bandLegendItems2}
  </g>
</svg>`;

        return {
            statusCode: 200,
            headers: {
                "Content-Type": "image/svg+xml",
                "Cache-Control": "no-cache, no-store, must-revalidate"
            },
            body: svgContent
        };

    } catch (error) {
        return {
            statusCode: 500,
            body: "Errore generazione SVG: " + error.message
        };
    }
};
