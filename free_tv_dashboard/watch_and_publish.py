import subprocess, time
from datetime import datetime
from pathlib import Path
import build_site
BASE=Path(__file__).resolve().parent

def git_push(date):
    cmds=[['git','add','.'],['git','commit','-m',f'Update dashboard {date}'],['git','push']]
    for c in cmds:
        r=subprocess.run(c,cwd=BASE,text=True,capture_output=True)
        if r.returncode!=0 and not (c[1]=='commit' and 'nothing to commit' in (r.stdout+r.stderr).lower()):
            print('Git error:',r.stdout,r.stderr); return False
    return True

print('Dashboard watcher running. Drop 5 CSVs + 2 screenshots into:', BASE/'Incoming')
last=None
while True:
    try:
        ok,msg=build_site.process_once()
        now=datetime.now().strftime('%H:%M:%S')
        if ok:
            date=build_site.json.loads(build_site.META.read_text()).get('latest_date')
            print(now,msg)
            if git_push(date): print(now,'Published to GitHub Pages.')
            time.sleep(30)
        else:
            if msg!=last: print(now,msg); last=msg
            time.sleep(5)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print('ERROR:',e); time.sleep(10)
