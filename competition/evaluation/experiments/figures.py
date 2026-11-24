"""Generate competition figures/CSV from the actual result JSON files."""
from __future__ import annotations
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

EVAL = Path(__file__).resolve().parents[1]
RESULTS = EVAL / 'results'
FIG = EVAL / 'figures'


def load(name):
    return json.loads((RESULTS / name).read_text(encoding='utf-8'))


def save(fig, name):
    fig = plt.gcf()
    FIG.mkdir(parents=True, exist_ok=True)
    for ext in ('svg', 'png'):
        fig.savefig(FIG / f'{name}.{ext}', bbox_inches='tight')
    plt.close(fig)


def write_csv(name, header, rows):
    FIG.mkdir(parents=True, exist_ok=True)
    with (FIG / f'{name}.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream); writer.writerow(header); writer.writerows(rows)


def long_sequence():
    data = load('long-sequence.json')
    seq = data['real'][0]
    for label, trace in (('off', seq['off']['trace']), ('enforce', seq['proposed']['trace'])):
        xs, ys = [], []
        for row in trace:
            after = row.get('after')
            if after:
                xs.append(row['position']); ys.append(after['reserved'] + after['spent'])
        plt.plot(xs, ys, marker='o', label=label)
    plt.xlabel('action position'); plt.ylabel('reserved + spent')
    plt.title('Long sequence: resource occupancy (first paired sequence)')
    plt.legend(); plt.grid(alpha=.3)
    save(None, 'fig1-long-sequence-resource')
    write_csv('fig1-long-sequence-resource',
              ['position', 'off_occupancy', 'enforce_occupancy'],
              [[i, (seq['off']['trace'][i].get('after') or {}).get('reserved', '') if
                seq['off']['trace'][i].get('after') else '',
                (seq['proposed']['trace'][i].get('after') or {}).get('reserved', '') if
                seq['proposed']['trace'][i].get('after') else '']
               for i in range(len(seq['off']['trace']))])

    margins = []
    for row in seq['proposed']['trace']:
        after = row.get('after')
        if after and after.get('goal'):
            margins.append((row['position'], int(after['goal']['remaining_floor']),
                            int(after['goal']['headroom'])))
    if margins:
        xs, rem, head = zip(*margins)
        plt.plot(xs, rem, marker='o', label='remaining floor')
        plt.plot(xs, head, marker='s', label='headroom')
        plt.xlabel('action position'); plt.ylabel('units')
        plt.title('GoalFloor witness on accepted actions')
        plt.legend(); plt.grid(alpha=.3)
        save(None, 'fig2-goal-floor-margin')
        write_csv('fig2-goal-floor-margin', ['position', 'remaining_floor', 'headroom'], margins)


def ablation():
    data = load('ablation.json')['summary']
    names = list(data); values = [data[n]['illegal_accepted'] for n in names]
    plt.bar(names, values, color=['#999', '#999', '#d95f02', '#7570b3', '#1b9e77'])
    plt.ylabel('illegal accepts (of 5)'); plt.ylim(0, 5)
    plt.title('Ablation: illegal accepts')
    plt.xticks(rotation=20)
    save(None, 'fig3-ablation')
    write_csv('fig3-ablation', ['model', 'illegal_accepted', 'total'],
              [[n, data[n]['illegal_accepted'], data[n]['illegal_total']] for n in names])


def concurrency():
    old = load('concurrency.json')
    bulk = load('concurrency-bulk.json')
    labels = ['old real', 'bulk real', 'reference model']
    values = [old['actual_histories'], bulk['histories'], old['model']['histories']]
    plt.bar(labels, values, color=['#1b9e77', '#7570b3', '#999'])
    plt.yscale('log'); plt.ylabel('histories (log)')
    plt.title('Concurrency evidence volume')
    save(None, 'fig4-concurrency-volume')
    write_csv('fig4-concurrency-volume', ['kind', 'histories'], list(zip(labels, values)))


def crash():
    data = load('crash-recovery.json')
    rows = [(r['test'], int(r['passed'])) for r in data['tests']]
    plt.barh([r[0] for r in rows], [r[1] for r in rows], color='#1b9e77')
    plt.xlim(0, 1.2); plt.xlabel('pass=1')
    plt.title('Crash boundaries')
    save(None, 'fig5-crash-boundaries')
    write_csv('fig5-crash-boundaries', ['test', 'passed'], rows)


def tamper():
    data = load('crypto-attacks.json')
    rows = [(m['mutation'], 1 if m['status'] == 'FAIL' else 0) for m in data['mutations']
            if m['mutation'] != 'none']
    plt.barh([r[0] for r in rows], [r[1] for r in rows], color='#d95f02')
    plt.xlim(0, 1.2); plt.xlabel('rejected=1')
    plt.title('Directed tamper/replay matrix')
    save(None, 'fig6-tamper-matrix')
    write_csv('fig6-tamper-matrix', ['mutation', 'rejected'], rows)


def performance():
    pure = load('performance.json')['pure_goal_floor']
    bulk = load('performance-bulk.json')
    labels = ['pure p50', 'pure p95', 'off p50', 'enforce p50']
    values = [pure['p50_ns'] / 1e6, pure['p95_ns'] / 1e6,
              bulk['off']['p50_ns'] / 1e6, bulk['enforce']['p50_ns'] / 1e6]
    plt.bar(labels, values, color=['#1b9e77', '#1b9e77', '#7570b3', '#7570b3'])
    plt.ylabel('ms'); plt.yscale('log')
    plt.title('Latency (exploratory samples)')
    plt.xticks(rotation=20)
    save(None, 'fig7-performance')
    write_csv('fig7-performance', ['metric', 'ms'], list(zip(labels, values)))


def cross():
    data = load('cross-goal.json')['rows']
    labels = [f"{r['profile']} {r['mode']} {'crowd' if r['crowd'] else 'normal'}" for r in data]
    values = [1 if r['accepted'] else 0 for r in data]
    plt.barh(labels, values, color='#1b9e77')
    plt.xlim(0, 1.2); plt.xlabel('accepted=1')
    plt.title('Cross-profile GoalFloor')
    save(None, 'fig8-cross-scenario')
    write_csv('fig8-cross-scenario', ['profile', 'mode', 'crowd', 'accepted', 'code'],
              [[r['profile'], r['mode'], r['crowd'], r['accepted'], r['code']] for r in data])


def main():
    long_sequence(); ablation(); concurrency(); crash(); tamper(); performance(); cross()
    print('figures written', FIG)


if __name__ == '__main__':
    main()
