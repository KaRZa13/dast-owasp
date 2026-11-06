#!/usr/bin/env python3
"""Indicateurs simples à partir des rapports JSON de ZAP (zap-baseline.py -J).

Usage :
  python3 kpi_zap.py rapport.json                 # synthèse d'un scan
  python3 kpi_zap.py ancien.json nouveau.json     # comparaison : nouvelles / disparues / persistantes

Les comptes portent sur les *types* d'alertes (alertRef) et non sur les instances :
une hausse peut refléter une meilleure couverture du scan, pas une dégradation.
"""
import json
import sys
from collections import Counter

ORDER = ["High", "Medium", "Low", "Informational"]


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    alerts = {}
    for site in data.get("site", []):
        for a in site.get("alerts", []):
            risk = a["riskdesc"].split(" (")[0]
            alerts[(site["@name"], a["alertRef"])] = {
                "name": a["name"],
                "risk": risk,
                "confidence": a["riskdesc"].split("(")[-1].rstrip(")"),
                "instances": int(a.get("count", len(a.get("instances", [])))),
            }
    return data.get("@generated", "?"), alerts


def summary(path):
    generated, alerts = load(path)
    by_risk = Counter(a["risk"] for a in alerts.values())
    print(f"Rapport : {path} (généré le {generated})")
    print(f"Types d'alertes : {len(alerts)} | instances : {sum(a['instances'] for a in alerts.values())}")
    for r in ORDER:
        print(f"  {r:<14} {by_risk.get(r, 0)}")
    return alerts


def compare(old_path, new_path):
    _, old = load(old_path)
    _, new = load(new_path)
    fixed = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    kept = sorted(set(old) & set(new))
    print(f"Disparues (corrections à confirmer) : {len(fixed)}")
    for k in fixed:
        print(f"  - [{old[k]['risk']}] {k[1]} {old[k]['name']}")
    print(f"Nouvelles : {len(added)}")
    for k in added:
        print(f"  + [{new[k]['risk']}] {k[1]} {new[k]['name']}")
    print(f"Persistantes : {len(kept)}")
    if old:
        print(f"Taux de disparition : {100 * len(fixed) / len(old):.0f} %")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        summary(sys.argv[1])
    elif len(sys.argv) == 3:
        compare(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
