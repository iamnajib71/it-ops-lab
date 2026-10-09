"""Reproducible Windows/local lab setup. Generates secrets only in ignored .env."""
import json
import argparse
import pathlib
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.ingest_kb import load_env

def run(*args,**kwargs):
    return subprocess.run(list(args),cwd=ROOT,check=True,**kwargs)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--measured',action='store_true',help='Enable measured winner (keyword) behind the feature flag')
    args=parser.parse_args()
    envpath=ROOT/'.env'
    if not envpath.exists():
        values={'PG_USER':'itops','PG_DB':'itops','PG_PASSWORD':secrets.token_hex(20),
          'N8N_ENCRYPTION_KEY':secrets.token_hex(32),'N8N_OWNER_EMAIL':'lab@example.invalid',
          'N8N_OWNER_PASSWORD':secrets.token_hex(16),'GRAFANA_USER':'admin',
          'GRAFANA_PASSWORD':secrets.token_hex(20),'APPROVAL_TOKEN':secrets.token_hex(24),
          'CLOUD_TIER':'off','RAG_MEASURED':'off','RAG_VARIANT':'keyword'}
        envpath.write_text(''.join(f'{k}={v}\n' for k,v in values.items()))
    if args.measured:
        lines=[s for s in envpath.read_text().splitlines() if not s.startswith(('RAG_MEASURED=','RAG_VARIANT='))]
        envpath.write_text('\n'.join(lines+['RAG_MEASURED=on','RAG_VARIANT=keyword'])+'\n')
    env=load_env()
    run('docker','compose','up','-d')
    for _ in range(60):
        p=subprocess.run(['docker','compose','exec','-T','postgres','pg_isready','-U',env['PG_USER'],'-d',env['PG_DB']],cwd=ROOT,capture_output=True)
        if p.returncode==0: break
        time.sleep(2)
    else: raise RuntimeError('Postgres did not become ready')
    # Apply schema/functions to an existing volume too.
    run('docker','compose','exec','-T','postgres','psql','-v','ON_ERROR_STOP=1','-q','-U',env['PG_USER'],'-d',env['PG_DB'],
        input=(ROOT/'db/init.sql').read_text(),text=True)
    run(sys.executable,'-u','scripts/ingest_kb.py')
    run(sys.executable,'scripts/build_workflows.py')
    credential=[{'id':'pgItOps','name':'IT Ops Postgres','type':'postgres','data':{
        'host':'postgres','port':5432,'database':env['PG_DB'],'user':env['PG_USER'],'password':env['PG_PASSWORD'],'ssl':'disable'}}]
    with tempfile.TemporaryDirectory(prefix='itops-credentials-') as temp:
        path=pathlib.Path(temp)/'credentials.json'
        path.write_text(json.dumps(credential))
        run('docker','compose','cp',str(path),'n8n:/tmp/itops-credentials.json')
        try:
            run('docker','compose','exec','-T','n8n','n8n','import:credentials','--input=/tmp/itops-credentials.json')
        finally: run('docker','compose','exec','-T','--user','0','n8n','rm','-f','/tmp/itops-credentials.json')
    run('docker','compose','exec','-T','n8n','n8n','import:workflow','--separate','--input=/import/workflows')
    for wid in ('itopsGateway001','itopsIntake00001','itopsApproval001','itopsSlaMonitor1','itopsDigest00001','itopsDigestNow01'):
        run('docker','compose','exec','-T','n8n','n8n','publish:workflow','--id='+wid)
    run('docker','compose','restart','n8n')
    for _ in range(60):
        try:
            with urllib.request.urlopen('http://localhost:5678/healthz/readiness',timeout=2) as r:
                if r.status==200:
                    # n8n opens HTTP before it registers published webhook workflows.
                    probe=subprocess.run(['docker','compose','exec','-T','postgres','psql','-X','-At',
                        '-U',env['PG_USER'],'-d',env['PG_DB']],cwd=ROOT,text=True,capture_output=True,
                        input='SELECT count(*) FROM n8n.webhook_entity WHERE "workflowId"=\'itopsIntake00001\' AND method=\'POST\';\n')
                    if probe.returncode==0 and probe.stdout.strip()=='1': break
        except OSError: pass
        time.sleep(2)
    else: raise RuntimeError('n8n did not become ready')
    print('Lab prepared. Run: python tests/run_demo.py')

if __name__=='__main__': main()
