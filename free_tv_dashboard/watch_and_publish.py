import subprocess, time
from datetime import datetime
from pathlib import Path
import build_site

BASE = Path(__file__).resolve().parent
REPO_ROOT = BASE.parent

def run_git(args):
    return subprocess.run(
        ['git'] + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True
    )

def git_push(date):
    # Add both the public GitHub Pages files and the automation/data history.
    r = run_git(['add', '-A'])
    if r.returncode != 0:
        print('Git add error:', r.stdout, r.stderr)
        return False

    r = run_git(['commit', '-m', f'Update dashboard {date}'])
    combined = (r.stdout + r.stderr).lower()
    if r.returncode != 0 and 'nothing to commit' not in combined:
        print('Git commit error:', r.stdout, r.stderr)
        return False

    # If there was nothing new, there is nothing to push.
    if 'nothing to commit' in combined:
        return True

    r = run_git(['push', 'origin', 'main'])
    if r.returncode != 0:
        print('Git push error:', r.stdout, r.stderr)
        return False
    return True

print('Dashboard watcher running.')
print('Drop 5 CSVs + 2 screenshots into:', BASE / 'Incoming')
print('Press Ctrl+C to stop.')

last = None
while True:
    try:
        ok, msg = build_site.process_once()
        now = datetime.now().strftime('%H:%M:%S')
        if ok:
            date = build_site.json.loads(build_site.META.read_text()).get('latest_date')
            print(now, msg)
            if git_push(date):
                print(now, 'Published to GitHub Pages.')
            time.sleep(30)
        else:
            if msg != last:
                print(now, msg)
                last = msg
            time.sleep(5)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print('ERROR:', e)
        time.sleep(10)
