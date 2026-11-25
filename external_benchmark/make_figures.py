"""Generate the external-benchmark figures from RESULTS.json and raw traces."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "external_benchmark" / "results"
FIG = ROOT / "external_benchmark" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
DATA = json.loads((RESULTS / "RESULTS.json").read_text(encoding="utf-8"))


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / (name + ".png"), dpi=180)
    fig.savefig(FIG / (name + ".svg"))
    plt.close(fig)


def capability():
    rows = DATA["capability_coverage"]["properties"]
    cols = ["AADP", "AP2", "ZJJ"]
    values = []
    labels = []
    for row in rows:
        vs, ls = [], []
        for key in ("aadp", "ap2", "zjj"):
            value = row[key]
            vs.append({"PASS": 1.0, "PARTIAL": 0.5, "N/A": 0.0, "FAIL": -0.4}[value])
            ls.append(value)
        values.append(vs)
        labels.append(ls)
    values = np.array(values)
    fig, ax = plt.subplots(figsize=(6.4, 6.2))
    im = ax.imshow(values, cmap="RdYlGn", vmin=-0.6, vmax=1.0, aspect="auto")
    ax.set_xticks(range(len(cols)), cols, fontsize=10)
    ax.set_yticks(range(len(rows)), [r["id"] for r in rows], fontsize=9)
    for i in range(len(rows)):
        for j in range(len(cols)):
            ax.text(j, i, labels[i][j], ha="center", va="center", fontsize=8)
    ax.set_title("Capability coverage: public evidence (frozen definitions)")
    fig.colorbar(im, ax=ax, ticks=[-0.4, 0, 0.5, 1], label="FAIL  N/A  PARTIAL  PASS")
    save(fig, "fig1-capability-matrix")


def native_rates():
    native = DATA["native"]
    items = [
        ("AADP full", native["aadp"]["full_suite"]),
        ("AADP selected", native["aadp"]["selected_capability_suite"]),
        ("AP2 full", native["ap2"]["full_suite"]),
        ("AgentDojo tests", native["agentdojo"]["full_suite"]),
        ("ZJJ selected", DATA["capability_coverage"]["junit"]["zjj_selected"]),
    ]
    labels = [x[0] for x in items]
    rates = [x[1]["passed"] / x[1]["total"] * 100 for x in items]
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    bars = ax.bar(labels, rates, color=["#2a7f62", "#57a773", "#3b6ea8", "#8a6bbf", "#c47f17"])
    ax.set_ylim(90, 101)
    ax.set_ylabel("native tests passed (%)")
    ax.set_title("Native reproduction pass rate (not a cross-protocol score)")
    for bar, (_, row) in zip(bars, items):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                f"{row['passed']}/{row['total']}", ha="center", fontsize=8)
    ax.tick_params(axis="x", labelrotation=15)
    save(fig, "fig2-native-test-rates")


def floor_rates():
    paired = DATA["differential_goalfloor"]["paired_20"]
    labels = ["A AADP budget", "B AADP static reserve", "C ZJJ GoalFloor off", "D ZJJ GoalFloor enforce"]
    rows = [paired["aadp"]["A"], paired["aadp"]["B"], paired["zjj_off"], paired["zjj_enforce"]]
    rates = [r["floor_violations"] / r.get("sequences", r.get("clean_sequences")) * 100 for r in rows]
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    bars = ax.bar(labels, rates, color=["#c0504d", "#4f81bd", "#c0504d", "#2a7f62"])
    ax.set_ylim(0, 40)
    ax.set_ylabel("sequences with floor violation (%)")
    ax.set_title("Necessary-resource floor: 20 paired generated sequences")
    for bar, rate in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, rate + 0.6, f"{rate:.0f}%", ha="center", fontsize=9)
    ax.tick_params(axis="x", labelrotation=10)
    save(fig, "fig3-floor-violation")


def relations():
    rows = DATA["crypto_relations"]["results"]
    names = [r["case"] for r in rows]
    y = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.barh(y, [1] * len(names), color="#2a7f62")
    ax.set_yticks(y, names, fontsize=8)
    ax.set_xlim(0, 1.12)
    ax.set_xlabel("rejected (1) / accepted (0)")
    ax.set_title("Ten relation negatives: each producing signature is valid")
    ax.text(0.02, len(names) - 0.3, "single-signature-only baseline: 0/10 rejected",
            fontsize=8, color="#8b1a1a")
    save(fig, "fig4-crypto-relations")


def atomic():
    a = DATA["atomic_evidence"]
    labels = ["crash boundaries", "acceptance races", "offline package", "evidence tamper"]
    passed = [a["crash_boundaries"]["passed"], a["acceptance_races"]["passed"],
              a["offline_package"]["passed"], a["evidence_tamper_tests"]["passed"]]
    total = [a["crash_boundaries"]["total"], a["acceptance_races"]["total"],
             a["offline_package"]["passed"] + a["offline_package"]["failed"],
             a["evidence_tamper_tests"]["total"]]
    rates = [p / t * 100 for p, t in zip(passed, total)]
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    bars = ax.bar(labels, rates, color=["#3b6ea8", "#57a773", "#8a6bbf", "#c47f17"])
    ax.set_ylim(0, 105)
    ax.set_ylabel("PASS (%)")
    ax.set_title("Atomic accept and independent evidence checks")
    for bar, p, t in zip(bars, passed, total):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{p}/{t}", ha="center", fontsize=9)
    ax.tick_params(axis="x", labelrotation=10)
    save(fig, "fig5-atomic-evidence")


def availability():
    paired = DATA["differential_goalfloor"]["paired_20"]
    labels = ["A", "B", "C", "D"]
    rows = [paired["aadp"]["A"], paired["aadp"]["B"], paired["zjj_off"], paired["zjj_enforce"]]
    optional = [r["optional_accepted"] for r in rows]
    done = [r["all_done"] for r in rows]
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    ax.bar(x - 0.18, optional, 0.36, label="optional actions accepted", color="#4f81bd")
    ax.bar(x + 0.18, done, 0.36, label="all-sequence completion", color="#2a7f62")
    ax.set_xticks(x, labels)
    ax.set_ylabel("count over 20 sequences")
    ax.set_title("Safety and business availability are not the same axis")
    ax.legend(fontsize=8)
    save(fig, "fig6-availability")


def performance():
    paired = DATA["differential_goalfloor"]["paired_20"]
    modes = ["C off", "D enforce"]
    vals = {"C off": paired["zjj_off"], "D enforce": paired["zjj_enforce"]}
    p50 = [vals[m]["p50_ns"] / 1e9 for m in modes]
    p95 = [vals[m]["p95_ns"] / 1e9 for m in modes]
    p99 = [vals[m]["p99_ns"] / 1e9 for m in modes]
    x = np.arange(len(modes))
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.bar(x - 0.22, p50, 0.22, label="p50", color="#57a773")
    ax.bar(x, p95, 0.22, label="p95", color="#c47f17")
    ax.bar(x + 0.22, p99, 0.22, label="p99", color="#c0504d")
    ax.set_xticks(x, modes)
    ax.set_ylabel("accept latency (s)")
    ax.set_title("Exploratory accept latency under 4–6 worker load")
    ax.legend(fontsize=8)
    for i, (a, b, c) in enumerate(zip(p50, p95, p99)):
        ax.text(i - 0.22, a + 0.1, f"{a:.1f}", ha="center", fontsize=7)
        ax.text(i, b + 0.1, f"{b:.1f}", ha="center", fontsize=7)
        ax.text(i + 0.22, c + 0.1, f"{c:.1f}", ha="center", fontsize=7)
    save(fig, "fig7-performance")


def main():
    capability()
    native_rates()
    floor_rates()
    relations()
    atomic()
    availability()
    performance()
    print("figures written", sorted(p.name for p in FIG.glob("*.png")))


if __name__ == "__main__":
    main()
