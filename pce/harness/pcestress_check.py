"""Explicitly restored, validation-only checks of future PCE stress controls."""
import os, sys, json, argparse
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE,'..','..'))
WORK = os.path.join(ROOT,'work')
sys.path[:0] = [os.path.join(ROOT,d) for d in ('lib','pce/tools','pce/harness')]
from pcestress import Stress

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--state',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--check',choices=['ivan-retry','ivan-retry-limit','queen-retry','queen-route','factory-route','factory-altamira','factory-listen','factory-tools','benson-word','benson-probe','phone-retry','capture','tour','late-tour','rooms'],default='ivan-retry')
    ap.add_argument('--minutes',type=int,default=5)
    a=ap.parse_args()
    p=Stress(os.path.abspath(a.out),validation_only=True)
    p.restore(os.path.abspath(a.state))
    if a.check=='capture':
        p.phase='validation-only-capture';p.step(120)
    elif a.check in ('ivan-retry','ivan-retry-limit','queen-retry'):
        p.phase='act2_g' if a.check=='queen-retry' else 'act1_f'
        p.aim=['head','centre'] if a.check=='ivan-retry-limit' else ['up','head'] if a.check=='queen-retry' else 'centre'
        p._retry_aim=list(p.aim) if isinstance(p.aim,list) else p.aim
        p.fight_count=1
        p._awaiting_fight_outcome=True
        p.step(60)
        if a.check=='ivan-retry-limit':
            try:
                p.choose('Interrogate')
            except RuntimeError as e:
                assert '3 fresh shootout retries' in str(e), str(e)
            else:
                raise AssertionError('Expected explicit bounded native retry failure')
            assert len(p.deaths)==4, p.deaths
            assert p.fight_count==4, p.fight_count
            assert p.aim==['head','centre'], p.aim
        else:
            p.choose('Look' if a.check=='queen-retry' else 'Interrogate')
            p.step(120)
            assert len(p.deaths)==1, p.deaths
            assert p.fight_count>=2 if a.check=='queen-retry' else p.fight_count==2, p.fight_count
    elif a.check=='benson-probe':
        import pcemenu as M
        p.phase='act2_e'
        M.run(p,[{'choose':'Deduce'},{'wait':300},{'shot':'before-instruction-ack'},{'save':'before-instruction-ack'}],outdir=p.out,bram=False)
        for i in range(3):
            r=p.ram();print(json.dumps(dict(i=i,keyboard_ready=M.native_keyboard_ready(p),geometry=r[0x16B0:0x16B9].hex(),objects=r[0x103E:0x1040].hex(),busy=r[M.BUSY-M.BASE],count=r[M.COUNT-M.BASE])),flush=True)
            M.run(p,[{'press':'a','n':1,'gap':90},{'shot':f'ack-{i}'},{'save':f'ack-{i}'}],outdir=p.out,bram=False)
    elif a.check=='benson-word':
        import pcemenu as M
        p.phase='act2_e'
        r=json.load(open(os.path.join(HERE,'routes','act2_e.json')))
        first=next(i for i,s in enumerate(r) if s.get('save')=='oh2_asked')+1
        M.run(p,r[first:],outdir=p.out,bram=False)
        assert p.module()==190,p.module()
    elif a.check=='phone-retry':
        p.phase='act1_c'
        route=json.load(open(os.path.join(HERE,'routes','act1_c.json')))
        p.napoleon_to_altamira(route)
        assert p.module()==398,p.module()
    elif a.check=='factory-tools':
        import pcemenu as M
        p.phase='act1_b'
        M.run(p,[{'choose':'Use Metal Gear'},{'items':1},{'shot':'offered-tools'}],outdir=p.out,bram=False)
        M.run(p,[{'press':'b','n':1,'gap':30}],outdir=p.out,bram=False)
        for leaf in ["Little's memory",'Hair','Skin tissue','Residue']*3:
            M.run(p,[{'choose':'Use Metal Gear'},{'choose':'Analysis'},{'choose':leaf},{'read':6000}],outdir=p.out,bram=False)
            print(f'{leaf}: native read-only story byte172A={p.ram()[0x172A]:02x}',flush=True)
    elif a.check=='factory-listen':
        import pcemenu as M
        p.phase='act1_b'
        M.run(p,[{'choose':'Look'},{'press':'b','n':1,'gap':30}],outdir=p.out,bram=False)
        for i in range(3):
            M.run(p,[{'choose':'Listen'},{'read':6000},{'shot':f'listen-{i}'},{'save':f'listen-{i}'}],outdir=p.out,bram=False)
            print(f'Native read-only story byte172A={p.ram()[0x172A]:02x}',flush=True)
    elif a.check in ('factory-route','factory-altamira'):
        import pcemenu as M
        p.phase='act1_b'
        route=json.load(open(os.path.join(HERE,'routes','act1_b.json')))
        first=next(i for i,s in enumerate(route) if s.get('save')=='fac_front')-7
        if a.check=='factory-altamira':
            first=next(i for i,s in enumerate(route) if s.get('save')=='factory')+1
        last=next(i for i,s in enumerate(route) if s.get('save')=='hq2')+1
        M.run(p,route[first:last],outdir=p.out,bram=False)
        assert p.module()==350,p.module()
        assert p.fight_count==1,p.fight_count
        assert not p.deaths,p.deaths
        if a.check=='factory-altamira':
            M.run(p,route[last:],outdir=p.out,bram=False)
            p.phase='act1_c'
            route=json.load(open(os.path.join(HERE,'routes','act1_c.json')))
            p.napoleon_to_altamira(route)
            assert p.module()==398,p.module()
    elif a.check=='queen-route':
        import pcemenu as M
        p.phase='act2_g'
        route=json.load(open(os.path.join(HERE,'routes','act2_g.json')))
        first=next(i for i,s in enumerate(route) if s.get('save')=='q2_switched')+1
        last=next(i for i,s in enumerate(route) if s.get('save')=='q2_d1')+1
        M.run(p,route[first:last],outdir=p.out,bram=False)
        M.wait_menu(p,limit=12000)
        assert p.module()==590,p.module()
        assert not p.retry_menu(p.menu()),p.menu()
        assert p.fight_count==2,p.fight_count
        assert not p.deaths,p.deaths
    elif a.check=='rooms':
        from pcestress_rooms import explore,Native
        p.phase='validation-rooms'
        p.subscene_coverage=explore(Native(p),p.out)
        assert len(p.subscene_coverage)==7, p.subscene_coverage
        facts=json.load(open(os.path.join(p.out,'oleen-gaudi-fact-tree-result.json')))
        assert facts['pending']==0 and len(facts['leaves'])==54, facts
    else:
        p.phase='validation-tour'
        p.tour(30 if a.check=='late-tour' else a.minutes)
    p.snapshot()
    p.emu.image().save(os.path.join(a.out,'final.png'))
    open(os.path.join(a.out,'final.mdf'),'wb').write(p.emu.state())
    json.dump(dict(validation_only=True,full_game_pass=False,check=a.check,
                   deaths=p.deaths,fights=p.fight_count,tours=p.tours,visits=p.visits),
              open(os.path.join(a.out,'result.json'),'w'),indent=2)

if __name__=='__main__':
    main()
