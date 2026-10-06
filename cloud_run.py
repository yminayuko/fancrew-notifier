"""One bounded Actions run; persist a stop flag when the site restricts access."""
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parent
mode=os.environ.get('MODE','monitor')
if mode not in ('monitor','resume','test-notification'):
    raise SystemExit('Invalid mode')
if mode=='test-notification':
    raise SystemExit(subprocess.call([sys.executable,str(root/'fancrew_notifier.py'),'--test-notification']))
if mode=='resume':
    (root/'STOPPED').unlink(missing_ok=True)
if (root/'STOPPED').exists():
    print('監視は停止中です。原因解消後にresumeで手動実行してください。')
    raise SystemExit(0)
result=subprocess.call([sys.executable,str(root/'fancrew_notifier.py'),'--once','--max-details','120'])
if result==2:
    (root/'STOPPED').write_text('Site access restriction detected. Manual resume required.\n')
raise SystemExit(result)
