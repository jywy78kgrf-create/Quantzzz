"""Render a RunReport (multi-suite) to a human-readable markdown report."""

from __future__ import annotations

from typing import Any


def _pct(n: int, d: int) -> str:
    return f"{n}/{d}" + (f" ({n / d:.0%})" if d else "")


def _judge_by_name(suite: dict, name_contains: str) -> dict | None:
    for j in suite["judges"]:
        if name_contains in j["judge_name"]:
            return j
    return None


def _headline_table(suites: list[dict]) -> list[str]:
    out = [
        "| suite | rows | gate recall | judge | precision | recall | sem-delta | FP on ok |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in suites:
        gate_r = s["gate_only"]["recall"]
        for j in s["judges"]:
            if not j["available"]:
                out.append(
                    f"| {s['suite']} | {s['n_rows']} | {gate_r:.3f} | "
                    f"{j['judge_name']} | _unavailable_ | | | |"
                )
                continue
            out.append(
                f"| {s['suite']} | {s['n_rows']} | {gate_r:.3f} | "
                f"{j['judge_name']} | {j['precision']:.3f} | {j['recall']:.3f} | "
                f"{j['semantic_delta']} | {j['ok_false_positives']}/{j['ok_total']} |"
            )
    return out


def _difficulty_table(j: dict) -> list[str]:
    bd = j.get("by_difficulty", {})
    if not bd:
        return []
    out = [
        "",
        "    difficulty breakdown:",
        "| difficulty | off-objective caught (recall) | false positives on ok |",
        "|---|---|---|",
    ]
    order = ["easy", "hard", "borderline", "unspecified"]
    for k in sorted(bd, key=lambda x: (order.index(x) if x in order else 99, x)):
        d = bd[k]
        out.append(
            f"| {k} | {_pct(d['off_caught'], d['off_total'])} | "
            f"{_pct(d['ok_fp'], d['ok_total'])} |"
        )
    return out


def _tag_highlights(j: dict) -> list[str]:
    bt = j.get("by_tag", {})
    interesting = ["subtle", "borderline_ok", "injection", "net_new", "prepay", "off_contract"]
    rows = []
    for tag in interesting:
        if tag in bt:
            d = bt[tag]
            if d["off_total"]:
                rows.append(f"| {tag} | recall {_pct(d['off_caught'], d['off_total'])} |")
            elif d["ok_total"]:
                rows.append(f"| {tag} | false positives {_pct(d['ok_fp'], d['ok_total'])} |")
    if not rows:
        return []
    return ["", "    key tags:", "| tag | result |", "|---|---|", *rows]


def _failures(j: dict, limit: int = 12) -> list[str]:
    fails = j.get("failures", [])
    if not fails:
        return ["", "    failures: none on this suite."]
    out = ["", f"    failures ({len(fails)} shown, up to {limit}):"]
    for f in fails[:limit]:
        tags = ",".join(f.get("tags") or [])
        out.append(
            f"  - **{f['type']}** `{f['id']}` ({f['label']}/{f.get('difficulty')}"
            f"{'/' + tags if tags else ''}) → got {f['decision']}"
        )
        if f.get("note"):
            out.append(f"      note: {f['note']}")
        if f.get("judge_reason"):
            out.append(f"      judge: {f['judge_reason'][:200]}")
    return out


def generate_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    a = lines.append
    a("# Procurement Firewall — Evaluation Report")
    a("")
    a(f"_Generated {report['when']}_")
    a("")
    a("Positive class = **should be stopped** (`det_off` or `sem_off`). "
      "The **semantic delta** counts off-objective rows the deterministic gate "
      "provably cannot catch (it ALLOWed them) that the judge escalated.")
    a("")
    a("## Headline (all suites)")
    a("")
    lines.extend(_headline_table(report["suites"]))
    a("")

    # Injection resistance summary across suites.
    a("## Prompt-injection resistance")
    a("")
    a("| suite | judge | injected rows escalated (resistance) |")
    a("|---|---|---|")
    for s in report["suites"]:
        for j in s["judges"]:
            if j.get("injection_total"):
                res = (
                    _pct(j["injection_caught"], j["injection_total"])
                    if j["available"]
                    else "_unavailable_"
                )
                a(f"| {s['suite']} | {j['judge_name']} | {res} |")
    a("")

    # Per-suite detail.
    for s in report["suites"]:
        a("---")
        a(f"## Suite: `{s['suite']}`")
        a("")
        a(f"- mandate: `{s['mandate_id']}`")
        a(f"- dataset: `{s['dataset_path']}` (sha256 `{s['dataset_sha256'][:16]}`)")
        a(f"- rows: {s['n_rows']}  |  labels: {s['label_counts']}")
        g = s["gate_only"]
        gc = g["confusion"]
        a(f"- **deterministic floor (gate only):** precision {g['precision']:.3f}, "
          f"recall {g['recall']:.3f}  (TP={gc['tp']} FP={gc['fp']} FN={gc['fn']} TN={gc['tn']})")
        a("")
        for j in s["judges"]:
            a(f"### Judge: `{j['judge_name']}`")
            if not j["available"]:
                a(f"- UNAVAILABLE — {j['unavailable_reason']}")
                a("")
                continue
            c = j["confusion"]
            a(f"- confusion: TP={c['tp']} FP={c['fp']} FN={c['fn']} TN={c['tn']}")
            a(f"- precision **{j['precision']:.3f}**, recall **{j['recall']:.3f}**, "
              f"f1 {j['f1']:.3f}")
            a(f"- det_off caught {_pct(j['det_off_caught'], j['det_off_total'])}, "
              f"sem_off caught {_pct(j['sem_off_caught'], j['sem_off_total'])}")
            a(f"- false positives on ok rows: {_pct(j['ok_false_positives'], j['ok_total'])}")
            a(f"- **semantic delta: {j['semantic_delta']}**")
            if j.get("errors"):
                a(f"- errors during run: {j['errors']}")
            lines.extend(_difficulty_table(j))
            lines.extend(_tag_highlights(j))
            lines.extend(_failures(j))
            a("")
    return "\n".join(lines) + "\n"
