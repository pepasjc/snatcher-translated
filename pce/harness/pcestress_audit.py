"""Read-only evidence ledger for a retained PCE stress run; never opens a core."""
import os, sys, json, argparse
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE,'..','..'))
WORK = os.path.join(ROOT,'work')
sys.path[:0] = [os.path.join(ROOT,d) for d in ('lib','pce/tools','pce/harness')]
from pcestress import DESTINATIONS, DESTINATION_MODULES
from pcemenu import norm


def audit(directory):
    choices = [json.loads(line) for line in open(os.path.join(directory,'choices.jsonl'),encoding='utf-8')]
    snapshots = []
    for line in open(os.path.join(directory,'stdout.log'),encoding='utf-8'):
        if line.startswith('{'):
            try:
                item=json.loads(line)
                if 'module' in item and 'frame' in item:
                    snapshots.append(item)
            except ValueError:
                pass
    pending=None
    visits=[]
    for item in choices:
        label=norm(item['label'])
        if label in DESTINATIONS:
            pending=item
        if label!='exit tricycle' or pending is None:
            continue
        expected=DESTINATION_MODULES.get(norm(pending['label']),set())
        matches=[s for s in snapshots if item['frame']<=s['frame']<=item['frame']+7200
                 and s.get('module') in expected]
        evidence=matches[0] if matches else None
        visits.append(dict(destination=pending['label'],destination_choice_frame=pending['frame'],
                           native_exit_frame=item['frame'],phase=item['phase'],
                           module_evidence=evidence,
                           screenshot=f"f{evidence['frame']:09d}.png" if evidence else None,
                           manual_reviewed=False,classification='candidate: review native scene'))
        pending=None
    status=json.load(open(os.path.join(directory,'status.json'),encoding='utf-8'))
    result=dict(run=directory,read_only_audit=True,status=status,arrival_candidates=visits,
                unique_destinations=sorted(set(x['destination'] for x in visits)),
                attempted_choice_count=len(choices),
                successful_ending_claim=False,
                caveat='Exit choices need settled scene/screenshot review; rooms, maps and phone are not travel.')
    with open(os.path.join(directory,'audit.json'),'w',encoding='utf-8') as f:
        json.dump(result,f,indent=2)
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('directory')
    a=ap.parse_args()
    result=audit(os.path.abspath(a.directory))
    print(json.dumps({k:result[k] for k in ('unique_destinations','attempted_choice_count','successful_ending_claim')}))

if __name__=='__main__':
    main()
