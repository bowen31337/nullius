import os, json, sys
from concurrent.futures import ThreadPoolExecutor
src = open('run.py').read().split('jobs = [')[0]
ns = {'__file__': os.path.abspath('run.py')}
exec(compile(src, 'run.py', 'exec'), ns)
TOT = {'lvp':15,'minwin':12,'calc':19,'wordbreak':8,'topo':10,'qs':14}
TASKS_D = ns['TASKS']; EP = {m: (ep, p) for m, ep, p in ns['MODELS']}
R = json.load(open('results.json'))
fails = [r for r in R if r['passed'] < TOT[r['task']]]

MAXTOK = 32000
def go(r):
    ep, prov = EP[r['model']]
    res = ns['call'](r['model'], ep, TASKS_D[r['task']]['prompt'], max_tokens=MAXTOK)
    if not res['ok']:
        out = {'passed':0,'total':TOT[r['task']],'err':res['error']}
    else:
        out = ns['grade'](r['task'], ns['extract'](res['text']))
    rec = {'model':r['model'],'provider':prov,'task':r['task'],
           'latency':round(res['latency'],2),'out_tok':res['out_tok'],
           'stop':res['stop'],'thinking':res['thinking'], **out}
    print(f"{prov:9}{r['model']:24}{r['task']:10} {r['passed']}/{TOT[r['task']]} -> "
          f"{rec['passed']}/{rec['total']}  stop={rec['stop']} tok={rec['out_tok']} "
          f"{rec['latency']:.0f}s  {(rec['err'] or '')[:70]}", flush=True)
    return rec

print(f"retrying {len(fails)} cells at max_tokens={MAXTOK}", flush=True)
with ThreadPoolExecutor(max_workers=4) as ex:
    retried = list(ex.map(go, fails))
json.dump(retried, open('retry.json','w'), indent=1)
print('WROTE retry.json')
