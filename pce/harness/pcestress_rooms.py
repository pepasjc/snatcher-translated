"""Extra native-controlled safe room coverage, separate from physical tour quota."""
import os,json,argparse,sys
HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.abspath(os.path.join(HERE,'..','..'))
WORK=os.path.join(ROOT,'work')
sys.path[:0]=[os.path.join(ROOT,d) for d in ('lib','pce/tools','pce/harness')]
from pcestress_live import Live,norm

def actions(p,menu):
    eligible={'look','investigate','ask','talk','smell','search','survey','listen','hear','item','use metal gear','do something'}
    done=set()
    for _ in range(16):
        action=next((x for x in menu if norm(x) in eligible and norm(x) not in done),None)
        if action is None: break
        done.add(norm(action))
        steps=[{'choose':action},{'read':6000}] if norm(action) in {'listen','hear','do something'} else [{'sweep':action,'rounds':1,'avoid':['Save','Videophone','Terminal']},{'read':3000}]
        menu,_,_=p.command(steps)
        if norm(action)=='do something' and all(norm(x) in {'use toilet','smell','shave'} for x in menu):
            for number,topic in enumerate(list(menu)):
                if number:p.command([{'choose':'Do something'},{'read':6000}])
                menu,_,_=p.command([{'choose':topic},{'read':8000}])
    if 'train' in [norm(x) for x in menu]:
        previous_aim=getattr(getattr(p,'p',None),'aim',None)
        menu,_,_=p.command([{'aim':'centre'},{'choose':'Train'},{'read':10000}])
        if previous_aim is not None:p.command([{'aim':previous_aim}])
    if 'use gaudi' in [norm(x) for x in menu]:
        p.command([{'choose':'Use Gaudi'},{'read':6000},
                   {'choose':"Don't use Gaudi"},{'read':6000},
                   {'choose':'Use Gaudi'},{'read':6000},{'choose':'Use card'},{'read':6000},
                   {'choose':'Load person file'},{'read':6000},
                   {'choose':'Search a name'},{'wait':300},{'type':'GILLIAN'},{'read':18000},
                   {'choose':'Stop searching'},{'read':6000},
                   {'choose':'Load fact file'},{'read':6000}])
        from pcestress_facts import explore as facts
        menu=facts(p,p.out if isinstance(p,Live) else p.p.out)
        menu,_,_=p.command([{'choose':'Back to menu'},{'read':6000},
                           {'choose':'Log off'},{'read':6000}])
    return menu

def explore(p,out):
    findings=[]
    for destination in ("Gillian's home",'JUNKER HQ'):
        menu=p.depart()
        offered=next((x for x in menu if norm(x)==norm(destination)),None)
        if offered is None:
            # Native menu omits the currently parked-at destination.
            menu,_,_=p.command([{'choose':'Exit Tricycle'},{'read':6000}])
        else:
            menu,_,_=p.command([{'choose':offered},{'read':6000},{'choose':'Exit Tricycle'},{'read':6000}])
        menu,_,_=p.command([{'choose':'Move'},{'read':6000}])
        if destination=="Gillian's home":
            if 'go inside' in [norm(x) for x in menu]:
                menu,st,marker=p.command([{'choose':'Go inside'},{'read':8000}])
                findings.append(dict(destination=destination,subscene='Go inside',frame=st['frame'],module=st['module'],menu=menu,screenshot=marker+'.png'))
                json.dump(findings,open(os.path.join(out,'oleen-subscene-coverage.json'),'w'),indent=2)
                actions(p,menu)
                menu,_,_=p.command([{'choose':'Move'},{'read':6000}])
                if 'enter bath' in [norm(x) for x in menu]:
                    menu,st,marker=p.command([{'choose':'Enter bath'},{'read':10000}])
                    findings.append(dict(destination=destination,subscene='Enter bath',frame=st['frame'],module=st['module'],menu=menu,screenshot=marker+'.png'))
                    actions(p,menu)
                    p.command([{'bram':'stress_'+os.path.basename(os.path.abspath(out))+'_oleen_bath','slot':1}])
            p.depart()
        else:
            rooms=[x for x in menu if norm(x) in {"chief's room",'mechanic room','computer room','squad room','shooting range'}]
            for room in rooms:
                menu,st,marker=p.command([{'choose':room},{'read':8000}])
                findings.append(dict(destination=destination,subscene=room,frame=st['frame'],module=st['module'],menu=menu,screenshot=marker+'.png'))
                json.dump(findings,open(os.path.join(out,'oleen-subscene-coverage.json'),'w'),indent=2)
                menu=actions(p,menu)
                if 'go out' in [norm(x) for x in menu]:
                    menu,_,_=p.command([{'choose':'Go out'},{'read':6000}])
                elif 'move' in [norm(x) for x in menu]:
                    menu,_,_=p.command([{'choose':'Move'},{'read':6000}])
                    if 'front desk' in [norm(x) for x in menu]:
                        menu,_,_=p.command([{'choose':'Front desk'},{'read':6000},{'choose':'Move'},{'read':6000}])
                if norm(room) not in [norm(x) for x in menu] and rooms[-1]!=room:
                    raise RuntimeError(f'Room departure did not return to native room list: {menu}')
            p.depart()
        json.dump(findings,open(os.path.join(out,'oleen-subscene-coverage.json'),'w'),indent=2)
    json.dump(dict(subscenes=findings,counts_as_physical_travel=False,completed=True),open(os.path.join(out,'oleen-subscene-result.json'),'w'),indent=2)
    return findings

class Native:
    def __init__(self,pilot): self.p=pilot; self.index=0
    def command(self,steps):
        import pcemenu as M
        self.index+=1;marker=f'oleen-native-subscene-{self.index:04d}-{self.p.frame}'
        M.run(self.p,steps,outdir=self.p.out,bram=False)
        self.p.confirm_arrival()
        menu=self.p.items()
        self.p.emu.image().save(os.path.join(self.p.out,marker+'.png'))
        self.p.snapshot()
        return menu,dict(frame=self.p.frame,module=self.p.module()),marker
    def depart(self): return self.p.depart()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default=os.path.join(WORK,'pce','stress','continuous-v3'))
    a=ap.parse_args();explore(Live(a.out,'oleen-subscene-coverage'),a.out)

if __name__=='__main__':main()
