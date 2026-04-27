"""
Score agent output against ground truth.
  python evaluate.py                          (auto-match last run)
  python evaluate.py --subject "Timothy Overturf"
"""
import json, argparse
from pathlib import Path

GT   = Path("evaluation/ground_truth.json")
RPT  = Path("outputs/risk_report.json")


def fuzzy(needle: str, corpus: list[str], threshold=0.4) -> bool:
    words = set(needle.lower().split()) - {"a","an","the","of","in","at","by","for","and","or","to"}
    if not words:
        return False
    for item in corpus:
        il = item.lower()
        if sum(1 for w in words if w in il) / len(words) >= threshold:
            return True
    return False


def score(gt: dict, report: dict) -> dict:
    fact_corpus = []
    for f in report.get("key_facts", []):
        fact_corpus += [f"{f.get('subject','')} {f.get('relation','')} {f.get('object','')}",
                        f.get("quote", "")]
    flag_corpus = [f"{fl.get('category','')} {fl.get('description','')}"
                   for fl in report.get("flags", [])]

    req_facts = gt.get("required_facts", [])
    req_flags = gt.get("required_flag_categories", [])
    found_f   = [f for f in req_facts if fuzzy(f, fact_corpus)]
    found_fl  = [f for f in req_flags if fuzzy(f, flag_corpus)]

    fs   = len(found_f)  / len(req_facts)  if req_facts  else 1.0
    fls  = len(found_fl) / len(req_flags)  if req_flags  else 1.0
    final = fs * 0.6 + fls * 0.4
    thr   = gt.get("pass_threshold", 0.70)

    return {
        "name": gt["name"], "fact_score": round(fs,3), "flag_score": round(fls,3),
        "final": round(final,3), "threshold": thr, "passed": final >= thr,
        "found_facts": found_f, "missing_facts": [f for f in req_facts if f not in found_f],
        "found_flags": found_fl, "missing_flags": [f for f in req_flags if f not in found_fl],
    }


def show(r: dict):
    sep = "="*58
    status = "PASS" if r["passed"] else "FAIL"
    print(f"\n{sep}\n  [{status}] {r['name']}\n{sep}")
    print(f"  Facts : {r['fact_score']:.0%}  ({len(r['found_facts'])}/{len(r['found_facts'])+len(r['missing_facts'])})")
    print(f"  Flags : {r['flag_score']:.0%}  ({len(r['found_flags'])}/{len(r['found_flags'])+len(r['missing_flags'])})")
    print(f"  Score : {r['final']:.0%}  (need {r['threshold']:.0%})")
    if r["found_facts"]:
        print(f"\n  Found facts:")
        for f in r["found_facts"]: print(f"    [+] {f}")
    if r["missing_facts"]:
        print(f"\n  Missing facts:")
        for f in r["missing_facts"]: print(f"    [-] {f}")
    if r["missing_flags"]:
        print(f"\n  Missing flags:")
        for f in r["missing_flags"]: print(f"    [-] {f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", default="")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    gt_data = json.loads(GT.read_text(encoding="utf-8"))
    report  = json.loads(RPT.read_text(encoding="utf-8"))
    subjects = gt_data.get("subjects", [])

    if args.all:
        targets = subjects
    elif args.subject:
        targets = [s for s in subjects if args.subject.lower() in s["name"].lower()]
    else:
        rname = report.get("subject", "")
        targets = [s for s in subjects if rname.lower() in s["name"].lower()] or subjects[:1]

    all_passed = True
    for gt in targets:
        r = score(gt, report)
        show(r)
        if not r["passed"]:
            all_passed = False

    print(f"\n{'='*58}")
    print(f"  Overall: {'ALL PASS' if all_passed else 'SOME FAILED'}")
    print(f"{'='*58}\n")


if __name__ == "__main__":
    main()
