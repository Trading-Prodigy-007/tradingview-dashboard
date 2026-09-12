import json, re, shutil, time, html
from pathlib import Path
from datetime import datetime
import pandas as pd
from PIL import Image

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
    dims=[]
    for p in imgs:
        with Image.open(p) as im: dims.append((p,im.height))
    dims.sort(key=lambda x:x[1])
    return (date,found,{'sector_rs':dims[0][0],'g10_proxy':dims[1][0]}), None

def ingest(batch):
    date,found,imgs=batch
    for k,p in found.items(): shutil.copy2(p,LATEST/f'{k}.csv')
    ddir=IMAGES/date; ddir.mkdir(parents=True,exist_ok=True)
    for k,p in imgs.items():
        ext='.png'
        # Convert to PNG so HTML paths stay stable.
        with Image.open(p) as im: im.convert('RGB').save(ddir/f'{k}{ext}')
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

def build_html():
    ensure()
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
    page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Daily TradingView Screener Dashboard</title><style>
:root{{--bg:#0f172a;--panel:#111827;--panel2:#182235;--text:#e5e7eb;--muted:#94a3b8;--line:#334155;--yellow:#fde047;--yellowText:#111827}}*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Arial;background:var(--bg);color:var(--text)}}.wrap{{max-width:1900px;margin:0 auto;padding:24px}}h1{{margin:0 0 6px;font-size:28px}}.sub{{color:var(--muted);margin-bottom:22px}}.nav{{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 24px;position:sticky;top:0;background:rgba(15,23,42,.96);padding:10px 0;z-index:10}}.nav a{{text-decoration:none;color:var(--text);background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:13px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-bottom:24px;overflow:hidden}}.cardhead{{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line)}}.cardhead h2{{margin:0;font-size:18px}}.stats{{color:var(--muted);font-size:13px;white-space:nowrap}}.tablewrap{{overflow:auto;max-height:72vh}}table{{border-collapse:separate;border-spacing:0;min-width:100%;width:max-content;font-size:12px}}th,td{{padding:7px 9px;border-right:1px solid #263244;border-bottom:1px solid #263244;white-space:nowrap}}th{{position:sticky;top:0;background:#1e293b;z-index:2;text-align:left;font-weight:700}}tbody tr:hover td{{background:#1b273a}}tbody tr.highlight td{{background:var(--yellow);color:var(--yellowText);font-weight:600}}tbody tr.highlight:hover td{{background:#facc15}}.image-date{{margin-bottom:28px}}.image-date h3{{font-size:16px;margin:0 0 10px;color:#cbd5e1}}.image-block{{margin-bottom:14px}}.image-block .label{{color:var(--muted);font-size:13px;margin-bottom:6px}}.image-block img{{width:100%;border:1px solid var(--line);border-radius:8px;display:block;background:#020617}}@media(max-width:700px){{.wrap{{padding:12px}}h1{{font-size:22px}}.cardhead{{align-items:flex-start;flex-direction:column}}}}
</style></head><body><div class="wrap"><h1>Daily TradingView Screener Dashboard</h1><div class="sub">Latest screener data: <strong>{meta.get('latest_date') or 'No data uploaded yet'}</strong>. Yellow rows = Quarterly YoY revenue growth &gt; TTM YoY revenue growth.</div><div class="nav">{nav}</div>{tables}<section class="card" id="charts"><div class="cardhead"><h2>TradingView Chart History</h2><div class="stats">Images accumulate by date</div></div><div style="padding:16px">{''.join(image_blocks) or '<div class="empty">No chart images yet.</div>'}</div></section></div></body></html>'''
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
