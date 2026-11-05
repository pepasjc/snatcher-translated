"""Bounded native exploration of Gaudi's offered fact-file tree, no typed queries."""
import argparse,os,json,sys
HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.abspath(os.path.join(HERE,'..','..'))
WORK=os.path.join(ROOT,'work')
sys.path[:0]=[os.path.join(ROOT,d) for d in ('lib','pce/tools','pce/harness')]
from pcestress_live import Live,norm

def explore(p,out):
    menu,_,_=p.command([])
    if 'history' not in [norm(x) for x in menu]:
        menu,_,_=p.command([{'press':'b'},{'read':5000}])
    if 'history' not in [norm(x) for x in menu]: raise RuntimeError(f'No native fact root: {menu}')
    roots=[x for x in menu if norm(x)!='back to menu']
    root_signature=tuple(norm(x) for x in menu)
    queue=[([x],[]) for x in roots];branches=[];leaves=[]
    while queue:
        if len(branches)+len(leaves)>=120: raise RuntimeError('Fact browser exceeded120 observed branches/leaves')
        path,ancestors=queue.pop(0)
        for _ in range(8):
            sig=tuple(norm(x) for x in menu)
            if sig==root_signature: break
            if 'back to menu' in sig:
                menu,_,_=p.command([{'choose':'Back to menu'},{'read':5000}])
            elif 'load fact file' in sig:
                menu,_,_=p.command([{'choose':'Load fact file'},{'read':5000}])
            else:
                menu,_,_=p.command([{'press':'b'},{'read':5000}])
        else: raise RuntimeError('Fact tree root return exhausted')
        traversed=[]
        for label in path:
            traversed.append(tuple(norm(x) for x in menu))
            menu,st,marker=p.command([{'choose':label},{'read':6000}])
        sig=tuple(norm(x) for x in menu)
        rec=dict(path=path,frame=st['frame'],module=st['module'],menu=menu,screenshot=marker+'.png')
        if sig in traversed or sig==root_signature or 'load fact file' in sig:
            leaves.append(rec)
        else:
            children=[x for x in menu if norm(x)!='back to menu']
            if not children: raise RuntimeError(f'Empty new fact subtree {path}: {menu}')
            branches.append(rec)
            queue.extend((path+[x],traversed) for x in children)
        json.dump(dict(branches=branches,leaves=leaves,pending=len(queue),typed_queries=False),
                  open(os.path.join(out,'oleen-gaudi-fact-tree.json'),'w'),indent=2)
    for _ in range(8):
        sig=tuple(norm(x) for x in menu)
        if sig==root_signature: break
        if 'back to menu' in sig:
            menu,_,_=p.command([{'choose':'Back to menu'},{'read':5000}])
        else:
            menu,_,_=p.command([{'press':'b'},{'read':5000}])
    else: raise RuntimeError('Completed fact traversal did not return to category root')
    json.dump(dict(branches=branches,leaves=leaves,pending=0,completed=True,typed_queries=False,
                   final_menu=menu),
              open(os.path.join(out,'oleen-gaudi-fact-tree-result.json'),'w'),indent=2)
    return menu

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',default=os.path.join(WORK,'pce','stress','continuous-v3'))
    ap.add_argument('--label',default='oleen-gaudi-facts-v2')
    a=ap.parse_args();explore(Live(a.out,a.label),a.out)
