"""Read-only checkout/environment audit; prints no secret values."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
container = json.loads(subprocess.check_output(['docker', 'inspect', 'web-ticketing-web-1'], text=True))[0]
labels = container['Config']['Labels']
print('compose_checkout:', labels['com.docker.compose.project.working_dir'])
print('compose_config:', labels['com.docker.compose.project.config_files'])
print('image_id:', container['Image'])
files = ['helpdesk/tickets.py', 'helpdesk/admin.py', 'helpdesk/models.py']
code = 'import json,pathlib; print(json.dumps({p:pathlib.Path(p).read_text() for p in ' + repr(files) + '}))'
deployed = json.loads(subprocess.check_output(['docker', 'compose', 'exec', '-T', 'web', 'python', '-c', code], text=True))
for name in files:
    local = (ROOT / name).read_text()
    if name.endswith('models.py'):
        local = local.split('\n\nclass TelegramSettings')[0].rstrip() + '\n'
    print(name, 'deployed_matches_baseline:', local.strip() == deployed[name].strip())
env = {}
for line in (ROOT / '.env').read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, val = line.split('=', 1)
        env[key.strip()] = val.strip().strip('\"\'')
for key in ['TELEGRAM_BOT_TOKEN', 'APP_BASE_URL']:
    print(key, 'configured:', bool(env.get(key) or os.environ.get(key)))
