"""Cooperative native Item coverage keyed by the full offered menu path.

This supervisor drives an already-paused continuous core through control.json.
It never restores, resets, loads a game, or reads/writes native game RAM.
"""
import argparse, hashlib, json, os, sys, time
HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.abspath(os.path.join(HERE,'..','..'))
WORK=os.path.join(ROOT,'work')
sys.path[:0]=[os.path.join(ROOT,d) for d in ('lib','pce/tools','pce/harness')]
from pcestress_live import Live,norm
from pcestress import DESTINATION_MODULES

SAFE={'look','investigate','show'}
FORBIDDEN={'load','quit game','stop','end the game','save','videophone'}

def root(menu):
    labels={norm(x) for x in menu}
    return 'item' in labels and ('use metal gear' in labels or 'move' in labels)

def capture(p,label):
    if hasattr(p,'p'):
        p.p.emu.image().save(os.path.join(p.out,label+'.png'))
        open(os.path.join(p.out,label+'.mdf'),'wb').write(p.p.emu.state())
        return
    path=os.path.join(p.out,'request.json')
    if os.path.exists(path):raise RuntimeError('Native request already pending')
    json.dump({'capture':label},open(path,'w'))
    for _ in range(120):
        if os.path.exists(os.path.join(p.out,label+'.mdf')):return
        time.sleep(.1)
    raise RuntimeError('Cooperative matched capture did not finish')

def explore(p,destination,record):
    menu,_,_=p.command([])
    if not root(menu):raise RuntimeError(f'No actual scene Item root: {menu}')
    scene_menu=list(menu)
    menu,st,marker=p.command([{'choose':'Item'},{'read':6000}])
    record['offered'].append(dict(path=['Item'],menu=menu,frame=st['frame'],screenshot=marker+'.png'))
    queue=[]
    for label in menu:
        if norm(label) in SAFE:queue.append(['Item',label])
        else:record['excluded'].append(dict(path=['Item',label],reason='Outside proven safe Look/Investigate/Show actions'))
    seen=set()
    while queue:
        if len(seen)>=120:raise RuntimeError('Item coverage exceeded120 distinct native paths')
        path=queue.pop(0);key=tuple(norm(x) for x in path)
        if key in seen:continue
        seen.add(key)
        for _ in range(8):
            if root(menu):break
            menu,_,_=p.command([{'press':'b','n':1,'gap':30},{'read':600}])
        else:raise RuntimeError(f'Item root return failed at {path}: {menu}')
        complete=True
        signatures=[]
        for label in path:
            offered=next((x for x in menu if norm(x)==norm(label)),None)
            if offered is None:
                record['blocked'].append(dict(path=path,missing=label,menu=menu,frame=p.status()['frame']))
                complete=False;break
            signatures.append(tuple(norm(x) for x in menu))
            menu,st,marker=p.command([{'choose':offered},{'read':6000}])
        if not complete:continue
        rec=dict(path=path,frame=st['frame'],module=st['module'],menu=menu,screenshot=marker+'.png')
        if root(menu) or tuple(norm(x) for x in menu) in signatures:
            rec['outcome']='native action returned to scene/ancestor menu'
            record['selected'].append(rec)
        else:
            record['offered'].append(rec)
            if len(path)>=5:raise RuntimeError(f'Unexpected deep Item path: {rec}')
            for label in menu:
                if norm(label) in FORBIDDEN:
                    record['excluded'].append(dict(path=path+[label],reason='Native Save/Load/Quit/phone excluded'))
                else:queue.append(path+[label])
        json.dump(record,open(os.path.join(p.out,p.label+'-'+norm(destination).replace(' ','_')+'.json'),'w'),indent=2)
    for _ in range(8):
        if root(menu):break
        menu,_,_=p.command([{'press':'b','n':1,'gap':30},{'read':600}])
    else:raise RuntimeError('Final native Item menu return failed')
    record.update(final_menu=menu,original_scene_menu=scene_menu,completed=True)
    capture(p,p.label+f'-destination-{len(p.events)}')
    return menu

class Native:
    """The same full-path controller operating directly on the retained core."""
    def __init__(self,pilot,out,label='native-item-paths'):
        self.p,self.out,self.label,self.index=pilot,out,label,0
        self.events=[]
    def status(self):return dict(frame=self.p.frame,module=self.p.module())
    def command(self,steps):
        import pcemenu as M
        self.index+=1;marker=f'{self.label}-{self.index:04d}-{self.p.frame}'
        M.run(self.p,steps,outdir=self.out,bram=False)
        if hasattr(self.p,'confirm_arrival'):self.p.confirm_arrival()
        menu=self.p.items();st=self.status()
        self.p.emu.image().save(os.path.join(self.out,marker+'.png'))
        self.events.append(dict(frame=st['frame'],module=st['module'],menu=menu,steps=steps,screenshot=marker+'.png'))
        json.dump(self.events,open(os.path.join(self.out,self.label+'-events.json'),'w'),indent=2)
        return menu,st,marker

def native_explore(pilot,out,label='native-item-paths'):
    p=Native(pilot,out,label)
    record=dict(destination=f'module-{pilot.module()}-{pilot.frame}',offered=[],selected=[],blocked=[],excluded=[])
    explore(p,record['destination'],record)
    json.dump(record,open(os.path.join(out,label+'-result.json'),'w'),indent=2)
    return record

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--label',required=True)
    ap.add_argument('--destinations',nargs='+',default=['JUNKER HQ',"Gillian's home",'Altamira'])
    ap.add_argument('--continue-run',action='store_true')
    a=ap.parse_args();p=Live(os.path.abspath(a.out),a.label)
    initial=p.status()
    if not initial.get('continuous') or initial.get('restored'):raise RuntimeError('Requires intact continuous core')
    if not initial.get('failure'):raise RuntimeError('Requires cooperative paused core')
    result=dict(pid=initial['pid'],start_frame=initial['frame'],continuous_native_control=True,
        reset_restore_RAM_writes=False,counts_toward_completed_tour=False,arrivals=[],coverage=[])
    result['supervisor_source']=dict(path=__file__,sha256=hashlib.sha256(open(__file__,'rb').read()).hexdigest(),text=open(__file__,encoding='utf-8').read())
    for destination in a.destinations:
        if norm(destination) in {'outer heaven'}:raise RuntimeError('Story-locking destination excluded')
        offered=p.depart()
        label=next((x for x in offered if norm(x)==norm(destination)),None)
        if label is not None:menu,_,_=p.command([{'choose':label},{'read':8000}])
        else:menu=offered # The native list omits the currently parked destination.
        if 'exit tricycle' not in [norm(x) for x in menu]:raise RuntimeError(f'No native exit: {menu}')
        menu,st,marker=p.command([{'choose':'Exit Tricycle'},{'read':8000}])
        if st['module'] not in DESTINATION_MODULES[norm(destination)] or not root(menu):
            raise RuntimeError(f'Actual destination not confirmed: {destination}/{st["module"]}/{menu}')
        result['arrivals'].append(dict(destination=destination,frame=st['frame'],module=st['module'],screenshot=marker+'.png'))
        record=dict(destination=destination,offered=[],selected=[],blocked=[],excluded=[])
        result['coverage'].append(record)
        explore(p,destination,record)
        result.update(end_frame=p.status()['frame'])
        json.dump(result,open(os.path.join(p.out,a.label+'-result.json'),'w'),indent=2)
    p.depart()
    result.update(end_frame=p.status()['frame'],emulated_minutes=(p.status()['frame']-initial['frame'])/3600,completed=True,
                  exhaustive_all_game_options=False,scope='All actually discovered safe Item Look/Investigate/Show paths at specified destinations')
    json.dump(result,open(os.path.join(p.out,a.label+'-result.json'),'w'),indent=2)
    if a.continue_run:json.dump({'continue':True},open(os.path.join(p.out,'control.json'),'w'))
    print(json.dumps({k:v for k,v in result.items() if k!='supervisor_source'}),flush=True)

if __name__=='__main__':main()
