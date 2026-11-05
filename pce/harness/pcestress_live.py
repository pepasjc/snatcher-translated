"""External native-control tour supervisor; never attaches to or changes game RAM."""
import argparse, ast, json, os, time, hashlib
HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.abspath(os.path.join(HERE,'..','..'))
WORK=os.path.join(ROOT,'work')
from pcestress import DESTINATIONS, DESTINATION_MODULES

def norm(s): return ' '.join(s.lower().split())

class Live:
    def __init__(self,out,label):
        self.out=out; self.label=label; self.index=0; self.events=[]
    def status(self):
        for _ in range(20):
            try: return json.load(open(os.path.join(self.out,'status.json')))
            except (ValueError,OSError): time.sleep(.1)
        raise RuntimeError('No readable native status')
    def command(self,steps):
        self.index+=1
        marker=f'{self.label}-{self.index:04d}'
        steps=steps+[{'items':1},{'shot':marker}]
        path=os.path.join(self.out,'control.json')
        if os.path.exists(path): raise RuntimeError('Existing command pending')
        json.dump({'steps':steps},open(path,'w'),indent=2)
        deadline=time.time()+180
        while not os.path.exists(os.path.join(self.out,marker+'.png')):
            if time.time()>deadline: raise RuntimeError(f'Native command did not finish: {steps}')
            time.sleep(1)
        time.sleep(1)
        text=open(os.path.join(self.out,'stdout.log'),encoding='utf-8').read()
        lines=[x.split(': items ',1)[1] for x in text.splitlines() if ': items ' in x]
        offered=ast.literal_eval(lines[-1])
        st=self.status()
        event=dict(index=self.index,frame=st['frame'],module=st['module'],menu=offered,
                   screenshot=marker+'.png',steps=steps[:-2])
        self.events.append(event)
        json.dump(self.events,open(os.path.join(self.out,self.label+'-events.json'),'w'),indent=2)
        print(json.dumps(event),flush=True)
        return offered,st,marker
    def depart(self):
        menu,st,_=self.command([])
        for _ in range(12):
            n=[norm(x) for x in menu]
            if any(x in DESTINATIONS for x in n): return menu
            choice=next((x for x in ('board tricycle','go out','front desk','hallway','move') if x in n),None)
            if choice is None: raise RuntimeError(f'No departure: {menu}')
            menu,st,_=self.command([{'choose':menu[n.index(choice)]},{'read':6000}])
        raise RuntimeError('Twelve departure transitions exhausted')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',default=os.path.join(WORK,'pce','stress','continuous-v3'))
    ap.add_argument('--label',required=True)
    ap.add_argument('--start-frame',type=int,required=True)
    ap.add_argument('--minutes',type=int,required=True)
    ap.add_argument('--exclude-hq',action='store_true')
    a=ap.parse_args(); p=Live(os.path.abspath(a.out),a.label)
    counts={}; arrivals=[]; coverage=[]
    while p.status()['frame']-a.start_frame<a.minutes*3600:
        menu=p.depart()
        destinations=[x for x in menu if norm(x) in DESTINATIONS and
                      not(a.exclude_hq and norm(x) in {'junker hq','junkers hq'})]
        if not destinations: raise RuntimeError(f'No eligible offered destinations {menu}')
        dest=min(destinations,key=lambda x:counts.get(norm(x),0))
        counts[norm(dest)]=counts.get(norm(dest),0)+1
        menu,st,_=p.command([{'choose':dest},{'read':8000}])
        if 'exit tricycle' not in [norm(x) for x in menu]:
            raise RuntimeError(f'Offered destination refused: {dest}, {menu}')
        cockpit=open(os.path.join(p.out,p.label+f'-{p.index:04d}.png'),'rb').read()
        menu,st,marker=p.command([{'choose':'Exit Tricycle'},{'read':6000}])
        image=open(os.path.join(p.out,marker+'.png'),'rb').read()
        if st['module'] not in DESTINATION_MODULES[norm(dest)] or image==cockpit:
            raise RuntimeError(f'Unconfirmed arrival {dest}: {st}')
        arrivals.append(dict(destination=dest,frame=st['frame'],module=st['module'],screenshot=marker+'.png'))
        eligible={'look','investigate','ask','talk','smell','search','survey','listen','hear','item','use metal gear'}
        for action in [x for x in menu if norm(x) in eligible]:
            steps=[{'choose':action},{'read':6000}] if norm(action) in {'listen','hear'} else [{'sweep':action,'rounds':1,'avoid':['Save','Videophone','Terminal']},{'read':3000}]
            _,st,marker=p.command(steps)
            coverage.append(dict(destination=dest,action=action,frame=st['frame'],screenshot=marker+'.png'))
        json.dump(dict(start_frame=a.start_frame,requested_minutes=a.minutes,frame=st['frame'],
                       arrivals=arrivals,coverage=coverage,offered_counts=counts),
                  open(os.path.join(p.out,a.label+'-coverage.json'),'w'),indent=2)
    p.depart()
    json.dump(dict(start_frame=a.start_frame,end_frame=p.status()['frame'],
                   minutes=(p.status()['frame']-a.start_frame)/3600,arrivals=arrivals,
                   coverage=coverage,offered_counts=counts,continuous_native_control=True),
              open(os.path.join(p.out,a.label+'-result.json'),'w'),indent=2)

if __name__=='__main__': main()
