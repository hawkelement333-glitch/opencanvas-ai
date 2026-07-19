# OpenAI Build Week submission checklist

Status vocabulary is intentionally strict: **PASS**, **PARTIAL**, **MISSING**, **BLOCKED**, or
**MANUAL ACTION REQUIRED**. PASS means repository evidence exists; it does not mean Devpost or
GitHub state was changed.

| Requirement                                     | Status                 | Evidence / action                                                                                                                                        |
| ----------------------------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Working project                                 | PASS                   | Canonical validation, browser workflows, migrations, security checks, and the production build pass on the exact candidate.                              |
| Appropriate category                            | PASS                   | **Work and Productivity** matches the product's primary knowledge-work and team-productivity use case.                                                   |
| Clear project description                       | PASS                   | Root `README.md` and proposed release metadata.                                                                                                          |
| Public demo video under three minutes           | MISSING                | Record, review for private information, upload publicly to YouTube, and enter the verified URL in Devpost.                                               |
| Video audio explains Codex and GPT-5.6          | MISSING                | Use `docs/DEMO_GUIDE.md`; do not describe mock output as live.                                                                                           |
| Repository URL                                  | PASS                   | Public source: `https://github.com/hawkelement333-glitch/opencanvas-ai`.                                                                                 |
| Judge repository access                         | PASS                   | The repository is public; no private collaborator invitation is required by the current rules.                                                           |
| Relevant license/notice                         | PASS                   | Root `LICENSE`, `COPYRIGHT`, and `NOTICE` state the owner-selected proprietary All Rights Reserved evaluation terms.                                     |
| README setup instructions                       | PASS                   | Judge, Docker, local, environment, migration, and validation paths are documented.                                                                       |
| Non-sensitive sample/demo data                  | PASS                   | The isolated deterministic seed, exact persisted invariants, manual UI evidence, and repository hygiene checks passed.                                   |
| Clear running instructions                      | PASS                   | `README.md`, `docs/JUDGE_SETUP.md`, and `docs/DEMO_GUIDE.md`.                                                                                            |
| Codex acceleration explanation                  | PASS                   | `README.md` and `docs/BUILD_WEEK.md`; private transcripts excluded.                                                                                      |
| Major human decisions explanation               | PASS                   | `docs/BUILD_WEEK.md`.                                                                                                                                    |
| GPT-5.6/runtime model explanation               | PASS                   | Live configurable Responses API versus deterministic mock mode is explicitly distinguished.                                                              |
| Codex `/feedback` Session ID                    | MANUAL ACTION REQUIRED | Enter the approved primary-build Session ID directly in Devpost; do not publish private Codex conversation content.                                      |
| Developer-tool/plugin installation instructions | PASS                   | No required custom plugin; Node, pnpm, Python, Docker, and Playwright prerequisites are documented.                                                      |
| Judge-accessible demo/test account              | PASS                   | No account is required; the deterministic local demo passed source-only clean-clone reproduction and startup smoke testing.                              |
| Trace/provenance demonstration                  | PARTIAL                | Trace read API and execution evidence exist; recording must show them accurately without claiming a full UI.                                             |
| Supported-answer demonstration                  | PARTIAL                | Workflow and tests exist; final recording must show exact citation navigation.                                                                           |
| Unsupported-answer demonstration                | PARTIAL                | Insufficient-evidence behavior exists; final recording must show it.                                                                                     |
| Inference/conflict distinction                  | PARTIAL                | Documentation states these are not automatically classified; presenter may only describe human interpretation.                                           |
| Visual asset integrity                          | PASS                   | Promotional art is separated from product evidence; implemented features must be shown with real captures from the reviewed localhost build.             |
| Secret/security audit                           | PASS                   | Security tests, production dependency audit, final source scan, and repository-hygiene validation passed; human pre-publication review remains required. |
| Third-party license audit                       | PASS                   | Audited direct/transitive inventory and redistribution caveats are recorded in `THIRD_PARTY_NOTICES.md`; no exhaustive legal certainty is claimed.       |
| Clean-clone reproduction                        | PASS                   | The exact source-only candidate completed frozen Node install, fresh Python install, canonical validation, and temporary cleanup.                        |
| GitHub Actions                                  | PASS                   | Canonical validation passed on `main`: [run 29624339220](https://github.com/hawkelement333-glitch/opencanvas-ai/actions/runs/29624339220).               |
| Public source approval                          | PASS                   | The owner explicitly approved a public proprietary repository; tag, GitHub release, deployment, and Devpost submission remain separate actions.          |
| Devpost form completion                         | MANUAL ACTION REQUIRED | Enter final category, description, URLs, Session ID, and required disclosures.                                                                           |

Demo evidence update: the isolated seed contains separately persisted grounded and
insufficient-evidence responses. `pnpm demo:check`, `pnpm demo:smoke`, canonical validation, and
source-only clean-clone reproduction pass. Manual UI verification confirmed both exact citation
passages, the persisted Trace record, and the insufficient-evidence node's no-citation state.
Recording these behaviors remains a manual competition action.

## Submission assets and external fields

- Repository URL: <https://github.com/hawkelement333-glitch/opencanvas-ai>
- Demo URL: not applicable; the documented judging path is the deterministic localhost demo.
- Public video URL: enter the verified public YouTube URL directly in Devpost after upload.
- Promotional thumbnail: `docs/assets/solarplexus-mobius-thumbnail.png`
- Primary screenshot path: `docs/assets/opencanvas-evidence-canvas.jpg`
- Citation screenshot path: `docs/assets/opencanvas-citation-passage.jpg`
- Trace screenshot path: `docs/assets/opencanvas-trace-record.jpg`
- Codex `/feedback` Session ID: enter the approved primary-build ID directly in Devpost.
- Final category: **Work and Productivity**
- Final license: **Proprietary / All Rights Reserved evaluation terms (`LICENSE`)**

## Final manual sequence

1. Review current official competition rules and judging access addresses.
2. Confirm the final secret/history scan and green GitHub Actions run.
3. Run the final validation and deterministic-demo checks.
4. Record and review the sub-three-minute public YouTube video using real product footage.
5. Obtain the `/feedback` Session ID from the primary build task.
6. Enter the final video URL, Session ID, category, description, and required disclosures in Devpost.
7. Verify every public URL in an incognito browser and submit rather than saving as a draft.

Current submission deadline: **July 21, 2026 at 5:00 PM PDT**. Recheck the official
[Build Week page](https://openai.com/build-week/),
[Devpost FAQ](https://openai.devpost.com/details/faqs), and
[rules](https://openai.devpost.com/rules) immediately before submission because competition details
can change.
