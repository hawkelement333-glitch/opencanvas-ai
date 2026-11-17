"""Compile the existing operational catalogs for one isolated destination.

The generated KQL is a candidate until Azure validates and evaluates it. Local
generation is neither destination acceptance nor proof that every signal exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLES = "union MobiusMetric_CL, MobiusApplication_CL, MobiusSecurity_CL"


def bound(value: str) -> str:
    if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}", value) is None:
        raise ValueError("invalid telemetry source binding")
    return value


def sample_query(release: str, deployment: str) -> str:
    return (
        f'{TABLES}\n| where Release == "{bound(release)}" '
        f'and Deployment == "{bound(deployment)}"\n'
        '| where Service in ("mobius-api", "mobius-worker", "mobius-outbox")\n'
        "| summarize arg_max(TimeGenerated, *) by SignalId\n"
        "| extend V=todouble(Payload.value), Outcome=tostring(Payload.labels.outcome)\n"
    )


# Summary, breach, recovery, firing windows, recovery windows. Names and
# conditions retain the existing catalog. Outbox is disabled for this pilot.
SPECS = {
    "api-latency-v1": (
        "V=percentileif(V,95,Name=='mobius.api.duration')",
        "V>=1000",
        "V<750",
        2,
        2,
    ),
    "database-saturation-v1": (
        "V=percentileif(V,95,Name=='mobius.database.pool.acquire'), "
        "T=sumif(V,Name=='mobius.database.timeouts')",
        "V>=500 or T>0",
        "V<250 and T==0",
        2,
        3,
    ),
    "storage-outage-v1": (
        "F=sumif(V,Name=='mobius.storage.failures'), "
        "N=sumif(V,Name=='mobius.storage.operations')",
        "F/N>=0.05",
        "F/N<0.01",
        2,
        3,
    ),
    "scanner-outage-v1": (
        "V=sumif(V,Name=='mobius.scanner.unavailable'), "
        "H=sumif(V,Name=='mobius.scanner.throughput' and Outcome=='success')",
        "V>=1",
        "V==0 and H>=3",
        1,
        1,
    ),
    "queue-backlog-v1": (
        "V=maxif(V,Name=='mobius.queue.oldest_age')",
        "V>=300",
        "V<120",
        2,
        2,
    ),
    "limiter-outage-v1": (
        "V=minif(V,Name=='mobius.limiter.health'), "
        "Decisions=make_list_if(V,Name=='mobius.limiter.health',2048)",
        "V<1",
        "array_length(Decisions)>=3 and array_sum(array_slice(Decisions,-3,-1))==3",
        1,
        1,
    ),
    "indexer-freshness-v1": (
        "V=maxif(V,Name=='mobius.indexer.freshness'), D=sumif(V,Name=='mobius.indexer.drift')",
        "V>=900 or D>0",
        "V<300 and D==0",
        2,
        2,
    ),
    "provider-degradation-v1": (
        "F=sumif(V,Name=='mobius.provider.calls' and Outcome in ('server_error','unavailable')), "
        "N=sumif(V,Name=='mobius.provider.calls')",
        "F/N>=0.05",
        "F/N<0.01",
        2,
        3,
    ),
    "outbox-backlog-v1": (
        "V=maxif(V,Name=='mobius.outbox.oldest_age'), "
        "T=sumif(V,Name=='mobius.outbox.terminal_failure')",
        "V>=300 or T>0",
        "V<120 and T==0",
        2,
        2,
    ),
    "evidence-integrity-v1": (
        "V=maxif(V,Name=='mobius.evidence.integrity')",
        "V>0",
        "false",
        1,
        1,
    ),
    "telemetry-loss-v1": (
        "D=sumif(V,Name=='mobius.telemetry.dropped'), "
        "F=countif(Name=='telemetry.export.failed'), "
        "H=make_list_if(V,Name=='mobius.telemetry.export_health',2048), "
        "B=maxif(V,Name=='mobius.telemetry.buffer')",
        "D>=1 or F>=3",
        "array_length(H)>=3 and array_sum(array_slice(H,-3,-1))==3 and B==0",
        1,
        1,
    ),
    "backup-freshness-v1": (
        "Values=make_list_if(V,Name=='mobius.backup.freshness',2048)",
        "todouble(Values[-1])>=86400",
        "todouble(Values[-1])<86400",
        1,
        1,
    ),
    "capacity-v1": (
        "V=maxif(V,Name=='mobius.capacity.utilization')",
        "V>=0.8",
        "V<0.65",
        3,
        3,
    ),
    "cost-v1": (
        "Values=make_list_if(V,Name=='mobius.cost.estimated',2048)",
        "todouble(Values[-1])>=COST_CEILING*0.8",
        "todouble(Values[-1])<COST_CEILING*0.7",
        1,
        1,
    ),
    "readiness-v1": (
        "F=countif(Name=='api.request.completed' and tostring(Payload.route)=='/api/v1/health/ready' "
        "and toint(Payload.status_code)>=500), "
        "S=make_list_if(toint(Payload.status_code),Name=='api.request.completed' "
        "and tostring(Payload.route)=='/api/v1/health/ready',2048)",
        "F>=3",
        "array_length(S)>=3 and array_sum(array_slice(S,-3,-1))==600",
        1,
        1,
    ),
    "worker-stale-v1": (
        "V=countif(Name=='worker.state.changed' and tostring(Payload.state)=='healthy')",
        "V==0",
        "V>=2",
        2,
        1,
    ),
}


def alert_query(alert: dict, *, release: str, deployment: str, ceiling: float) -> str:
    aggregation, breach, recovery, firing_windows, recovery_windows = SPECS[alert["id"]]
    # Preserve literal catalog lookbacks. Rolling windows end at evaluation time;
    # latest-value daily rules do not require a fabricated full day of samples.
    minutes = int(alert["evaluationWindowMinutes"])
    bucket = minutes
    # Each row's Presence counts the rule's own signal(s), not unrelated healthy
    # traffic. Missing-data breaches therefore cannot become healthy zeros.
    names = re.findall(r"Name=='([^']+)'", aggregation)
    names_literal = ",".join(f"'{item}'" for item in sorted(set(names)))
    aggregation += f", Presence=countif(Name in ({names_literal}))"
    missing = "true" if alert["missingData"] == "breach" else "false"
    hold = "true" if alert["missingData"] == "hold" else "false"
    return (
        f"let COST_CEILING={float(ceiling)};\n"
        f"let End=now(); let Start=End-2d;\n"
        "let Observed=("
        + sample_query(release, deployment)
        + f"| where TimeGenerated>=Start and TimeGenerated<End\n"
        "| order by TimeGenerated asc\n"
        f"| summarize {aggregation} by Window=bin_at(TimeGenerated,{bucket}m,End));\n"
        f"range Window from Start to (End-{bucket}m) step {bucket}m\n"
        "| join kind=leftouter Observed on Window\n"
        f"| extend Missing=isnull(Presence) or Presence==0\n"
        f"| extend Breach=iff(Missing,{missing},coalesce({breach},false)), "
        f"Healthy=iff(Missing,false,coalesce({recovery},false)), Hold=Missing and {hold}, "
        f"ForceFire={'coalesce(T>0,false)' if alert['id'] == 'outbox-backlog-v1' else 'false'}\n"
        "| order by Window asc\n| serialize\n"
        "| scan declare (Firing:bool=false, Bad:long=0, Good:long=0) with (\n"
        " step s: true =>\n"
        " Bad=iff(Hold,s.Bad,iff(Breach,s.Bad+1,0)),\n"
        " Good=iff(Hold,s.Good,iff(Healthy,s.Good+1,0)),\n"
        f" Firing=iff(ForceFire,true,iff(Hold,s.Firing,iff(Breach and s.Bad+1>={firing_windows},true,"
        f"iff(Healthy and s.Good+1>={recovery_windows},false,s.Firing))));\n"
        ")\n| top 1 by Window desc\n| where Firing\n"
        f'| project TimeGenerated=Window, AlertId="{alert["id"]}", Firing\n'
    )


def compile_catalog(
    *, release: str, deployment: str, ceiling: float, full_closure: bool = False
) -> dict:
    if not 0 < ceiling <= 1000:
        raise ValueError("operating ceiling must be explicit and bounded")
    dashboards = json.loads(
        (ROOT / "docs/observability/dashboards-v1.json").read_text()
    )
    alerts = json.loads((ROOT / "docs/observability/alerts-v1.json").read_text())
    result: dict = {
        "version": "m78-pilot-destination-v1",
        "release": bound(release),
        "deployment": bound(deployment),
        "workbooks": [],
        "alerts": [],
    }
    for dashboard in dashboards["dashboards"]:
        panels = []
        for panel in dashboard["panels"]:
            aggregation = panel["aggregation"]
            expression = {
                "rate": "sum(V)/60.0",
                "sum": "sum(V)",
                "max": "max(V)",
                "min": "min(V)",
                "p95": "percentile(V,95)",
            }[aggregation]
            query = (
                sample_query(release, deployment)
                + f'| where Name == "{panel["signal"]}" and '
                f"TimeGenerated >= ago({dashboard['windowMinutes']}m)\n"
                f"| summarize Observations=count(), Value={expression} "
                "by bin(TimeGenerated,1m)\n"
                "| project TimeGenerated, Value=iff(Observations==0,real(null),Value)"
            )
            panels.append(
                {
                    "type": 3,
                    "content": {
                        "version": "KqlItem/1.0",
                        "query": query,
                        "title": f"{panel['signal']} ({panel['unit']}, {aggregation})",
                        "queryType": 0,
                        "resourceType": "microsoft.operationalinsights/workspaces",
                        "visualization": "timechart",
                        "size": 0,
                    },
                    "name": panel["signal"],
                }
            )
        result["workbooks"].append(
            {
                "id": dashboard["id"],
                "title": dashboard["title"],
                "workbook": {
                    "version": "Notebook/1.0",
                    "items": panels,
                    "isLocked": True,
                    "fallbackResourceIds": [],
                },
            }
        )
    for alert in alerts["alerts"]:
        query = alert_query(
            alert, release=release, deployment=deployment, ceiling=ceiling
        )
        result["alerts"].append(
            {
                "id": alert["id"],
                "enabled": full_closure or alert["id"] != "outbox-backlog-v1",
                "evaluationWindowMinutes": alert["evaluationWindowMinutes"],
                "evaluationFrequency": "PT1M",
                "autoMitigate": alert["id"] != "evidence-integrity-v1",
                "recoveryMode": "authorized-investigation"
                if alert["id"] == "evidence-integrity-v1"
                else "catalog-hysteresis",
                "severity": {"critical": 0, "high": 1, "warning": 2}[alert["severity"]],
                "description": f"{alert['query']}; recovery: {alert['recoveryRule']}; "
                f"runbook: {alert['runbook']}",
                "query": query,
                "observationQuery": query.rsplit("\n| top 1", 1)[0],
            }
        )
    return result
