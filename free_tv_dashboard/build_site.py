import json, re, shutil, time, html
from pathlib import Path
from datetime import datetime
import pandas as pd
from PIL import Image, ImageChops

BASE = Path(__file__).resolve().parent
REPO_ROOT = BASE.parent
INCOMING = BASE / 'Incoming'
ARCHIVE = BASE / 'Archive'
DATA = BASE / 'data'
LATEST = DATA / 'latest'
IMAGES = DATA / 'images'
DOCS = BASE / 'docs'
PUBLIC_INDEX = REPO_ROOT / 'index.html'
PUBLIC_IMAGES = REPO_ROOT / 'images'
META = DATA / 'meta.json'

PATTERNS = {
    'relative_volume': re.compile(r'^Relative Volume EP Screener_(\d{4}-\d{2}-\d{2})_', re.I),
    'high_adx_3m': re.compile(r'^Pullback Stocks Screener HIGH ADX with 3M Perf_(\d{4}-\d{2}-\d{2})_', re.I),
    'high_adx': re.compile(r'^Pullback Stocks Screener HIGH ADX_(\d{4}-\d{2}-\d{2})_', re.I),
    'low_adx': re.compile(r'^Pullback Stocks Screener LOW ADX_(\d{4}-\d{2}-\d{2})_', re.I),
    'luc': re.compile(r'^Luc Stock Screener_(\d{4}-\d{2}-\d{2})_', re.I),
}
TITLES = {
    'high_adx_3m':'Pullback Stocks Screener HIGH ADX with 3M Perf',
    'high_adx':'Pullback Stocks Screener HIGH ADX',
    'low_adx':'Pullback Stocks Screener LOW ADX',
    'luc':'Luc Stock Screener',
    'relative_volume':'Relative Volume EP Screener',
}
ORDER = ['high_adx_3m','high_adx','low_adx','luc','relative_volume']
Q='Revenue growth %, Quarterly YoY'; T='Revenue growth %, TTM YoY'

def ensure():
    for p in [INCOMING,ARCHIVE,LATEST,IMAGES,DOCS]: p.mkdir(parents=True,exist_ok=True)
    if not META.exists(): META.write_text(json.dumps({'latest_date':None,'image_dates':[]},indent=2))

def fmt(col,v):
    if pd.isna(v): return ''
    if isinstance(v,(int,float)):
        if 'volume' in col.lower() or 'capitalization' in col.lower():
            av=abs(v)
            if av>=1e9: return f'{v/1e9:.2f}B'
            if av>=1e6: return f'{v/1e6:.2f}M'
            if av>=1e3: return f'{v/1e3:.1f}K'
        if '%' in col: return f'{v:.2f}%'
        if col.lower()=='price': return f'{v:.2f}'
        return f'{v:.4g}'
    return str(v)


def chart_color_score(path):
    """
    Sector RS has many differently colored sector lines.
    G10 EL Proxy is mostly gray with blue/red overlays.
    """
    with Image.open(path) as im:
        rgb = im.convert('RGB')
        rgb.thumbnail((700, 350))

        colorful = 0
        total = 0
        hue_bins = set()

        for r, g, b in rgb.getdata():
            mx = max(r, g, b)
            mn = min(r, g, b)
            chroma = mx - mn

            if mx < 55 or chroma < 28:
                continue

            total += 1
            colorful += chroma

            if r >= g and r >= b:
                if g > b * 1.35:
                    hue_bins.add('yellow_orange')
                elif b > g * 1.2:
                    hue_bins.add('magenta')
                else:
                    hue_bins.add('red')
            elif g >= r and g >= b:
                if b > r * 1.2:
                    hue_bins.add('cyan_green')
                else:
                    hue_bins.add('green')
            else:
                if r > g * 1.2:
                    hue_bins.add('purple')
                else:
                    hue_bins.add('blue')

        return len(hue_bins) * 1_000_000 + colorful + total


def identify_chart_images(paths):
    """
    Return {'sector_rs': Path, 'g10_proxy': Path}.
    Filename hints take precedence. Otherwise classify by image content.
    """
    paths = list(paths)
    if len(paths) != 2:
        raise ValueError("Expected exactly 2 chart screenshots")

    result = {}
    unresolved = []

    for p in paths:
        name = p.stem.lower().replace('-', ' ').replace('_', ' ')
        if 'sector' in name:
            result['sector_rs'] = p
        elif 'g10' in name or 'proxy' in name:
            result['g10_proxy'] = p
        else:
            unresolved.append(p)

    if len(result) == 2:
        return result

    if len(result) == 1 and len(unresolved) == 1:
        if 'sector_rs' in result:
            result['g10_proxy'] = unresolved[0]
        else:
            result['sector_rs'] = unresolved[0]
        return result

    scored = sorted(((chart_color_score(p), p) for p in paths), reverse=True)
    return {'sector_rs': scored[0][1], 'g10_proxy': scored[1][1]}

def find_batch():
    found={}; dates={}
    for p in INCOMING.glob('*.csv'):
        for k,rx in PATTERNS.items():
            m=rx.search(p.name)
            if m: found[k]=p; dates[k]=m.group(1); break
    if set(found)!=set(PATTERNS): return None, f'Waiting for CSVs ({len(found)}/5 found)'
    if len(set(dates.values()))!=1: return None, f'CSV dates do not match: {dates}'
    date=next(iter(dates.values()))
    imgs=[p for p in INCOMING.iterdir() if p.is_file() and p.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}]
    if len(imgs)<2: return None, 'Waiting for 2 screenshots'
    imgs=sorted(imgs,key=lambda p:p.stat().st_mtime,reverse=True)[:2]
    chart_map = identify_chart_images(imgs)
    return (date,found,chart_map), None


def crop_white_padding(im):
    rgb = im.convert('RGB')
    white = Image.new('RGB', rgb.size, (255,255,255))
    diff = ImageChops.difference(rgb, white).convert('L')
    mask = diff.point(lambda p: 255 if p > 18 else 0)
    bbox = mask.getbbox()
    return rgb.crop(bbox) if bbox else rgb

def normalize_date_images(date):
    ddir = IMAGES / date
    sector = ddir / 'sector_rs.png'
    g10 = ddir / 'g10_proxy.png'
    if not sector.exists() or not g10.exists():
        return
    tmp_sector = ddir / '__tmp_sector.png'
    tmp_g10 = ddir / '__tmp_g10.png'

    with Image.open(sector) as im:
        crop_white_padding(im).save(tmp_sector)
    with Image.open(g10) as im:
        crop_white_padding(im).save(tmp_g10)

    identified = identify_chart_images([tmp_sector, tmp_g10])

    with Image.open(identified['sector_rs']) as im:
        sector_img = im.copy()
    with Image.open(identified['g10_proxy']) as im:
        g10_img = im.copy()

    sector_img.save(sector)
    g10_img.save(g10)

    tmp_sector.unlink(missing_ok=True)
    tmp_g10.unlink(missing_ok=True)

def normalize_all_images():
    if not IMAGES.exists():
        return
    for d in IMAGES.iterdir():
        if d.is_dir():
            normalize_date_images(d.name)

def ingest(batch):
    date,found,imgs=batch
    for k,p in found.items(): shutil.copy2(p,LATEST/f'{k}.csv')
    ddir=IMAGES/date; ddir.mkdir(parents=True,exist_ok=True)
    for k,p in imgs.items():
        ext='.png'
        # Convert to PNG so HTML paths stay stable.
        with Image.open(p) as im:
            crop_white_padding(im).save(ddir/f'{k}{ext}')
    meta=json.loads(META.read_text())
    meta['latest_date']=date
    ds=set(meta.get('image_dates',[])); ds.add(date); meta['image_dates']=sorted(ds)
    META.write_text(json.dumps(meta,indent=2))
    arc=ARCHIVE/date; arc.mkdir(parents=True,exist_ok=True)
    for p in list(found.values())+list(imgs.values()):
        dest=arc/p.name
        if dest.exists(): dest.unlink()
        shutil.move(str(p),str(dest))
    return date

def render_table(k):
    p=LATEST/f'{k}.csv'
    if not p.exists(): return ''
    df=pd.read_csv(p)
    if k!='relative_volume' and Q in df.columns and T in df.columns:
        mask=df[Q].notna() & df[T].notna() & (df[Q]>df[T])
    else: mask=pd.Series(False,index=df.index)
    cols=''.join(f'<th>{html.escape(str(c))}</th>' for c in df.columns)
    rows=[]
    for i,row in df.iterrows():
        cls=' class="highlight"' if bool(mask.loc[i]) else ''
        tds=''.join(f'<td>{html.escape(fmt(c,row[c]))}</td>' for c in df.columns)
        rows.append(f'<tr{cls}>{tds}</tr>')
    stats=f'{len(df)} rows' + ('' if k=='relative_volume' else f' · {int(mask.sum())} highlighted')
    return f'''<section class="card" id="{k}"><div class="cardhead"><h2>{html.escape(TITLES[k])}</h2><div class="stats">{stats}</div></div><div class="tablewrap"><table><thead><tr>{cols}</tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>'''


def prune_image_history(max_days=5):
    """Keep only the newest max_days chart-history dates."""
    ensure()
    datedirs = [p for p in IMAGES.iterdir() if p.is_dir()]
    datedirs.sort(key=lambda p: p.name, reverse=True)

    for old_dir in datedirs[max_days:]:
        shutil.rmtree(old_dir, ignore_errors=True)

    kept = [p.name for p in datedirs[:max_days]]

    try:
        meta = json.loads(META.read_text())
    except Exception:
        meta = {}

    meta['image_dates'] = kept
    META.write_text(json.dumps(meta, indent=2))

def build_html():
    ensure()
    normalize_all_images()
    prune_image_history(5)
    meta=json.loads(META.read_text())
    # Copy accumulated images into docs.
    outimg=DOCS/'images'
    if outimg.exists(): shutil.rmtree(outimg)
    if IMAGES.exists(): shutil.copytree(IMAGES,outimg)
    tables=''.join(render_table(k) for k in ORDER)
    nav=''.join(f'<a href="#{k}">{html.escape(TITLES[k])}</a>' for k in ORDER) + '<a href="#charts">Chart History</a>'
    image_blocks=[]
    for d in sorted(meta.get('image_dates',[]), reverse=True):
        parts=[]
        for label,fn in [('Sector RS Dashboard vs SPY','sector_rs.png'),('G10 EL Proxy','g10_proxy.png')]:
            if (IMAGES/d/fn).exists(): parts.append(f'<div class="image-block"><div class="label">{label}</div><img src="images/{d}/{fn}" loading="lazy"></div>')
        if parts: image_blocks.append(f'<div class="image-date"><h3>{d}</h3>{"".join(parts)}</div>')
    sort_js = r"""<script>
(function () {
  function parseValue(raw) {
    var s = (raw || '').trim();
    if (s === '') return {type: 'empty', value: ''};

    if (/^\(.*\)$/.test(s)) s = '-' + s.slice(1, -1);

    var cleaned = s.replace(/[$,%]/g, '').replace(/,/g, '').trim();
    var m = cleaned.match(/^(-?\d+(?:\.\d+)?)\s*([KMBT])?$/i);
    if (m) {
      var n = parseFloat(m[1]);
      var suffix = (m[2] || '').toUpperCase();
      var mult = suffix === 'K' ? 1e3 :
                 suffix === 'M' ? 1e6 :
                 suffix === 'B' ? 1e9 :
                 suffix === 'T' ? 1e12 : 1;
      return {type: 'number', value: n * mult};
    }

    var time = Date.parse(s);
    if (!isNaN(time) && /[-\/]/.test(s)) {
      return {type: 'date', value: time};
    }

    return {type: 'text', value: s.toLowerCase()};
  }

  function compare(a, b, direction) {
    var av = parseValue(a);
    var bv = parseValue(b);

    if (av.type === 'empty' && bv.type === 'empty') return 0;
    if (av.type === 'empty') return 1;
    if (bv.type === 'empty') return -1;

    var result;
    if (av.type === bv.type && (av.type === 'number' || av.type === 'date')) {
      result = av.value - bv.value;
    } else {
      result = String(av.value).localeCompare(String(bv.value), undefined, {
        numeric: true,
        sensitivity: 'base'
      });
    }
    return direction === 'asc' ? result : -result;
  }

  document.querySelectorAll('table').forEach(function (table) {
    var headers = table.querySelectorAll('thead th');

    headers.forEach(function (th, columnIndex) {
      th.title = 'Click to sort';

      th.addEventListener('click', function () {
        var direction = th.getAttribute('data-sort-dir') === 'asc' ? 'desc' : 'asc';

        headers.forEach(function (h) {
          h.removeAttribute('data-sort-dir');
          h.classList.remove('sort-asc', 'sort-desc');
        });

        th.setAttribute('data-sort-dir', direction);
        th.classList.add(direction === 'asc' ? 'sort-asc' : 'sort-desc');

        var tbody = table.querySelector('tbody');
        var rows = Array.from(tbody.querySelectorAll('tr'));

        rows.sort(function (rowA, rowB) {
          var cellA = rowA.children[columnIndex];
          var cellB = rowB.children[columnIndex];
          return compare(
            cellA ? cellA.textContent : '',
            cellB ? cellB.textContent : '',
            direction
          );
        });

        rows.forEach(function (row) {
          tbody.appendChild(row);
        });
      });
    });
  });


  function storageKey(sectionId) {
    return 'tv-dashboard-hidden-columns:' + sectionId;
  }

  function readHidden(sectionId) {
    try {
      var value = JSON.parse(localStorage.getItem(storageKey(sectionId)) || '[]');
      return Array.isArray(value) ? value : [];
    } catch (e) {
      return [];
    }
  }

  function saveHidden(sectionId, hidden) {
    try {
      localStorage.setItem(storageKey(sectionId), JSON.stringify(hidden));
    } catch (e) {}
  }

  function setColumnVisible(table, columnIndex, visible) {
    table.querySelectorAll('tr').forEach(function (row) {
      var cell = row.children[columnIndex];
      if (cell) cell.style.display = visible ? '' : 'none';
    });
  }

  function applyHiddenColumns(section, table) {
    var hidden = readHidden(section.id);
    var headers = Array.from(table.querySelectorAll('thead th'));
    headers.forEach(function (_, i) {
      setColumnVisible(table, i, hidden.indexOf(i) === -1);
    });
  }

  document.querySelectorAll('section.card[id] table').forEach(function (table) {
    var section = table.closest('section.card');
    var cardhead = section.querySelector('.cardhead');
    if (!section || !cardhead) return;

    var stats = cardhead.querySelector('.stats');
    var actions = document.createElement('div');
    actions.className = 'cardhead-actions';

    if (stats) {
      stats.parentNode.insertBefore(actions, stats);
      actions.appendChild(stats);
    } else {
      cardhead.appendChild(actions);
    }

    var picker = document.createElement('div');
    picker.className = 'column-picker';

    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'column-btn';
    button.textContent = 'Columns';
    button.setAttribute('aria-expanded', 'false');

    var menu = document.createElement('div');
    menu.className = 'column-menu';

    var title = document.createElement('div');
    title.className = 'column-menu-title';
    title.textContent = 'Show / hide columns';
    menu.appendChild(title);

    var headers = Array.from(table.querySelectorAll('thead th'));
    var hidden = readHidden(section.id);

    headers.forEach(function (th, i) {
      var label = document.createElement('label');
      label.className = 'column-option';

      var checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = hidden.indexOf(i) === -1;

      var span = document.createElement('span');
      span.textContent = th.textContent.trim();

      checkbox.addEventListener('change', function () {
        var current = readHidden(section.id);
        if (checkbox.checked) {
          current = current.filter(function (x) { return x !== i; });
        } else if (current.indexOf(i) === -1) {
          current.push(i);
        }
        current.sort(function (a, b) { return a - b; });
        saveHidden(section.id, current);
        setColumnVisible(table, i, checkbox.checked);
      });

      label.appendChild(checkbox);
      label.appendChild(span);
      menu.appendChild(label);
    });

    var footer = document.createElement('div');
    footer.className = 'column-menu-footer';

    var reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'column-reset';
    reset.textContent = 'Show all';
    reset.addEventListener('click', function () {
      saveHidden(section.id, []);
      menu.querySelectorAll('input[type="checkbox"]').forEach(function (cb, i) {
        cb.checked = true;
        setColumnVisible(table, i, true);
      });
    });

    footer.appendChild(reset);
    menu.appendChild(footer);

    button.addEventListener('click', function (event) {
      event.stopPropagation();
      var opening = !menu.classList.contains('open');

      document.querySelectorAll('.column-menu.open').forEach(function (other) {
        if (other !== menu) other.classList.remove('open');
      });

      menu.classList.toggle('open', opening);
      button.setAttribute('aria-expanded', opening ? 'true' : 'false');
    });

    menu.addEventListener('click', function (event) {
      event.stopPropagation();
    });

    picker.appendChild(button);
    picker.appendChild(menu);
    actions.appendChild(picker);

    applyHiddenColumns(section, table);
  });

  document.addEventListener('click', function () {
    document.querySelectorAll('.column-menu.open').forEach(function (menu) {
      menu.classList.remove('open');
    });
    document.querySelectorAll('.column-btn').forEach(function (button) {
      button.setAttribute('aria-expanded', 'false');
    });
  });
})();
</script>"""
    page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Daily TradingView Screener Dashboard</title><style>
:root{{--bg:#0f172a;--panel:#111827;--panel2:#182235;--text:#e5e7eb;--muted:#94a3b8;--line:#334155;--yellow:#fde047;--yellowText:#111827}}*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Arial;background:var(--bg);color:var(--text)}}.wrap{{max-width:1900px;margin:0 auto;padding:24px}}h1{{margin:0 0 6px;font-size:28px}}.sub{{color:var(--muted);margin-bottom:22px}}.nav{{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 24px;position:sticky;top:0;background:rgba(15,23,42,.96);padding:10px 0;z-index:10}}.nav a{{text-decoration:none;color:var(--text);background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:13px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-bottom:24px;overflow:hidden}}.cardhead{{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line)}}.cardhead h2{{margin:0;font-size:18px}}.stats{{color:var(--muted);font-size:13px;white-space:nowrap}}.tablewrap{{overflow:auto;max-height:72vh}}table{{border-collapse:separate;border-spacing:0;min-width:100%;width:max-content;font-size:12px}}th,td{{padding:7px 9px;border-right:1px solid #263244;border-bottom:1px solid #263244;white-space:nowrap}}th{{position:sticky;top:0;background:#1e293b;z-index:2;text-align:left;font-weight:700;cursor:pointer;user-select:none;padding-right:24px}}th.sort-asc::after{{content:' ▲';position:absolute;right:7px;color:#93c5fd}}th.sort-desc::after{{content:' ▼';position:absolute;right:7px;color:#93c5fd}}th:hover{{background:#26354d}}.cardhead-actions{{display:flex;align-items:center;gap:10px}}.column-picker{{position:relative}}.column-btn{{border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:7px;padding:6px 10px;font-size:12px;cursor:pointer}}.column-btn:hover{{background:#26354d}}.column-menu{{display:none;position:absolute;right:0;top:calc(100% + 6px);z-index:30;width:min(360px,80vw);max-height:420px;overflow:auto;background:#111827;border:1px solid var(--line);border-radius:9px;box-shadow:0 14px 35px rgba(0,0,0,.45);padding:10px}}.column-menu.open{{display:block}}.column-menu-title{{font-size:12px;font-weight:700;margin:2px 4px 8px;color:#cbd5e1}}.column-option{{display:flex;align-items:flex-start;gap:8px;padding:6px 4px;font-size:12px;line-height:1.25;cursor:pointer;border-radius:5px}}.column-option:hover{{background:#1e293b}}.column-option input{{margin-top:2px;flex:0 0 auto}}.column-menu-footer{{display:flex;justify-content:flex-end;gap:8px;border-top:1px solid var(--line);margin-top:8px;padding-top:8px}}.column-reset{{border:1px solid var(--line);background:transparent;color:#cbd5e1;border-radius:6px;padding:5px 8px;font-size:11px;cursor:pointer}}tbody tr:hover td{{background:#1b273a}}tbody tr.highlight td{{background:var(--yellow);color:var(--yellowText);font-weight:600}}tbody tr.highlight:hover td{{background:#facc15}}.image-date{{margin-bottom:28px}}.image-date h3{{font-size:16px;margin:0 0 10px;color:#cbd5e1}}.image-block{{margin-bottom:14px;height:auto;min-height:0;overflow:hidden}}.image-block .label{{color:var(--muted);font-size:13px;margin-bottom:6px}}.image-block img{{display:block;width:100%;height:auto;max-height:none;object-fit:contain;border:1px solid var(--line);border-radius:8px;background:transparent}}@media(max-width:700px){{.wrap{{padding:12px}}h1{{font-size:22px}}.cardhead{{align-items:flex-start;flex-direction:column}}}}
</style></head><body><div class="wrap"><h1>Daily TradingView Screener Dashboard</h1><div class="sub">Latest screener data: <strong>{meta.get('latest_date') or 'No data uploaded yet'}</strong>. Yellow rows = Quarterly YoY revenue growth &gt; TTM YoY revenue growth.</div><div class="nav">{nav}</div>{tables}<section class="card" id="charts"><div class="cardhead"><h2>TradingView Chart History</h2><div class="stats">Images accumulate by date</div></div><div style="padding:16px">{''.join(image_blocks) or '<div class="empty">No chart images yet.</div>'}</div></section></div>{sort_js}</body></html>'''
    (DOCS/'index.html').write_text(page,encoding='utf-8')

    # Publish the generated static site to the Git repository root.
    # GitHub Pages is configured to serve main/(root).
    PUBLIC_INDEX.write_text(page, encoding='utf-8')
    if PUBLIC_IMAGES.exists():
        shutil.rmtree(PUBLIC_IMAGES)
    if IMAGES.exists():
        shutil.copytree(IMAGES, PUBLIC_IMAGES)

    return meta.get('latest_date')

def process_once():
    ensure(); batch,msg=find_batch()
    if batch:
        d=ingest(batch); build_html(); return True, f'Processed {d}. Website rebuilt.'
    build_html(); return False,msg

if __name__=='__main__':
    ok,msg=process_once(); print(msg)
