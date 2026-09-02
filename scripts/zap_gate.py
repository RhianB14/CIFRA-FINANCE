import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/zap/report.json")

if not report_path.exists():
    print(f"zap report missing: {report_path}")
    sys.exit(1)

report = json.loads(report_path.read_text(encoding="utf-8"))
sites = report.get("site") or []
scanned = set()
for site in sites:
    for alert in site.get("alerts") or []:
        for instance in alert.get("instances") or []:
            uri = instance.get("uri") or ""
            if uri:
                scanned.add(uri)
                break

if not scanned:
    print("zap examined zero urls; failing")
    sys.exit(1)

high = []
medium = []
for site in sites:
    for alert in site.get("alerts") or []:
        risk = int(alert.get("riskcode", "0"))
        name = alert.get("name", "unknown")
        if risk >= 3:
            high.append(name)
        elif risk == 2:
            medium.append(name)

print(f"zap scanned {len(scanned)} urls; high={len(high)} medium={len(medium)}")
if high:
    print("HIGH findings blocking:", sorted(set(high)))
    sys.exit(1)

print("ZAP-GATE-OK")
