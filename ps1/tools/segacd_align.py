# -*- coding: utf-8 -*-
"""Pair each PS1 bank string with its Sega CD counterpart.

    python ps1/tools/segacd_align.py B010 [--sp SP06 ...] [--min 55]

The PS1 banks and the Sega CD SP files carry the same script in nearly
the same order (the lobby's lines in ISZ_B010 follow SP06's one for one),
so the pairing is a monotone alignment: a similarity matrix between our
English (the bridge - the Japanese has no direct counterpart) and the
Sega CD text, then a dynamic programme that keeps the matches in order,
gaps allowed on either side (lines the PS1 added, lines the Sega CD
rewrote). Reads work/segacd/sp_text.json (lib/segacd/sptext.py) and writes
work/segacd/align_<bank>.json:

    {"strings": [{"off", "budget", "en", "sc_file", "sc_off", "sc", "score"}, ...],
     "cues":    [{"id", "en", "sc_file", "sc_off", "sc", "score"}, ...]}

plus a review listing work/segacd/align_<bank>.txt. Voice cards align to
the Sega CD's official English PCM transcript (pcm_asr.json); consecutive
PS1 cards split from one spoken line are grouped and share its reference.
``--cues-only`` refreshes those matches without disturbing string pairs.
The review tool
(ps1/review/server.py) shows the paired line beside ours, as reference for
rewording in our own words - nothing here is copied into the data.
"""
import argparse, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import numpy as np
from rapidfuzz import fuzz, process

SP_TEXT = os.path.join(WORK, "segacd", "sp_text.json")
PCM_ASR = os.path.join(WORK, "segacd", "pcm_asr.json")
TR = os.path.join(ROOT, "ps1/translation")

# Bank -> the SP files that carry the same scenes.  Keep this explicit: the
# automatic picker is useful for discovery, but its broad pools can align a
# PS1-only line to similar wording from an unrelated scene.
SP_FOR = {
    'B000': [],
    'B010': ['SP06'],
    'B020': ['SP07'],
    'B030': ['SP04'],
    'B040': ['SP04'],
    'B050': ['SP00'],
    'B060': ['SP18'],
    'B070': ['SP18'],
    'B080': ['SP08'],
    # One PS1 dummy-file message; no meaningful Sega CD counterpart.
    'B090': [],
    'B0A0': ['SP17'],
    'B0B0': ['SP03'],
    'B0C0': ['SP09'],
    'B0D0': ['SP10'],
    'B0E0': ['SP11'],
    'B0F0': ['SP12'],
    'B100': ['SP13'],
    'B110': ['SP14'],
    'B120': ['SP15'],
    'B130': ['SP16'],
    'B140': ['SP19', 'SP20', 'SP21'],
    'B150': ['SP21'],
    'B160': ['SP22'],
    'B170': ['SP34'],
    'B180': ['SP35'],
    'B190': ['SP23'],
    'B1A0': ['SP28'],
    'B1B0': ['SP24'],
    'B1C0': ['SP25'],
    'B1D0': ['SP27'],
    'B1E0': ['SP26'],
    'B1F0': ['SP29'],
    'B200': ['SP30'],
    # These banks are voiced-only; their references come from PCM_ASR.
    'B210': [],
    'B220': ['SP32'],
    'B230': ['SP33'],
    'B240': ['SP36'],
    'B250': ['SP37'],
    'B260': [],
}

CODE = re.compile(r'＠.|<[0-9a-f]{2}>')
NAMES = {  # Sega CD wording -> the PS1's, only so the bridge scores line up
    'jordan': 'gaudi', 'random': 'randam', 'modnar': 'madnar', 'modner': 'madnar',
    'katrina': 'catherine',
    'gibsonis': 'gibson',
}


def norm(s):
    s = CODE.sub('', s).replace('￥', ' ')
    s = s.lower()
    s = re.sub(r'[^a-z0-9\' ]+', ' ', s)
    s = ' '.join(NAMES.get(w, w) for w in s.split())
    return s


def bank_strings(bank):
    d = json.load(open(os.path.join(TR, f'ISZ_{bank}.json'), encoding='utf-8'))
    return [s for s in d['strings'] if s.get('en') and not s.get('lock')]


LABEL = re.compile(r'[.!?…]|￥')


def is_label(s):
    """Verb, object and topic labels: short, no sentence punctuation, no
    line break (the review tool's string_kind rule, on the English)."""
    t = CODE.sub('', s.get('long') or s['en'])
    return not LABEL.search(t) and len(t) < 20


def label_table(sc):
    """The Sega CD keeps its labels in a sorted, uppercase table at the head
    of each file; a run of prose starts at the first line with lowercase."""
    out = []
    for s in sc:
        t = CODE.sub('', s['text'])
        if t and t == t.upper() and not LABEL.search(t):
            out.append(s)
    return out


def align(ps, sc, min_score, gap=6, force_prose=False, free_sc_ends=False):
    """Labels: best match into the Sega CD label table (their table is sorted,
    so order says nothing). Prose: monotone alignment maximising the summed
    similarity, a gap on either side costing `gap`; a pair is worth its score
    above min_score, so weak pairs are kept only where the order supports
    them (a run of lines between two anchors pairs off one for one)."""
    labels = label_table(sc)
    LB = [norm(s['text']) for s in labels]
    pairs, scores = {}, {}
    prose_idx = [i for i, s in enumerate(ps) if force_prose or not is_label(s)]
    for i, s in enumerate(ps):
        if not force_prose and is_label(s):
            r = process.extractOne(norm(s.get('long') or s['en']), LB, scorer=fuzz.ratio)
            if r and r[1] >= 80:
                pairs[i] = sc.index(labels[r[2]])
                scores[i] = int(r[1])
    sc_prose = [j for j, s in enumerate(sc) if s not in labels]
    A = [norm(ps[i].get('long') or ps[i]['en']) for i in prose_idx]
    B = [norm(sc[j]['text']) for j in sc_prose]
    sim = process.cdist(A, B, scorer=fuzz.token_set_ratio, dtype=np.uint8, workers=-1).astype(np.int32)
    sim2 = process.cdist(A, B, scorer=fuzz.ratio, dtype=np.uint8, workers=-1).astype(np.int32)
    S = np.maximum(sim2, (sim + sim2) // 2)
    n, m = S.shape
    W = S - min_score
    D = np.zeros((n + 1, m + 1), dtype=np.int32)
    D[0, :] = 0 if free_sc_ends else -gap * np.arange(m + 1)
    D[:, 0] = -gap * np.arange(n + 1)
    for i in range(1, n + 1):
        row, prev, w = D[i], D[i - 1], W[i - 1]
        for j in range(1, m + 1):
            best = max(row[j - 1], prev[j]) - gap
            v = prev[j - 1] + w[j - 1]
            row[j] = v if v > best else best
    i = n
    j = int(D[n].argmax()) if free_sc_ends else m
    while i > 0 and j > 0:
        if D[i, j] == D[i - 1, j - 1] + W[i - 1, j - 1]:
            pairs[prose_idx[i - 1]] = sc_prose[j - 1]
            scores[prose_idx[i - 1]] = int(S[i - 1, j - 1])
            i, j = i - 1, j - 1
        elif D[i, j] == D[i - 1, j] - gap:
            i -= 1
        else:
            j -= 1
    full = np.zeros((len(ps), len(sc)), dtype=np.int32)
    for a, i in enumerate(prose_idx):
        full[i, sc_prose] = S[a]
    return pairs, full, scores


def align_cues(bank, sc, min_score, gap=6):
    """The voice cards in play order against the Sega CD prose, the same
    monotone alignment as the strings: a conversation's cards sit together
    in both scripts, so the neighbours anchor a short card ('Eek! H-help
    me!') that a best-match search pairs with any line containing its
    words. Pairs under min_score are dropped after the alignment."""
    p = os.path.join(TR, f'subs_{bank}.json')
    if not os.path.exists(p):
        return []
    cues = json.load(open(p, encoding='utf-8'))['cues']
    # Cue JSON is authored in play order.  Sorting only by sector start breaks
    # multi-file/multi-channel scenes whose sector counters restart.
    order = list(range(len(cues)))
    ps = [{'en': cues[i].get('en', ''), 'budget': 0, 'off': i} for i in order]
    if not ps:
        return []
    pairs, S, scores = align(ps, sc, min_score, gap, force_prose=True)
    out = [None] * len(cues)
    for k, i in enumerate(order):
        c = cues[i]
        rec = {'id': c['id'], 'speaker': c.get('speaker', ''), 'en': c.get('en', '')}
        if k in pairs and scores[k] >= min_score:
            j = pairs[k]
            rec.update(sc_file=sc[j]['file'], sc_off=sc[j]['off'], sc=sc[j]['text'], score=scores[k])
        out[i] = rec
    return out


def pcm_lines():
    """The Sega CD's official English voice clips, ASR-transcribed in clip order."""
    if not os.path.exists(PCM_ASR):
        return []
    data = json.load(open(PCM_ASR, encoding='utf-8'))
    out = []
    for key in sorted(data, key=lambda x: int(x)):
        text = (data[key].get('text') or '').strip()
        if text:
            out.append({'file': 'PCM', 'off': int(key), 'text': text})
    return out


def align_cues_pcm(bank, min_score=55, gap=6):
    """Align voice cards to the official Sega CD English voice library.

    Consecutive cards sharing one Japanese transcript are one spoken line split
    for the PS1 subtitle box.  Align their combined English once, then attach the
    same Sega CD line to every card in the group.  Free ends find the bank's
    contiguous passage without charging for unrelated clips before/after it.
    """
    path = os.path.join(TR, f'subs_{bank}.json')
    if not os.path.exists(path):
        return []
    cues = json.load(open(path, encoding='utf-8')).get('cues', [])
    if not cues:
        return []
    groups = []
    for i, cue in enumerate(cues):
        sig = (cue.get('file'), cue.get('chan'), (cue.get('jp') or '').strip())
        if sig[2] and groups and groups[-1]['sig'] == sig:
            groups[-1]['indices'].append(i)
        else:
            groups.append({'sig': sig, 'indices': [i]})
    ps = []
    for group in groups:
        text = ' '.join(cues[i].get('en', '').strip() for i in group['indices'] if cues[i].get('en', '').strip())
        ps.append({'en': text, 'budget': 0, 'off': len(ps)})
    sc = pcm_lines()
    out = [{'id': c['id'], 'speaker': c.get('speaker', ''), 'en': c.get('en', '')} for c in cues]
    if not sc or not any(x['en'] for x in ps):
        return out
    pairs, _, scores = align(ps, sc, min_score, gap, force_prose=True, free_sc_ends=True)
    for gi, group in enumerate(groups):
        if gi not in pairs or scores[gi] < min_score:
            continue
        row = sc[pairs[gi]]
        # token-set similarity alone makes tiny overlaps look perfect
        # ("Who are you?" -> "You").  Require the full strings to retain at
        # least half their character-level shape before exposing a reference.
        if fuzz.ratio(norm(ps[gi]['en']), norm(row['text'])) < 50:
            continue
        for i in group['indices']:
            out[i].update(sc_file=row['file'], sc_off=row['off'], sc=row['text'], score=scores[gi])
    return out


def merge_cues(old, pcm):
    """Keep each cue's stronger existing SP-text or new PCM-voice reference."""
    old_by_id = {c.get('id'): c for c in old if c.get('id')}
    out = []
    for cue in pcm:
        previous = old_by_id.get(cue.get('id'), {})
        # Recompute prior PCM matches on every run; only the independently
        # generated SP-text reference is a preservation candidate.
        if (previous.get('sc_file') != 'PCM' and previous.get('sc')
                and previous.get('score', 0) >= cue.get('score', 0)):
            for key in ('sc_file', 'sc_off', 'sc', 'score'):
                if key in previous:
                    cue[key] = previous[key]
        out.append(cue)
    return out


def refresh_cue_listing(bank, cues):
    """Keep the human-readable alignment listing in step with --cues-only."""
    path = os.path.join(WORK, 'segacd', f'align_{bank}.txt')
    lines = open(path, encoding='utf-8').read().splitlines() if os.path.exists(path) else []
    lines = lines[:next((i for i, line in enumerate(lines) if line.startswith('cue  ')), len(lines))]
    for cue in cues:
        lines.append(f"cue  {cue['id']:14s} {cue.get('score', '--'):>3}  {cue['en']}")
        lines.append(f"{'':21s}  {cue.get('sc', '')}")
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write('\n'.join(lines) + '\n')


def pick_files(ps, sp_text, keep=0.45, most=None):
    """Which SP files carry a bank's scenes: each file scored by how many of
    the bank's prose lines find a close line in it; files within `keep` of
    the best are kept (a bank can span two, a file can serve two banks)."""
    A = [norm(x.get('long') or x['en']) for x in ps if not is_label(x)]
    scores = {}
    for f, lines in sp_text.items():
        B = [norm(x['text']) for x in lines if x not in label_table(lines)]
        if not B:
            continue
        S = process.cdist(A, B, scorer=fuzz.token_set_ratio, dtype=np.uint8, workers=-1)
        scores[f] = int((S.max(axis=1) >= 70).sum())
    best = max(scores.values()) or 1
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    chosen = sorted(f for f, v in (ranked[:most] if most else ranked) if v >= keep * best and v >= 8)
    return chosen, scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bank')
    ap.add_argument('--sp', nargs='*', help='SP files to align against (default: SP_FOR)')
    ap.add_argument('--gap', type=int, default=6)
    ap.add_argument('--min-cue', type=int, default=55, help='minimum similarity for a cue pair')
    ap.add_argument('--min', type=int, default=35, help='minimum similarity for a pair')
    ap.add_argument('--cues-only', action='store_true', help='refresh PCM cue references, preserving existing strings')
    a = ap.parse_args()
    old_path = os.path.join(WORK, 'segacd', f'align_{a.bank}.json')
    if a.cues_only:
        old = json.load(open(old_path, encoding='utf-8')) if os.path.exists(old_path) else {'strings': []}
        cues = merge_cues(old.get('cues', []), align_cues_pcm(a.bank, a.min_cue, a.gap))
        json.dump({'strings': old.get('strings', []), 'cues': cues}, open(old_path, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        refresh_cue_listing(a.bank, cues)
        matched = sum(bool(c.get('sc')) for c in cues)
        print(f"{a.bank}: cue refs {matched}/{len(cues)}")
        return
    sp_text = json.load(open(SP_TEXT, encoding='utf-8'))
    ps = bank_strings(a.bank)
    if a.sp:
        sps = a.sp
    elif a.bank in SP_FOR:
        sps = SP_FOR[a.bank]
    else:
        sps, fs = pick_files(ps, sp_text)
        print(f"{a.bank}: picked {sps} from " + ', '.join(f"{f}:{v}" for f, v in sorted(fs.items(), key=lambda x: -x[1])[:5]))
    sc = [dict(s, file=f) for f in sps for s in sp_text[f]]
    if sc and ps:
        pairs, S, scores = align(ps, sc, a.min, a.gap)
    else:
        pairs, S, scores = {}, None, {}
    out, lines = [], []
    hist = {'>=85': 0, '70-84': 0, '<70': 0, 'none': 0}
    for i, s in enumerate(ps):
        rec = {'off': s['off'], 'budget': s['budget'], 'en': s.get('long') or s['en']}
        if i in pairs:
            j = pairs[i]
            sc_s = sc[j]
            rec.update(sc_file=sc_s['file'], sc_off=sc_s['off'], sc=sc_s['text'], score=scores[i])
            k = '>=85' if rec['score'] >= 85 else '70-84' if rec['score'] >= 70 else '<70'
        else:
            k = 'none'
            # best candidate anyway, for the review listing
            if S is not None and len(sc):
                j = int(S[i].argmax())
                rec.update(best_file=sc[j]['file'], best_off=sc[j]['off'], best=sc[j]['text'], best_score=int(S[i, j]))
        hist[k] += 1
        out.append(rec)
        tag = f"{rec.get('score', '-'):>3}" if 'score' in rec else ' --'
        lines.append(f"{i:4d} {s['off']:6d} b{s['budget']:<4d} {tag}  {rec['en']}")
        lines.append(f"{'':21s}  {rec.get('sc', '?? ' + rec.get('best', ''))}")
    sp_cues = align_cues(a.bank, sc, a.min_cue, a.gap) if sc else []
    cues = merge_cues(sp_cues, align_cues_pcm(a.bank, a.min_cue, a.gap))
    for c in cues:
        lines.append(f"cue  {c['id']:14s} {c.get('score', '--'):>3}  {c['en']}")
        lines.append(f"{'':21s}  {c.get('sc', '')}")
    os.makedirs(os.path.join(WORK, 'segacd'), exist_ok=True)
    json.dump({'strings': out, 'cues': cues},
              open(os.path.join(WORK, 'segacd', f'align_{a.bank}.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    open(os.path.join(WORK, 'segacd', f'align_{a.bank}.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    used = set(pairs.values())
    print(f"{a.bank}: {len(ps)} strings vs {len(sc)} Sega CD lines ({', '.join(sps)}): {hist}; "
          f"{len(sc) - len(used)} Sega CD lines unpaired")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
