# Milestone 7.8 pilot cost model

> Current follow-up: the [full-closure local ledger](MILESTONE_7_8_FULL_CLOSURE_LEDGER.md)
> and [revised execution proposal](MILESTONE_7_8_FULL_CLOSURE_EXECUTION_PACKAGE.md) supersede
> this historical pilot preparation for the new candidate. Its evidence and
> limitations remain history; its proposed budget is not execution authority.
> Full7.8 remains incomplete, closed campaigns stay closed, billing is unsettled.

Prepared 2026-11-16 from current public Azure Retail Prices responses for East US
and official OpenAI model pricing. This is preparation only. No resource,
provider request or new spending was authorized or executed. Billing remains
**unsettled**; the prior cumulative approved ceiling of **$350.89** is not settled
spending and is not available for this package. All figures are USD, before tax,
without credits, free grants, negotiated discounts or reservations.

## A. Temporary managed validation

**Forecast: $25.5678. Proposed incremental ceiling: $50.00. Proposed cumulative
ceiling: $400.89.** The $50 ceiling reuses the existing cleanup-controller allowlist; the forecast includes both API replicas. These proposed ceilings require separate approval. The
forecast includes a $1.50 cache-write contingency; without it the arithmetic is
$24.0678. There is no future-start waiting period: the proposed window is bound
to approval, with eight proof hours plus two cleanup hours. Resource counts and
final stop deadlines must match the executable package before approval.

The scoped allocation is API two replicas at 0.5 vCPU/1 GiB each, worker 0.5/1, web 0.5/1, telemetry
gateway 0.25/0.5, and aggregate probe jobs 0.5/1. All are conservatively charged
active for ten hours. The private alert receiver is a probe process, not an
additional permanent app. The existing DocumentWorker consumes the private
scanner bridge, so no separate scanner app is budgeted. PostgreSQL General Purpose D2ds_v4 has two vCores and
32 GB, with one restored copy for four hours. Bootstrap, migration, artifact staging and proof jobs run sequentially within the aggregate probe allocation; overlapping them would require a revised forecast. Redis B0 is HA (two node charges).
No PostgreSQL or Redis acceptance campaign is repeated.

Six private endpoints cover Blob, ACR, AMPLS, Redis, Key Vault and Event Hubs.
PostgreSQL uses a delegated subnet. Eleven DNS zones and sixteen five-minute
log alerts are budgeted; this conservatively includes rules disabled by pilot
feature restrictions. Final DNS counts must match the manifest.
Container Apps uses internal VNet integration and private in-VNet probes; no
ACA environment private endpoint, NAT gateway, private DNS resolver, firewall
or application gateway is included. This isolated proof topology is not a
public website hosting decision.

| Component and bound | USD |
|---|---:|
| ACA six allocations 2.75 vCPU 5.5GiB all active 10h | 2.9700 |
| ACA 1 million requests | 0.4000 |
| PG 2vCore 10h plus restored 2vCore 4h | 2.4920 |
| PG 32GB storage main10h restore4h | 0.0706 |
| PG 32GB excess backup allowance10h | 0.0416 |
| Redis B0 two HA nodes10h | 0.3200 |
| Premium ACR one full day allowance | 1.6666 |
| Blob10GB10h plus10k write/read/list | 0.1068 |
| Defender account10h | 0.1340 |
| Malware scan1GiB | 0.1611 |
| Analytics logs1GiB | 2.4696 |
| 16 log alerts5min10h | 0.3288 |
| 6 private endpoints10h plus10GB total processed | 0.7000 |
| 11 private DNS zones2billable days plus1M queries | 0.7667 |
| Key Vault10k operations | 0.0300 |
| Event Hubs Standard1TU10h and1000events | 0.3000 |
| Internet egress10GB conservative allowance | 1.0000 |
| Cleanup Automation and small unmetered-overlap allowance | 0.2500 |
| OpenAI200calls input15k output1600 percall | 9.8400 |
| Embeddings1M tokens | 0.0200 |
| Conservative AI cache-write surcharge all3Minput | 1.5000 |

The AI bound is **200 calls, each at most 15,000 input and 1,600 output tokens**:
3 million input and 0.32 million output tokens, $9.84 at standard short-context
`gpt-5.6-terra` rates. Output accounting must include reasoning tokens. One
million embedding tokens adds $0.02. A conservative $1.50 allows all input to
use the $2.50/million cache-write rate instead of $2.00 uncached input. No cache
read discount is assumed. The fixture/controller must enforce calls and token
bounds; an estimate alone is not a limit. No alternative model was selected.
[GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra),
[text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small).

The forecast bounds total LA ingestion and malware scanning at one GiB each
and converts GiB to decimal billing GB (1.073741824 GB). It budgets ten GB of
combined Private Link data processing, ten GB internet egress, ten GB stored
Blob data including versions, and ten thousand each Blob read/write/list
operations. ACR includes a full day and DNS two billable days. DNS is billed
by day with partial months prorated.
[Azure DNS pricing](https://azure.microsoft.com/en-us/pricing/details/dns/).

The internet-egress $1 and cleanup/small-overlap $0.25 entries are conservative
allowances, not asserted meter quotes: a broad public Retail API bandwidth
request was throttled (HTTP 429), and the narrow Zone 1 filter returned no rows.
No subscription billing query was made. Standard managed-service data charges,
platform logs or delayed teardown can consume the ceiling margin. The separate
execution package must stop new proof early enough to retain cleanup headroom;
this forecast does not guarantee Azure stops billing at the ceiling.

## B. Recurring pilot hosting

For a 730-hour month, the fixed baseline below is **$490.0444** with all five
permanent replicas charged active. The arithmetic floor if every allocation
qualifies idle for the entire month is **$365.8714**. That floor is not a
prediction: worker polling and telemetry can qualify as active, and core
services must remain available. No safe cohort size or workload capacity is
inferred from these figures. The transient probe and restored copy are absent.
[Container Apps billing rules](https://azure.microsoft.com/en-us/pricing/details/container-apps/).

| Component and bound | USD |
|---|---:|
| ACA 2.25vCPU4.5GiB active730h | 177.3900 |
| PG2vCore730h | 129.9400 |
| PG32GB | 3.6800 |
| Redis2HAnodes730h | 23.3600 |
| PremiumACR730h | 50.6924 |
| 6privateendpoints730h | 43.8000 |
| 11privateDNSzones | 5.5000 |
| DefenderStorage730h | 9.7820 |
| EventHubsStandard1TU730h | 21.9000 |
| 16logalerts5min | 24.0000 |

Illustrative usage, independent of user count, adds **$84.7320/month**, giving
**$574.7764/month** against the active fixed baseline. This is a transparent
usage scenario, not a hosting authorization or an observed bill:

| Component and bound | USD |
|---|---:|
| logs10GBingested | 23.0000 |
| retention10GBpermonth equal-fifths classes30-90-30-14-365 at steady state | 2.6200 |
| storedBlob10GBincludingversions | 0.2080 |
| scannedUploads1GB | 0.1500 |
| Blob10kreads10kwrites10klists | 0.1040 |
| privateLink10GBtotal | 0.1000 |
| DNS1Mqueries | 0.4000 |
| KeyVault10kops | 0.0300 |
| ACA1Mrequests | 0.4000 |
| InternetEgress10GBallowance | 1.0000 |
| OpenAI1000draftsat15kinput1600output | 49.2000 |
| embeddings1M | 0.0200 |
| Conservative AI cache-write surcharge all15Minput | 7.5000 |
| eventhub1000events | 0.0000 |

The retention example assumes ten decimal GB ingested per 30-day month, divided
equally across five existing classes (30/90/30/14/365 days), at steady state.
Only 90- and 365-day classes exceed the 31 included Analytics days. The extra
retained volume is `(10/30/5) * ((90-31) + (365-31)) = 26.2 GB`, costing $2.62 per
month. Actual table distribution and table-type constraints must replace this
illustration. No Sentinel commitment or Application Insights 90-day allowance
is assumed for custom tables. Queries against Analytics logs are included;
retention and export remain separately metered.
[Azure Monitor retention and query pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/).

The standard prices used are $0.089 per PostgreSQL vCore-hour, $0.115/GB-month
storage, $0.016 per Redis B0 node-hour, $1.6666/day Premium ACR, $0.01/endpoint-hour
plus $0.01/GB Private Link, $0.03/hour Event Hubs Standard throughput unit,
$2.30/GB Analytics ingestion, $0.10/GB-month extended retention, $0.15/GB malware
scanning and $0.0134/hour Defender storage account. The retained Retail meter
rows include meter IDs, effective dates, region, SKU and units. AMPLS/DCE/DCR and
a portal dashboard have no separate resource-hour charge in this model; their
ingestion, endpoint, alert and data-transfer costs are included. No managed
Grafana or separate Prometheus ingestion service is included.
[Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices),
[Private Link pricing](https://azure.microsoft.com/en-us/pricing/details/private-link/).

## C. Decisions and optional deltas

These are excluded from the selected internal proof topology and cannot be
silently added to its scope:

| Component and bound | USD |
|---|---:|
| NATandPublicIP730h | 36.5000 |
| NATperGB | 0.0450 |
| ACAEnvironmentPEplusPE730h | 80.3000 |
| PGHAstandby2vCore32GB730h | 133.6200 |
| additionalPrivateDnsZoneMonthly | 0.5000 |

NAT adds $0.045/GB processing besides its gateway/IP baseline. The ACA private
endpoint feature adds a $0.10/hour environment charge plus the ordinary
$0.01/hour endpoint; one additional DNS zone would also apply. Public authenticated
website ingress, operator connectivity, custom domain/TLS and any edge/WAF
choice remain explicit hosting decisions. Direct OpenAI public HTTPS outbound
is not private endpoint service connectivity. No cross-region workload transfer
is planned; alternative locations, regional processing or additional network
services require revised pricing and authority.

PostgreSQL HA is shown as an optional additional standby cost, not silently
removed from a full production requirement. Excess backup beyond provisioned
storage costs $0.095/GB-month. Additional web/API replicas, longer-lived restore
copies, load-generated telemetry, object versions and retained deletion data
increase costs. AI Fast/Batch, long-context (>272K), regional-residency,
cache-write/read and provider-specific modifiers differ from the selected
standard short-context rates. Provider credentials, exact account access,
spending controls and trusted artifact signing remain separate decisions.

Private price pages and exact arithmetic are retained under
`.runtime/milestone_7_8/pilot-rc-20261116/cost/`. The public responses are evidence,
not current subscription invoices. `selected-retail-meters.json` identifies the
used rows; `cost-model-corrected.json` records the current quantities, assumptions
and input hashes. The original `cost-model.json` is retained as superseded
history: it counted one API replica; the corrected model counts two.

Corrected cost model SHA-256: `623e91dfe765dbc2542e8bb90d866c1ee7ed0d946b8b7be3fc87eaa2148a33f5`.
