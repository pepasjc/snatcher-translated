"""Continuous native PCE New Game route with live control and retained evidence."""
import os, sys, json, time, traceback, argparse, re, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
WORK = os.path.join(ROOT, 'work')
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'pce/tools', 'pce/harness')]
import pcemenu as M

DESTINATIONS = {'altamira', 'oleen hospital', 'queen hospital', "gibson's house",
                "gibson's home", "gillian's home", 'outer heaven', 'joy division',
                "ivan's house", "ivan's home", "freddy's house", "freddy's home",
                'factory ruins', 'abandoned factory', 'church', 'junkers hq', 'junker hq'}
NAVIGATION = {'forward', 'back', 'go out', 'go inside', 'board tricycle', 'exit tricycle'}
DESTINATION_MODULES = {
    'altamira':{398,494}, 'oleen hospital':{510}, 'queen hospital':{542,590},
    "gibson's house":{382,526}, "gibson's home":{382,526},
    "gillian's home":{366,574}, 'outer heaven':{430,558}, 'joy division':{414},
    "ivan's house":{446}, "ivan's home":{446}, "freddy's house":{462},
    "freddy's home":{462}, 'factory ruins':{334}, 'abandoned factory':{334},
    'church':{638,654}, 'junkers hq':{318,350,478,622}, 'junker hq':{318,350,478,622}}


def final_cue_matches(page, module, track_bcd, phase):
    """Renderer pages include colour/nameplate controls before the actual words."""
    return (module == 670 and track_bcd == 0x16 and
            (phase.startswith('act3') or phase.startswith('ending')) and
            re.search(r'(?:^|[\x00-\x1f:])\s*Right,\s+Gillian!(?=\s*(?:<|$))', page or '', re.I) is not None)


class Stress(M.Pilot):
    def __init__(self, out, validation_only=False):
        self.out = out
        os.makedirs(out, exist_ok=True)
        self.phase, self.route_index, self.step_index = 'boot', 0, 0
        self.failure = None
        self.wall_start = time.time()
        self.visits, self.choices = [], []
        self.pending_destination = None
        self.suppress_fights = False
        self.final_cue_frame = None
        self.tours = []
        self.candidate_visits = []
        self.coverage = []
        self._navigation_seen = {}
        self._final_module = None
        self.deaths = []
        self.fight_count = 0
        self._death_latched = False
        self._retry_aim = None
        self._awaiting_fight_outcome = False
        self.validation_only = validation_only
        self.restored = False
        self._handling_request = False
        super().__init__()

    def step(self, n=1, held=()):
        # After the final epilogue subtitle all controller input ceases naturally.
        if self.final_cue_frame is not None:
            held = ()
        return super().step(n, held)

    def restore(self, path):
        if not self.validation_only:
            raise RuntimeError('Continuous stress passes never restore')
        super().restore(path)
        self.restored = True

    def shootout(self):
        return False if self.suppress_fights else super().shootout()

    def fight(self, limit=8000):
        self.fight_count += 1
        self._awaiting_fight_outcome = True
        self._death_latched = False
        self._retry_aim = list(self.aim) if isinstance(self.aim,list) else self.aim
        return super().fight(limit)

    def watch(self):
        super().watch()
        if self.frame % 60 == 0:
            self.poll_request()
            if self.validation_only and self.phase=='act1_b':
                value=self.ram()[0x172A]
                previous=getattr(self,'_factory_story_byte',None)
                if value!=previous:
                    self._factory_story_byte=value
                    receipt=dict(frame=self.frame,previous=previous,value=value,menu=self.menu(),page=self.page,
                                 choice=getattr(self,'_active_choice',None))
                    with open(os.path.join(self.out,'native-story-transitions.jsonl'),'a') as f:f.write(json.dumps(receipt)+'\n')
                    stem=f'story-172a-{value:02x}-{self.frame}'
                    self.emu.image().save(os.path.join(self.out,stem+'.png'))
                    open(os.path.join(self.out,stem+'.mdf'),'wb').write(self.emu.state())
        if self.frame % 60 == 0:
            menu = self.menu()
            if self._awaiting_fight_outcome and menu and menu[1]>=3 and not self.fighting:
                self._awaiting_fight_outcome = False
            if self._awaiting_fight_outcome and menu and menu[1]==2 and M.norm(menu[2]) in {'continue','quit game','stop'}:
                if not self._death_latched:
                    self.deaths.append(dict(frame=self.frame,phase=self.phase,fight=self.fight_count))
                    self._death_latched = True
                    if isinstance(self._retry_aim,list):
                        self.aim = list(self._retry_aim)
        if self.phase.startswith(('act3','ending')) and self.frame % 60 == 0:
            detected = self.module()
            # The ending replaces the module header before the last CDDA cue.
            # Preserve actual observed story context across an unknown header;
            # a different positively identified module replaces that context.
            if isinstance(detected, int):
                self._final_module = detected
        if self.final_cue_frame is None and final_cue_matches(
                self.page, self._final_module, self.ram()[0x63B], self.phase):
            self.final_cue_frame = self.frame
            self.suppress_fights = True
            self.emu.held = set()
            self.emu.image().save(os.path.join(self.out, 'final-story-cue.png'))
            open(os.path.join(self.out,'final-story-cue.mdf'),'wb').write(self.emu.state())
            json.dump(dict(frame=self.frame,page=self.page,remembered_module=self._final_module,
                           detected_module=self.module(),track_bcd=self.ram()[0x63B],input_disabled=True),
                      open(os.path.join(self.out,'final-story-cue.json'),'w'),indent=2)
            print(f'{self.frame}: FINAL STORY CUE observed; all input disabled', flush=True)
        if self.frame % 3600 == 0:
            self.snapshot()

    def snapshot(self):
        status = dict(pid=os.getpid(), phase=self.phase, frame=self.frame,
                      emulated_minutes=round(self.frame / 3600, 2),
                      elapsed_seconds=round(time.time()-self.wall_start, 1),
                      heartbeat=time.time(), route_index=self.route_index, step_index=self.step_index,
                      menu=self.menu(), dialogue=self.page, failure=self.failure,
                      physical_visits=self.visits, choice_count=len(self.choices),
                      candidate_visits=self.candidate_visits, coverage=self.coverage,
                      deaths=self.deaths, fight_count=self.fight_count,
                      final_cue_frame=self.final_cue_frame, tours=self.tours,
                      continuous=not self.validation_only, restored=self.restored,
                      validation_only=self.validation_only)
        try:
            status['module'] = self.module()
        except Exception as e:
            status['module_error'] = str(e)
        tmp = os.path.join(self.out, 'status.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2)
        os.replace(tmp, os.path.join(self.out, 'status.json'))
        self.emu.image().save(os.path.join(self.out, 'heartbeat.png'))
        self.emu.image().save(os.path.join(self.out, f'f{self.frame:09d}.png'))
        if self.phase=='act1_b' and self.fight_count:
            open(os.path.join(self.out,f'f{self.frame:09d}.mdf'),'wb').write(self.emu.state())
        print(json.dumps({k:status[k] for k in ('phase','frame','menu','dialogue','module') if k in status}), flush=True)

    def choose(self, label, tries=30):
        self._active_choice=label
        before = self.menu()
        label_norm = M.norm(label)
        if label_norm == 'quit game':
            raise RuntimeError('Refusing native Quit game during a continuous pass')
        if self.retry_menu(before) and label_norm not in {'continue','quit game','stop'}:
            self.recover_native()
            before = self.menu()
        if before and before[1]==2 and label_norm in {'quit game','stop'}:
            raise RuntimeError('Refusing to abandon continuous game at native retry prompt')
        if label_norm=='continue' and isinstance(self._retry_aim,list):
            self.aim = list(self._retry_aim)
        scene_hash = hashlib.sha256(self.emu.image().crop((0,0,256,152)).tobytes()).hexdigest()
        if label_norm not in NAVIGATION:
            self._navigation_seen.clear()
            self._last_navigation_signature = None
        if label_norm in NAVIGATION:
            signature = (self.phase, label_norm, scene_hash)
            # A return to a previously visited HQ room is a new navigation leg.
            # Only consecutive retries in the same scene share a stall budget.
            if getattr(self,'_last_navigation_signature',None) != signature:
                self._navigation_seen.clear()
                self._last_navigation_signature = signature
            first = self._navigation_seen.setdefault(signature, self.frame)
            if self.frame-first >= 5*3600:
                raise RuntimeError(f'Navigation {label!r} repeats same scene for five emulated minutes')
        result = super().choose(label, tries)
        record = dict(frame=self.frame, phase=self.phase, label=label, before=before)
        self.choices.append(record)
        with open(os.path.join(self.out, 'choices.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps(record)+'\n')
        if label_norm in DESTINATIONS:
            self.pending_destination = label
        if label_norm == 'exit tricycle' and self.pending_destination:
            self.candidate_visits.append(dict(frame=self.frame, destination=self.pending_destination,
                                              phase=self.phase, before_scene_hash=scene_hash))
            self.pending_destination = None
        return result

    @staticmethod
    def retry_menu(menu):
        return bool(menu and menu[1]==2 and M.norm(menu[2]) in {'continue','quit game','stop'})

    def confirm_probe(self,label):
        if self.phase=='act1_b' and M.norm(label) in {'squad room',"gibson's desk",'desk drawer','disk'}:
            name=f'before-{re.sub(r"[^a-z0-9]+","-",M.norm(label))}-{self.frame}'
            self.emu.image().save(os.path.join(self.out,name+'.png'))
            open(os.path.join(self.out,name+'.mdf'),'wb').write(self.emu.state())
        if self.validation_only and M.norm(label)=='listen':
            name=f'confirm-listen-{self.frame}'
            self.emu.image().save(os.path.join(self.out,name+'.png'))
            r=self.ram()
            with open(os.path.join(self.out,'confirm-probes.jsonl'),'a') as f:
                f.write(json.dumps(dict(frame=self.frame,label=label,menu=self.menu(),native=r[0x1470:0x1485].hex()))+'\n')

    def recover_native(self, limit=3):
        """Count retries only once a genuinely new shootout starts; no restore/reset."""
        start = self.frame
        attempted = 0
        sent = 0
        while self.retry_menu(self.menu()):
            if attempted >= limit:
                raise RuntimeError(f'Native Continue failed after {limit} fresh shootout retries')
            if self.frame-start >= 6000:
                raise RuntimeError('Native Continue lingered without reliable progression')
            if isinstance(self._retry_aim,list):
                self.aim = list(self._retry_aim)
            previous = self.fight_count
            self.choose('Continue')
            sent += 1
            self.step(120)
            if M.wait_menu(self,limit=12000) is None:
                raise RuntimeError('Native Continue did not reach a stable menu within 12000 frames')
            if self.fight_count != previous:
                attempted += self.fight_count-previous
                start = self.frame
            self.coverage.append(dict(frame=self.frame,action='native Continue',
                                      presses=sent,fresh_retries=attempted,
                                      fight_count=self.fight_count,deaths=len(self.deaths)))
            self.snapshot()

    def confirm_arrival(self):
        if not self.candidate_visits:
            return None
        candidate = self.candidate_visits[-1]
        if candidate.get('checked'):
            return None
        candidate['checked'] = True
        M.wait_menu(self)
        offered = self.items()
        module = self.module()
        digest = hashlib.sha256(self.emu.image().crop((0,0,256,152)).tobytes()).hexdigest()
        expected = DESTINATION_MODULES.get(M.norm(candidate['destination']),set())
        if not M.is_verb_menu(offered) or digest == candidate['before_scene_hash'] or module not in expected:
            candidate['verification'] = 'arrival unconfirmed'
            return None
        visit = dict(frame=self.frame, destination=candidate['destination'], phase=self.phase,
                     module=module, offered=offered, scene_hash=digest, verified=True)
        visit['screenshot'] = f'arrival-{len(self.visits):04d}-{self.frame}.png'
        self.emu.image().save(os.path.join(self.out,visit['screenshot']))
        self.visits.append(visit)
        self._navigation_seen.clear()
        self.snapshot()
        return visit

    def depart(self):
        for _ in range(12):
            M.wait_menu(self)
            have = self.items()
            nh = [M.norm(x) for x in have]
            if any(x in DESTINATIONS for x in nh):
                return have
            for choice in ('board tricycle','go out','front desk','hallway','move'):
                if choice in nh:
                    self.choose(have[nh.index(choice)])
                    M.run(self,[{'read':6000}],outdir=self.out,bram=False)
                    break
            else:
                raise RuntimeError(f'No native departure from {have}')
        raise RuntimeError('Native departure exhausted twelve transitions')

    def tour(self, minutes):
        start = self.frame
        record = dict(start_frame=start, requested_minutes=minutes, arrivals_start=len(self.visits))
        self.tours.append(record)
        counts = {}
        refusals = []
        while self.frame-start < minutes*3600:
            self.phase = f'tour-{minutes}min'
            have = self.depart()
            destinations = [x for x in have if M.norm(x) in DESTINATIONS and
                            not(minutes==30 and M.norm(x) in {'junker hq','junkers hq','outer heaven'})]
            if not destinations:
                raise RuntimeError(f'No offered unlocked destinations: {have}')
            dest = min(destinations,key=lambda x:counts.get(M.norm(x),0))
            counts[M.norm(dest)] = counts.get(M.norm(dest),0)+1
            M.run(self,[{'choose':dest},{'read':8000}],outdir=self.out,bram=False)
            offered = self.items()
            if 'exit tricycle' not in [M.norm(x) for x in offered]:
                refusals.append(dict(frame=self.frame,destination=dest,menu=offered,page=self.page))
                continue
            M.run(self,[{'choose':'Exit Tricycle'},{'read':6000}],outdir=self.out,bram=False)
            visit = self.confirm_arrival()
            if not visit:
                raise RuntimeError(f'Arrival at {dest} not confirmed by native outside scene')
            eligible = {'look','investigate','ask','talk','smell','search','survey','listen','hear','item'}
            actions = [x for x in visit['offered'] if M.norm(x) in eligible]
            for action in actions:
                have = self.items()
                if M.norm(action) not in [M.norm(x) for x in have]:
                    continue
                if M.norm(action) in {'listen','hear'}:
                    steps = [{'choose':action},{'read':6000}]
                else:
                    steps = [{'sweep':action,'rounds':1},{'read':3000}]
                M.run(self,steps,outdir=self.out,bram=False)
                self.coverage.append(dict(frame=self.frame,destination=dest,action=action,
                                          offered=have,visit_frame=visit['frame']))
            offered = self.items()
            if 'use metal gear' in [M.norm(x) for x in offered]:
                M.run(self,[{'sweep':'Use Metal Gear','rounds':1,
                             'avoid':['Save','Videophone']},{'read':3000}],outdir=self.out,bram=False)
                self.coverage.append(dict(frame=self.frame,destination=dest,action='Use Metal Gear',
                                          offered=offered,excluded=['Save','Videophone'],
                                          reason='Record save/phone coverage separately from native travel',
                                          visit_frame=visit['frame']))
            self.depart()
        record.update(end_frame=self.frame, emulated_minutes=(self.frame-start)/3600,
                      arrivals=len(self.visits)-record['arrivals_start'],
                      offered_destination_attempts=counts,refusals=refusals)
        self.snapshot()
        if minutes==120:
            from pcestress_rooms import explore, Native
            self.subscene_coverage=explore(Native(self),self.out)

    def napoleon_to_altamira(self, route):
        """Bounded native candidates; success requires offered and arrived Altamira."""
        for attempt,word in enumerate(('REIGN','OVER','REIGN','OVER')):
            page_start=len(self.pages)
            if attempt==0:
                M.run(self,route[:4],outdir=self.out,bram=False)
            else:
                offered=self.items()
                hq=next((x for x in offered if 'hq' in M.norm(x)),None)
                if hq is not None:
                    M.run(self,[{'choose':hq},{'read':8000}],outdir=self.out,bram=False)
                elif not any(M.norm(x)=='exit tricycle' for x in offered):
                    raise RuntimeError(f'No native HQ exit for password retry: {offered}')
                M.run(self,[{'choose':'Exit Tricycle'},{'read':8000}],outdir=self.out,bram=False)
                if self.module()!=350:raise RuntimeError('Password retry did not actually return to HQ')
                M.run(self,[
                    {'choose':'Move'},{'choose':'Mechanic room'},{'read':6000},
                    {'choose':'Use Metal Gear'},{'choose':'Videophone'},{'press':'a','n':1,'gap':40},
                    {'choose':'Call'},{'dial':'395644'},{'read':8000},{'choose':'Answer'},{'wait':300}],outdir=self.out,bram=False)
            question_pages=self.pages[page_start:]
            question_text=' '.join(M.norm(x) for x in question_pages)
            recognized=False
            if 'revolution is?' in question_text:
                word='OVER';recognized=True
            elif 'hundred days' in question_text:
                word='REIGN';recognized=True
            M.run(self,[{'shot':f'napoleon-question-{attempt}'},{'type':word},{'read':6000}],outdir=self.out,bram=False)
            M.run(self,route[6:16],outdir=self.out,bram=False)
            offered=self.items()
            unlocked=any(M.norm(x)=='altamira' for x in offered)
            receipt=dict(frame=self.frame,candidate=word,attempt=attempt,offered=offered,
                         outcome='destination unlocked' if unlocked else 'destination remains locked',
                         question_recognized=recognized,question_pages=question_pages,
                         validation_only=self.validation_only,
                         observed_pages=self.pages[page_start:])
            with open(os.path.join(self.out,'napoleon-password-attempts.jsonl'),'a',encoding='utf-8') as f:f.write(json.dumps(receipt)+'\n')
            if unlocked:
                M.run(self,route[16:21],outdir=self.out,bram=False)
                if self.module()!=398:raise RuntimeError('Altamira arrival was not confirmed')
                self.confirm_arrival();self.snapshot();return
        raise RuntimeError('Four native Napoleon candidates left Altamira locked')

    def poll_request(self):
        path=os.path.join(self.out,'request.json')
        if self._handling_request or not os.path.exists(path):
            return
        self._handling_request=True
        held=set(self.emu.held)
        try:
            command=json.load(open(path,encoding='utf-8'))
            if command.get('pause') and self.failure is None and held:
                return  # Keep queued until the current native button hold is released.
            os.replace(path,os.path.join(self.out,f'request_{time.time_ns()}.json'))
            label=command.get('capture','cooperative-capture')
            if not re.fullmatch(r'[A-Za-z0-9_-]+',label):
                raise ValueError('Unsafe capture label')
            self.snapshot()
            self.emu.image().save(os.path.join(self.out,label+'.png'))
            open(os.path.join(self.out,label+'.mdf'),'wb').write(self.emu.state())
            if command.get('pause') and self.failure is None:
                self.emu.held=set()
                self._handling_request=False
                self.control('Cooperative native pause')
        except KeyboardInterrupt:
            self.control('Interrupted; native core retained')
        finally:
            self.emu.held=held if self.final_cue_frame is None else set()
            self._handling_request=False

    def control(self, reason):
        self.failure = reason
        self.snapshot()
        open(os.path.join(self.out, f'pause_{self.frame}.mdf'), 'wb').write(self.emu.state())
        path = os.path.join(self.out, 'control.json')
        while True:
            try:
                self.poll_request()
                if os.path.exists(path):
                    command = json.load(open(path, encoding='utf-8'))
                    os.replace(path, os.path.join(self.out, f'control_{time.time_ns()}.json'))
                    if 'steps' in command:
                        M.run(self, command['steps'], outdir=self.out, bram=False)
                    if 'tour' in command:
                        self.tour(command['tour'])
                    if 'skip' in command:
                        self.step_index += command['skip']
                    if command.get('continue'):
                        self.failure = None
                        self.snapshot()
                        return
                    self.snapshot()
                # Idle controls retain the exact core and advance no emulated frames.
                time.sleep(1)
                if int(time.time()) % 10 == 0:
                    self.snapshot()
            except KeyboardInterrupt:
                self.snapshot()
            except BaseException:
                traceback.print_exc()
                self.snapshot()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(WORK, 'pce', 'stress', time.strftime('%Y%m%d-%H%M%S')))
    args = ap.parse_args()
    p = Stress(os.path.abspath(args.out))
    schedule = {1000:['start'], 1200:[], 4900:['a'], 4930:[]}
    for f in range(32000,35600,90):
        schedule[f]=['a']; schedule[f+8]=[]
    held=[]
    while p.frame < 35700:
        held=schedule.get(p.frame,held)
        p.step(1,held)
    p.snapshot()
    # act1_b includes its own full reception/HQ intro and repaired factory route.
    names = [f'act1_{c}' for c in 'bcdefg'] + [f'act2_{c}' for c in 'abcdefghi'] + ['act3_a','act3_b']
    for ri,name in enumerate(names):
        p.phase,p.route_index,p.step_index=name,ri,0
        route=json.load(open(os.path.join(HERE,'routes',name+'.json'),encoding='utf-8'))
        # act2_i already crosses naturally into Act 3; do not replay its save choice.
        if name=='act3_a':
            route=route[3:]
        while p.step_index < len(route):
            if name=='act1_c' and p.step_index==0:
                try:
                    p.napoleon_to_altamira(route)
                    p.step_index=21
                except BaseException as e:
                    traceback.print_exc();p.control(f'Native Napoleon/Altamira: {e}')
                continue
            st=route[p.step_index]
            print(f'{p.frame}: {name}[{p.step_index}] {st}',flush=True)
            try:
                if st.get('save')=='fac_won' and p.fight_count<1:
                    raise RuntimeError('Factory victory requires a naturally observed shootout')
                if st.get('save')=='hq2' and p.module()!=350:
                    raise RuntimeError('Factory return has not actually reached HQ module350')
                M.run(p,[st],outdir=p.out,bram=False)
                if 'read' in st or 'wait' in st:
                    p.confirm_arrival()
            except BaseException as e:
                traceback.print_exc()
                p.control(f'{name}[{p.step_index}]: {e}')
                continue
            p.step_index+=1
            if name=='act2_b' and st.get('save')=='oleen_done':
                try:
                    p.tour(120)
                except BaseException as e:
                    traceback.print_exc(); p.control(f'Oleen tour: {e}')
                p.phase=name
        p.snapshot()
        # Entering Outer Heaven commits to the BENSON deduction and forces HQ.
        # The last freely traversable native cockpit is after Queen Hospital.
        if name=='act2_d':
            try:
                p.tour(30)
            except BaseException as e:
                traceback.print_exc(); p.control(f'Latest free travel before BENSON: {e}')
    p.phase='ending-verification'
    p.control('Review ending cue and credits before final no-input hold')
    if p.final_cue_frame is None:
        p.failure='Final story cue was not naturally observed; ending proof incomplete'
        p.snapshot()
        raise RuntimeError(p.failure)
    p.suppress_fights=True
    p.phase='ending-no-input'
    p.step(max(36000, (p.final_cue_frame or p.frame)+36000-p.frame))
    p.phase='complete'
    p.snapshot()
    open(os.path.join(p.out,'final.mdf'),'wb').write(p.emu.state())

if __name__=='__main__':
    main()
