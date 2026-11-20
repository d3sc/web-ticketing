"""Data-preserving rollout; restricted to this checkout and its existing Compose app."""
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
assert ROOT == Path('/home/tpang/documents/web-ticketing')
os.chdir(ROOT)


def capture(args):
    return subprocess.check_output(args, text=True)


def command(*args):
    subprocess.run(args, check=True)


info = json.loads(capture(['docker', 'inspect', 'web-ticketing-web-1']))[0]
assert info['Config']['Labels']['com.docker.compose.project.working_dir'] == str(ROOT)
assert info['Config']['Labels']['com.docker.compose.project.config_files'] == str(ROOT / 'compose.yaml')
assert info['NetworkSettings']['Ports']['8000/tcp'] == [{'HostIp': '127.0.0.1', 'HostPort': '5017'}]
old_image = info['Image']
original_services = dict(line.split(' ', 1) for line in capture(['docker', 'ps', '--format', '{{.Names}} {{.ID}}']).splitlines() if line)
code = '''import json,hashlib
from helpdesk import create_app,db
app=create_app()
with app.app_context():
    result={}
    for name in ['users','categories','tickets','ticket_comments','ticket_events']:
        table=db.metadata.tables[name]
        rows=[dict(r) for r in db.session.execute(table.select().order_by(*table.primary_key.columns)).mappings()]
        result[name]={'count':len(rows),'sha256':hashlib.sha256(json.dumps(rows,default=str,sort_keys=True).encode()).hexdigest()}
    print(json.dumps(result,sort_keys=True))
'''


def snapshot():
    return json.loads(capture(['docker', 'compose', 'exec', '-T', 'web', 'python', '-c', code]))


before = snapshot()
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backups = Path.home() / 'backups/web-ticketing'
backups.mkdir(parents=True, exist_ok=True, mode=0o700)
backup = backups / ('before-telegram-' + stamp + '.sql')
fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'wb') as target:
    subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'sh', '-c',
                    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --no-tablespaces --set-gtid-purged=OFF helpdesk'],
                   stdout=target, check=True)
assert backup.stat().st_size > 0
rollback_tag = 'web-ticketing:before-telegram-' + stamp.lower()
command('docker', 'image', 'tag', old_image, rollback_tag)
command('docker', 'compose', 'build', 'web')
# Existing DB stays untouched. Web entrypoint applies additive migrations.
command('docker', 'compose', 'up', '-d', '--no-deps', '--wait', '--wait-timeout', '120', 'web')
after = snapshot()
assert before == after, 'Core records changed during rollout; investigate concurrent activity, never overwrite it.'
command('docker', 'compose', 'up', '-d', '--no-deps', '--wait', '--wait-timeout', '120', 'telegram-worker')
new = json.loads(capture(['docker', 'inspect', 'web-ticketing-web-1']))[0]
worker = json.loads(capture(['docker', 'inspect', 'web-ticketing-telegram-worker-1']))[0]
output = ROOT / 'verification/telegram'
output.mkdir(parents=True, exist_ok=True)
current_services = dict(line.split(' ', 1) for line in capture(['docker', 'ps', '--format', '{{.Names}} {{.ID}}']).splitlines() if line)
unchanged_services = all(current_services.get(name) == ident for name, ident in original_services.items() if name not in ('web-ticketing-web-1', 'web-ticketing-telegram-worker-1'))
assert unchanged_services, 'An unrelated container changed during rollout; investigate without overwriting it.'
report = {'checkout': str(ROOT), 'other_containers_unchanged': unchanged_services, 'old_image': old_image, 'new_image': new['Image'],
          'rollback_tag': rollback_tag, 'backup': str(backup), 'core_data_unchanged': before == after,
          'core_counts': {name: row['count'] for name, row in before.items()},
          'web_health': new['State']['Health']['Status'], 'worker_health': worker['State']['Health']['Status']}
(output / 'deployment.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
