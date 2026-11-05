"""Freeze source receipts and launch a cold New Game stress process without a console."""
import os,sys,json,argparse,hashlib,pathlib,subprocess,datetime
HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.abspath(os.path.join(HERE,'..','..'))
WORK=os.path.join(ROOT,'work')
sys.path[:0]=[os.path.join(ROOT,d) for d in ('lib','pce/tools','pce/harness')]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args()
    out=pathlib.Path(a.out).resolve()
    if out.exists():raise RuntimeError('Fresh stress output must not exist')
    out.mkdir(parents=True)
    base=pathlib.Path(ROOT)
    paths=sorted(pathlib.Path(HERE).glob('*.py'))+sorted((pathlib.Path(HERE)/'routes').glob('*.json'))
    sources={str(p.relative_to(base)):dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),text=p.read_text(encoding='utf-8')) for p in paths}
    image=base/'patched/pce/snatcher_pce.bin';cue=image.with_suffix('.cue')
    receipt=dict(generated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
        whole_game_from='Cold native New Game',restore_reset_RAM_injection=False,
        source_frozen_for_run=True,sources=sources,
        image=dict(path=str(image),sha256=hashlib.file_digest(image.open('rb'),'sha256').hexdigest()),
        cue=dict(path=str(cue),sha256=hashlib.sha256(cue.read_bytes()).hexdigest()),
        late_tour_checkpoint='After Queen before entering Outer Heaven; HQ/Outer Heaven excluded')
    (out/'source-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    stdout=(out/'stdout.log').open('wb');stderr=(out/'stderr.log').open('wb')
    p=subprocess.Popen([sys.executable,os.path.join(HERE,'pcestress.py'),'--out',str(out)],cwd=ROOT,
        stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    (out/'launch.json').write_text(json.dumps(dict(pid=p.pid,command='pcestress.py --out '+str(out),native_control='request.json/control.json; no console signals'),indent=2),encoding='utf-8')
    print(json.dumps(dict(pid=p.pid,out=str(out)),indent=2))
if __name__=='__main__':main()
