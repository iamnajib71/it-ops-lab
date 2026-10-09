"""One-time, verified migration from byte hashes to canonical LF text hashes.

Keeps original provenance in hash_migrations; never changes embeddings or outputs.
"""
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from eval.core import ROOT, digest

def main():
    inputs={'kb_sha256':list((ROOT/'kb').glob('*.md')),
      'questions_sha256':[ROOT/'eval/questions.jsonl'],
      'prompts_sha256':list((ROOT/'eval/prompts').glob('*.txt')),
      'sql_sha256':[ROOT/'db/init.sql']}
    for path in (ROOT/'eval/fixtures').glob('*.json'):
        data=json.loads(path.read_text()); before=dict(data['provenance']); updates={}
        for key,paths in inputs.items():
            legacy=hashlib.sha256()
            for p in sorted(paths): legacy.update(p.name.encode()); legacy.update(p.read_bytes())
            canonical=digest(paths)
            if before[key] not in (legacy.hexdigest(),canonical): raise ValueError('Inputs changed; cannot migrate '+key)
            updates[key]=canonical
        data.setdefault('hash_migrations',[]).append({'method':'CRLF to LF hashing only; inputs verified against original byte hashes','original_provenance':before})
        data['provenance'].update(updates)
        path.write_text(json.dumps(data,indent=2),encoding='utf-8')
        print('Canonicalized',path.name)

if __name__=='__main__': main()
