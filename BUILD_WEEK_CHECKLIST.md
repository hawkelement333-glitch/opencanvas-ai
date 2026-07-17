# OpenAI Build Week submission checklist

Status vocabulary is intentionally strict: **PASS**, **PARTIAL**, **MISSING**, **BLOCKED**, or **MANUAL ACTION REQUIRED**. PASS means repository evidence exists; it does not mean Devpost or GitHub state was changed.

| Requirement                                     | Status                 | Evidence / action                                                                                                                                                                            |
| ----------------------------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Working project                                 | PASS                   | Canonical validation, browser workflows, migrations, security checks, and the production build pass on the exact candidate.                                                                  |
| Appropriate category                            | MANUAL ACTION REQUIRED | Recommended: **Work and Productivity**. Eligible tracks currently listed are Apps for Your Life, Work and Productivity, Developer Tools, and Education; owner must make the final selection. |
| Clear project description                       | PASS                   | Root `README.md` and proposed release metadata.                                                                                                                                              |
| Public demo video under three minutes           | MISSING                | Record, review for private information, upload publicly to YouTube, and add URL.                                                                                                             |
| Video audio explains Codex and GPT-5.6          | MISSING                | Use `docs/DEMO_GUIDE.md`; do not describe mock output as live.                                                                                                                               |
| Repository URL                                  | MISSING                | No Git remote is configured and no publication was authorized.                                                                                                                               |
| Judge repository access                         | MANUAL ACTION REQUIRED | Choose public repository with relevant licensing, or keep it private and share with `testing@devpost.com` and `build-week-event@openai.com`.                                                 |
| Relevant license/notice                         | MANUAL ACTION REQUIRED | Owner must make the final license choice after reviewing `LICENSE_RECOMMENDATION.md`.                                                                                                        |
| README setup instructions                       | PASS                   | Judge, Docker, local, environment, migration, and validation paths are documented.                                                                                                           |
| Non-sensitive sample/demo data                  | PASS                   | The isolated deterministic seed, exact persisted invariants, manual UI evidence, and repository hygiene checks passed.                                                                       |
| Clear running instructions                      | PASS                   | `README.md`, `docs/JUDGE_SETUP.md`, and `docs/DEMO_GUIDE.md`.                                                                                                                                |
| Codex acceleration explanation                  | PASS                   | `README.md` and `docs/BUILD_WEEK.md`; private transcripts excluded.                                                                                                                          |
| Major human decisions explanation               | PASS                   | `docs/BUILD_WEEK.md`.                                                                                                                                                                        |
| GPT-5.6/runtime model explanation               | PASS                   | Live configurable Responses API versus deterministic mock mode is explicitly distinguished.                                                                                                  |
| Codex `/feedback` Session ID                    | MANUAL ACTION REQUIRED | Placeholder must be replaced with the approved session ID.                                                                                                                                   |
| Developer-tool/plugin installation instructions | PASS                   | No required custom plugin; Node, pnpm, Python, Docker, and Playwright prerequisites are documented.                                                                                          |
| Judge-accessible demo/test account              | PASS                   | No account is required; the deterministic local demo passed source-only clean-clone reproduction and startup smoke testing.                                                                  |
| Trace/provenance demonstration                  | PARTIAL                | Trace read API and execution evidence exist; recording must show them accurately without claiming a full UI.                                                                                 |
| Supported-answer demonstration                  | PARTIAL                | Workflow and tests exist; final recording must show exact citation navigation.                                                                                                               |
| Unsupported-answer demonstration                | PARTIAL                | Insufficient-evidence behavior exists; final recording must show it.                                                                                                                         |
| Inference/conflict distinction                  | PARTIAL                | Documentation states these are not automatically classified; presenter may only describe human interpretation.                                                                               |
| Secret/security audit                           | PASS                   | Security tests, production dependency audit, final source scan, and repository-hygiene validation passed; human pre-publication review remains required.                                     |
| Third-party license audit                       | PARTIAL                | Final notices/recommendation require owner review; no exhaustive legal certainty claimed.                                                                                                    |
| Clean-clone reproduction                        | PASS                   | The exact source-only candidate completed frozen Node install, fresh Python install, canonical validation, and temporary cleanup.                                                            |
| Final public release approval                   | MANUAL ACTION REQUIRED | Owner approval required; no push/tag/publish is authorized.                                                                                                                                  |
| Devpost form completion                         | MANUAL ACTION REQUIRED | Enter final category, description, URLs, session ID, and required disclosures.                                                                                                               |

Demo evidence update: the isolated seed contains separately persisted grounded and
insufficient-evidence responses. `pnpm demo:check`, `pnpm demo:smoke`, canonical validation, and
source-only clean-clone reproduction pass. Manual UI verification confirmed both exact citation
passages, the persisted Trace record, and the insufficient-evidence node's no-citation state.
Recording these behaviors remains a manual competition action.

## Submission asset placeholders

- Repository URL: **TBD**
- Demo URL: **TBD**
- Public video URL: **TBD**
- Primary screenshot URL/path: **TBD**
- Citation screenshot URL/path: **TBD**
- Trace screenshot URL/path: **TBD**
- Codex `/feedback` session ID: **TBD**
- Final category: **TBD; Work and Productivity recommended**
- Final license: **TBD**

## Final manual sequence

1. Review current official competition rules and judging access addresses.
2. Review the secret and third-party license reports.
3. Choose and apply the final license.
4. Record and review the sub-three-minute video.
5. Obtain the `/feedback` session ID.
6. Approve repository visibility/access and publication.
7. Fill the Devpost form and verify every URL in an incognito browser.

Current submission deadline: **July 21, 2026 at 5:00 PM PDT**. Recheck the official [Build Week page](https://openai.com/build-week/), [Devpost FAQ](https://openai.devpost.com/details/faqs), and [rules](https://openai.devpost.com/rules) immediately before submission because competition details can change.
