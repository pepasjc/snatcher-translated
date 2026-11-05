"""Restored native checkpoints for future source; never a full-game pass."""
import argparse,hashlib,json,os,sys
HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.abspath(os.path.join(HERE,'..','..'))
WORK=os.path.join(ROOT,'work')
sys.path[:0]=[os.path.join(ROOT,x) for x in ('lib','pce/tools','pce/harness')]
import pcemenu as M
from pcestress import Stress,final_cue_matches

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--check',required=True,choices=['hospital','queen','chief','quiz','item','ending','save-prompt'])
    ap.add_argument('--state',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    p=Stress(os.path.abspath(a.out),validation_only=True);p.restore(os.path.abspath(a.state));p.phase='act3-validation' if a.check=='ending' else 'validation-'+a.check
    receipt=dict(validation_only=True,full_game_pass=False,restored_from=os.path.abspath(a.state),check=a.check,
        sources={f:hashlib.sha256(open(os.path.join(HERE,f),'rb').read()).hexdigest() for f in ('pcestress.py','pcemenu.py','pcestress_items.py')})
    json.dump(receipt,open(os.path.join(p.out,'source-receipt.json'),'w'),indent=2)
    if a.check=='hospital':
        M.run(p,[{'hospital_list_keyboard':True},{'type':'QUEEN'},{'read':12000},{'choose':'Check the list'},{'read':600}],outdir=p.out,bram=False)
        assert any(M.norm(x)=='its address' for x in p.items()),p.items()
    elif a.check=='queen':
        p.phase='act2_g';route=json.load(open(os.path.join(HERE,'routes','act2_g.json')))
        first=next(i for i,s in enumerate(route)if s.get('save')=='q2_switched')+1
        last=next(i for i,s in enumerate(route)if s.get('save')=='q2_d2')+1
        M.run(p,route[first:last],outdir=p.out,bram=False)
        assert p.module()==590 and p.fight_count==2 and not p.deaths,(p.module(),p.fight_count,p.deaths)
    elif a.check=='chief':
        p.phase='act2_i';route=json.load(open(os.path.join(HERE,'routes','act2_i.json')))
        first=next(i for i,s in enumerate(route)if s.get('save')=='hq6_rooms')+1
        last=next(i for i,s in enumerate(route[first:],first)if s.get('choose')=='Desk')
        M.run(p,route[first:last],outdir=p.out,bram=False)
        assert any(M.norm(x)=='desk' for x in p.items()),p.items()
    elif a.check=='quiz':
        route=json.load(open(os.path.join(HERE,'routes','act3_a.json')))
        first=next(i for i,s in enumerate(route)if s.get('choose')=='UV rays')
        M.run(p,route[first:first+2],outdir=p.out,bram=False)
        assert any(M.norm(x)=='underpass' for x in p.items()),p.items()
    elif a.check=='item':
        from pcestress_items import native_explore
        r=native_explore(p,p.out,'full-item-check')
        paths={tuple(M.norm(x)for x in z['path']) for z in r['selected']}
        assert ('item','look','junker id') in paths and ('item','investigate','junker id') in paths,paths
        assert len(paths)>=14 and not r['blocked'],r
        receipt['item_paths']=len(paths)
    elif a.check=='save-prompt':
        # A past fight is not evidence that an ordinary Save/Continue prompt
        # is a death. Exercise the actual native BRAM save confirmation.
        p.fight_count=4
        M.run(p,[{'read':1200},{'bram':'validation_future_save_prompt','slot':1}],outdir=p.out,bram=False)
        assert not p.deaths and p.fight_count==4,(p.deaths,p.fight_count)
    else:
        # Positive story context is acquired by real native progression, never
        # initialized from a restored credit screen or written into game RAM.
        p.phase='act3-validation'
        M.run(p,[{'choose':'Investigate'},{'choose':'Terminal'},{'read':60000}],outdir=p.out,bram=False)
        for _ in range(4):
            if p.final_cue_frame is not None:break
            M.run(p,[{'read':60000}],outdir=p.out,bram=False)
        assert p.final_cue_frame is not None,'No naturally observed final cue'
        cue=p.final_cue_frame;p.step(36000)
        receipt.update(final_cue_frame=cue,no_input_tail_frames=36000,ending_context=p._final_module)
    p.snapshot();p.emu.image().save(os.path.join(p.out,'final.png'))
    open(os.path.join(p.out,'final.mdf'),'wb').write(p.emu.state())
    receipt.update(passed=True,frame=p.frame,module=p.module(),fights=p.fight_count,deaths=p.deaths)
    json.dump(receipt,open(os.path.join(p.out,'result.json'),'w'),indent=2);print(json.dumps(receipt),flush=True)

if __name__=='__main__':main()
