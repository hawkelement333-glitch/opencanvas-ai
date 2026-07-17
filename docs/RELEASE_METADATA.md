# Proposed GitHub and Devpost metadata

All values are drafts for owner review. No remote, tag, release, visibility change, or Devpost submission has been created.

## Release

- Proposed tag: `v0.3.0-buildweek-demo`
- Proposed release title: `OpenCanvas AI — Build Week Demo`
- Proposed commit message: `Prepare OpenCanvas AI Build Week demo release`
- Release notes: `docs/RELEASE_NOTES_v0.3.0-buildweek-demo.md`
- Pre-release: recommended **yes** until judge setup and final legal choice are confirmed
- Package manifests remain at `0.1.0`; the proposed tag names the competition milestone and does not silently change package publication versions.

## Repository

- Proposed name: `opencanvas-ai`
- Proposed description: `Visual, source-grounded AI knowledge workspace with user-controlled context and claim-level Trace provenance.`
- Proposed homepage/demo URL: **TBD**
- Proposed repository URL: **TBD**
- Proposed topics:
  - `ai`
  - `codex`
  - `gpt-5-6`
  - `knowledge-management`
  - `infinite-canvas`
  - `provenance`
  - `rag`
  - `traceability`
  - `openai-build-week`
  - `productivity`

## Product copy

- Tagline: `See the context. Trust the evidence.`
- One sentence: `OpenCanvas AI is a spatial knowledge workspace that lets users select exact context, generate source-grounded answers, and inspect durable provenance.`
- Devpost short summary: `OpenCanvas AI turns notes and documents into an interactive canvas where users choose exactly what AI may use. It retrieves only from selected sources, validates citations to exact passages, refuses unsupported questions, and preserves structured Trace evidence for each execution.`
- Category: **TBD — Work and Productivity recommended; manual owner decision**

## Required placeholders

- Public video URL: **TBD**
- Screenshot URLs: **TBD**
- Live demo URL: **TBD**
- Codex `/feedback` Session ID: **TBD**
- Public contact: **TBD**
- Final license: **TBD**
- Judge access method: **TBD — public with relevant licensing, or private sharing with `testing@devpost.com` and `build-week-event@openai.com`**

## Accuracy guardrails

- Do not call mock/demo responses live GPT-5.6 output.
- Do not claim automatic inference or source-conflict classification.
- Do not claim a complete Trace UI.
- Do not claim the Git history proves the Build Week start date; this repository has no commits.
- Do not publish test counts unless rerun against the exact release candidate.

## Proposed review and publication sequence

Run only after replacing placeholders, completing `RELEASE_CHECKLIST.md`, and receiving explicit owner approval:

```sh
git status --short
git diff --check
git diff
corepack pnpm validate
git add .dockerignore .editorconfig .env.example .gitignore .github README.md BUILD_WEEK_CHECKLIST.md RELEASE_CHECKLIST.md CHANGELOG.md CONTRIBUTING.md CODE_OF_CONDUCT.md COPYRIGHT NOTICE THIRD_PARTY_NOTICES.md LICENSE_RECOMMENDATION.md SECURITY.md apps docs docker-compose.yml package.json pnpm-lock.yaml pnpm-workspace.yaml scripts
git status --short
git diff --cached --check
git diff --cached
git commit -m "Prepare OpenCanvas AI Build Week demo release"
git tag -a v0.3.0-buildweek-demo -m "OpenCanvas AI Build Week demo"
git push origin master
git push origin v0.3.0-buildweek-demo
```

Before the push commands, verify that `origin` points to the owner-approved destination and that `master` is the intended publication branch. This repository currently has no remote and no commit, so those facts cannot be assumed.

After pushing, configure approved repository access, create a GitHub pre-release from the reviewed notes, verify the clean-clone judge path, upload/verify the public YouTube video, and complete Devpost. Each is a separate manual action.

## Rollback outline

- Before push: delete or correct a local proposed tag only with owner approval, amend the candidate, and rerun validation.
- After push but before submission: prefer a new corrective commit or `git revert <published-commit>`; do not rewrite shared history.
- If the GitHub release text is wrong, unpublish/edit the release through the reviewed owner account without deleting source history.
- If a secret was exposed, make repository access private if possible, rotate/revoke the credential first, remove it from the working tree, and coordinate history remediation; a normal revert does not erase a secret from Git history.
- If a migration causes a deployment issue, stop application writes, restore the pre-release database/file backup, and redeploy the previous reviewed artifact. Do not improvise an untested destructive downgrade.
