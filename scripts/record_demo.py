"""Record real subprocess output in asciinema v2 format; render with agg.

Long runs are compressed to 60 seconds and clearly labelled. Nothing is scripted
as a pretend model response: every output event comes from a real command.
"""
import json
import pathlib
import subprocess
import sys
import time
ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    events=[]; started=time.monotonic()
    commands=[[sys.executable,'-u','tests/run_demo.py'],[sys.executable,'eval/run_retrieval.py','--summary'],[sys.executable,'-m','pytest','-q']]
    for cmd in commands:
        events.append([time.monotonic()-started,'o','\r\n\x1b[36mPS> '+ ' '.join(['python']+cmd[1:])+'\x1b[0m\r\n'])
        p=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        for line in p.stdout:
            print(line,end='',flush=True)
            events.append([time.monotonic()-started,'o',line.replace('\n','\r\n')])
        if p.wait()!=0: raise RuntimeError('Demo command failed: '+str(cmd))
    elapsed=time.monotonic()-started
    factor=min(1,55/max(elapsed,1))
    events=[[round(t*factor+3,3),kind,data] for t,kind,data in events]
    events.insert(0,[0,'o','IT OPS LAB | Real local run | Playback time compressed\r\n'])
    events.append([max(30,events[-1][0]+5),'o','\r\nAll commands passed. Runs locally; no paid APIs.\r\n'])
    target=ROOT/'docs/demo.cast'
    target.write_text('\n'.join(json.dumps(x) for x in [{'version':2,'width':120,'height':32,'timestamp':int(time.time()),'env':{'TERM':'xterm-256color'}}]+events)+'\n',encoding='utf-8')
    (ROOT/'docs/demo-recording.json').write_text(json.dumps({'duration_s':elapsed,'playback_factor':factor,'commands':[['python']+c[1:] for c in commands]},indent=2))
    print('Saved',target)

if __name__=='__main__': main()
