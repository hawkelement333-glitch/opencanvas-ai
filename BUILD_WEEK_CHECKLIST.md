# OpenAI Build Week submission checklist

Status vocabulary is intentionally strict: **PASS**, **PARTIAL**, **MISSING**, **BLOCKED**, or
**MANUAL ACTION REQUIRED**. PASS means repository evidence exists; it does not mean Devpost or
GitHub state was changed.

| Requirement                                     | Status                 | Evidence / action                                                                                                                                         |
| ----------------------------------------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Working project                                 | PASS                   | Canonical validation, browser workflows, migrations, security checks, and the production build pass on the exact candidate.                               |
| Appropriate category                            | PASS                   | **Work and Productivity** matches the product's primary knowledge-work and team-productivity use case.                                                    |
| Clear project description                       | PASS                   | Root `README.md` and proposed release metadata.                                                                                                           |
| Public demo video under three minutes           | MANUAL ACTION REQUIRED | Submitted URL: <https://www.youtube.com/watch?v=gd0JWNcHhAA>. Verify public visibility and runtime in an incognito browser before submitting.               |
| Video audio explains Codex and GPT-5.6          | MANUAL ACTION REQUIRED | Review the final upload against `docs/DEMO_GUIDE.md`; do not describe deterministic mock output as live GPT-5.6 output.                                    |
| Repository URL                                  | PASS                   | Public source: `https://github.com/hawkelement333-glitch/opencanvas-ai`.                                                                                  |
| Judge repository access                         | PASS                   | The repository is public; no private collaborator invitation is required by the current rules.                                                            |
| Relevant license/notice                         | PASS                   | Root `LICENSE`, `COPYRIGHT`, and `NOTICE` state the owner-selected proprietary All Rights Reserved evaluation terms.                                      |
| README setup instructions                       | PASS                   | Judge, Docker, local, environment, migration, and validation paths are documented.                                                                        |
| Non-sensitive sample/demo data                  | PASS                   | The isolated deterministic seed, exact persisted invariants, manual UI evidence, and repository hygiene checks passed.                                    |
| Clear running instructions                      | PASS                   | `README.md`, `docs/JUDGE_SETUP.md`, and `docs/DEMO_GUIDE.md`.                                                                                             |
| Codex acceleration explanation                  | PASS                   | `README.md` and `docs/BUILD_WEEK.md`; private transcripts excluded.                                                                                       |
| Major human decisions explanation               | PASS                   | `docs/BUILD_WEEK.md`.                                                                                                                                     |
| GPT-5.6/runtime model explanation               | PASS                   | Live configurable Responses API versus deterministic mock mode is explicitly distinguished.                                                               |
| Codex `/feedback` Session ID                    | MANUAL ACTION REQUIRED | Enter the approved primary-build Session ID directly in Devpost; do not publish private Codex conversation content.                                       |
| Developer-tool/plugin installation instructions | PASS                   | No required custom plugin; Node, pnpm, Python, Docker, and Playwright prerequisites are documented.                                                       |
| Judge-accessible demo/test account              | PASS                   | No account is required; the deterministic local demo passed source-only clean-clone reproduction and startup smoke testing.                               |
| Trace/provenance demonstration                  | PARTIAL                | Trace read API and execution evidence exist; the final video must show them accurately without claiming a complete end-user Trace explorer.                |
| Supported-answer demonstration                  | PARTIAL                | Workflow and tests exist; confirm that the final video visibly shows exact citation navigation.                                                            |
| Unsupported-answer demonstration                | PARTIAL                | Insufficient-evidence behavior exists; confirm that the final video visibly shows it.                                                                      |
| Inference/conflict distinction                  | PARTIAL                | Documentation states these are not automatically classified; the presenter may only describe human interpretation.                                        |
| Visual asset integrity                          | PASS                   | Promotional art is separated from product evidence; implemented features must be shown with real captures from the reviewed localhost build.              |
| Secret/security audit                           | PASS                   | Security tests, production dependency audit, final source scan, and repository-hygiene validation passed; human pre-publication review remains required.  |
| Third-party license audit                       | PASS                   | Audited direct/transitive inventory and redistribution caveats are recorded in `THIRD_PARTY_NOTICES.md`; no exhaustive legal certainty is claimed.        |
| Clean-clone reproduction                        | PASS                   | The exact source-only candidate completed frozen Node install, fresh Python install, canonical validation, and temporary cleanup.                         |
| GitHub Actions                                  | PASS                   | Canonical validation passed on the final rebrand PR head: [run 29670242267](https://github.com/hawkelement333-glitch/opencanvas-ai/actions/runs/29670242267). |
| Public source approval                          | PASS                   | The owner explicitly approved a public proprietary repository; tag, GitHub release, deployment, and Devpost submission remain separate actions.           |
| Devpost form completion                         | MANUAL ACTION REQUIRED | Enter the final category, description, YouTube URL, Session ID, and required disclosures, then submit rather than saving as a draft.                        |

Demo evidence update: the isolated seed contains separately persisted grounded and
insufficient-evidence responses. `pnpm demo:check`, `pnpm demo:smoke`, canonical validation, and
source-only clean-clone reproduction pass. Manual UI verification confirmed both exact citation
passages, the persisted Trace record, and the insufficient-evidence node's no-citation state. The
final public video must still be reviewed against the recording checklist.

## Submission assets and external fields

- Repository URL: <https://github.com/hawkelement333-glitch/opencanvas-ai>
- Demo URL: not applicable; the documented judging path is the deterministic localhost demo.
- Public YouTube video: <https://www.youtube.com/watch?v=gd0JWNcHhAA>
- Promotional thumbnail: `docs/assets/solarplexus-mobius-thumbnail.png`
- Primary screenshot path: `docs/assets/opencanvas-evidence-canvas.jpg`
- Citation screenshot path: `docs/assets/opencanvas-citation-passage.jpg`
- Trace screenshot path: `docs/assets/opencanvas-trace-record.jpg`
- Codex `/feedback` Session ID: enter the approved primary-build ID directly in Devpost.
- Final category: **Work and Productivity**
- Final license: **Proprietary / All Rights Reserved evaluation terms (`LICENSE`)**

## Final manual sequence

1. Review the current official competition rules and judging-access requirements.
2. Confirm the final secret/history scan and green GitHub Actions run.
3. Run the final validation and deterministic-demo checks.
4. Open <https://www.youtube.com/watch?v=gd0JWNcHhAA> in an incognito browser and confirm it is public,
   under three minutes, audible, and accurately distinguishes mock replay from live GPT-5.6 use.
5. Obtain the `/feedback` Session ID from the primary build task.
6. Enter the YouTube URL, Session ID, category, description, and required disclosures in Devpost.
7. Verify every public URL and submit rather than saving as a draft.

Current submission deadline: **July 21, 2026 at 5:00 PM PDT**. Recheck the official
[Build Week page](https://openai.com/build-week/),
[Devpost FAQ](https://openai.devpost.com/details/faqs), and
[rules](https://openai.devpost.com/rules) immediately before submission because competition details
can change.
