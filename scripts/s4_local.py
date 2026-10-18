"""Local S4 check: our template grouping vs Loghub 2k gold EventIds (GA / FGA).

Runs the survey's code path on the Content column: mask every line (mask_py, the
Python twin of mask_sql; --sql masks inside SereneDB instead), group identical
masked strings, merge them with drain.merge_groups, and compare each line's
template with its gold EventId.

GA (grouping accuracy): a line is correct iff the set of lines sharing its
predicted template equals the set sharing its gold event.
FGA: F1 over templates, a predicted template being correct iff its line set equals
a gold event's line set (precision over predicted, recall over gold templates).

    uv run python scripts/s4_local.py <structured.csv> [<structured.csv> ...] [--sql URL] [-v]

Get the data with `gh repo clone logpai/loghub` (or logpai/logparser's
data/loghub_2k_corrected, which has *_structured_corrected.csv).
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict

from rcagent.templating.drain import MaskedGroup, merge_groups
from rcagent.templating.masking import mask_py, mask_sql


def _mask_all(lines: list[str], sql_url: str | None) -> list[str]:
    if not sql_url:
        return [mask_py(line) for line in lines]
    import psycopg

    with psycopg.connect(sql_url, autocommit=True) as conn:
        out = []
        for line in lines:
            row = conn.execute(f"SELECT {mask_sql('%(m)s')}", {"m": line}).fetchone()
            out.append(row[0] if row else "")
        return out


def evaluate(path: str, sql_url: str | None, verbose: bool) -> tuple[float, float]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    contents = [r["Content"] for r in rows]
    gold = [r["EventId"] for r in rows]
    masked = _mask_all(contents, sql_url)
    counts = Counter(masked)
    example: dict[str, str] = {}
    for m, c in zip(masked, contents, strict=True):
        example.setdefault(m, c)
    merged = merge_groups(MaskedGroup(m, n, example[m]) for m, n in counts.items())
    template_of = {m: t.template for t in merged for m in t.masks}
    pred = [template_of[m] for m in masked]

    pred_sets: dict[str, set[int]] = defaultdict(set)
    gold_sets: dict[str, set[int]] = defaultdict(set)
    for i, (p, g) in enumerate(zip(pred, gold, strict=True)):
        pred_sets[p].add(i)
        gold_sets[g].add(i)
    gold_frozen = {frozenset(s) for s in gold_sets.values()}
    correct_lines = sum(len(s) for s in pred_sets.values() if frozenset(s) in gold_frozen)
    correct_templates = sum(1 for s in pred_sets.values() if frozenset(s) in gold_frozen)
    ga = correct_lines / len(rows)
    precision = correct_templates / len(pred_sets)
    recall = correct_templates / len(gold_sets)
    fga = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    print(f"{path.rsplit('/', 1)[-1]}: lines={len(rows)} gold={len(gold_sets)} predicted={len(pred_sets)} "
          f"GA={ga:.3f} FGA={fga:.3f} (P={precision:.3f} R={recall:.3f})")
    if verbose:
        for g, lines in sorted(gold_sets.items(), key=lambda kv: -len(kv[1])):
            preds = Counter(pred[i] for i in lines)
            if len(preds) > 1:
                print(f"  SPLIT {g} ({len(lines)} lines) into {len(preds)}:")
                for t, n in preds.most_common(6):
                    print(f"      {n:4d}  {t}")
        for p, lines in sorted(pred_sets.items(), key=lambda kv: -len(kv[1])):
            golds = Counter(gold[i] for i in lines)
            if len(golds) > 1:
                print(f"  MERGED {len(golds)} gold events into: {p}")
                for g, n in golds.most_common(6):
                    ex = next(contents[i] for i in lines if gold[i] == g)
                    print(f"      {g} {n:4d}  e.g. {ex[:140]}")
    return ga, fga


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--sql", help="mask inside SereneDB at this URL instead of with mask_py")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    for path in args.files:
        evaluate(path, args.sql, args.verbose)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
