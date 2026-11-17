# Milestone 7.8 pilot release candidate

Prepared 2026-11-16 CST; corrected local build completed 2026-11-17 00:24 UTC
(2026-11-16 18:24 CST). Branch:
`milestone-7-8-production-readiness-audit-local`. Starting source checkpoint:
`5a6e6b5f3a043ff539caf7a1dbddb3fccf899f37`.

The user authorized a local API candidate build and artifact verification after
release inputs are ready. This does not authorize registry publication, Azure
operations, paid provider calls, managed validation or website deployment.
PostgreSQL, M78-D-001 and M78-D-002 remain accepted. Billing remains unsettled.

## Current release disposition

The current corrected candidate is `sha256:71f3ccb9a450a9773d3c904dd83fc8b6b97b98eccc7a1bdc890fd0633c5f6192`. Its local artifact checks and affected real-PostgreSQL browser journey pass. The first candidate remains preserved as superseded release history after the demonstrated retrieval-head timestamp failure. Trusted signing and managed/deployment acceptance remain unproved.

## Source and build boundary

The candidate incorporates the current grounded-context, instruction/relevance,
exact-version retrieval, admitted-context isolation and document-deletion
corrections recorded in the
[local gap completion](MILESTONE_7_8_LOCAL_GAP_COMPLETION.md). The corrected
frontend manifests and lockfile belong to the web release inputs; the API
Dockerfile does not copy them. The pilot's read-only controlled-draft interface
is an explicit product decision, not acceptance of the historical editable AI
node expectations.

The release-affecting secure-upload path was corrected before the build:
the website uses upload sessions and preserves quarantine/pending/timeout
states; the API creates exactly one persistent card; the real document worker
hands a promoted current source to native private-clean publication. Durable
completion binds the exact revision and publication, and lost-lease rollback
suppresses the publication transaction. The final snapshot also includes the
telemetry gateway/destination corrections. No unchanged campaign was rerun.

**Two local candidates were built. The corrected candidate's composition, source binding, inventory,
SBOM and the High/Critical scan passed. Trusted signature verification remains
open.** No registry publication or managed execution occurred.

The canonical input list remains the existing
`infra/milestone_7_8/canonical_inputs.py:BUILD_INPUTS`: API Dockerfile and ignore
file; Python project/build/runtime locks; API source; Alembic configuration and
migrations; API scripts; and LICENSE, COPYRIGHT, NOTICE and THIRD_PARTY_NOTICES.
The prepared local executor reuses the existing canonical hash and safe source
archive verifier. It does not invoke the campaign executor, which would perform
Azure registry operations.

The source snapshot uses a separate private Git index, `read-tree`, scoped
`git add` of canonical inputs, and `write-tree`. The real index and all five
protected stashes remain unchanged. The receipt distinguishes the base commit,
snapshot tree, changed input paths, canonical input hash, source archive hash
and patch hash. OCI labels identify the snapshot truthfully, including changes
not yet committed. Exact source bytes are extracted with LF preservation.

Executed build mechanism: installed Docker Buildx v0.35.0-desktop.2 and
BuildKit v0.31.2, Linux/amd64, pinned Dockerfile base and dependency hashes,
`--provenance=mode=max --load`, explicit source-date epoch from the base commit,
local-only tag, and a private metadata file. There is no `--push` or registry
login. The original image and scan remain retained and are not replaced:
`sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a`.

## Artifact acceptance checks

Private inputs, command intents/results and outputs belong under
`.runtime/milestone_7_8/pilot-rc-20261116/image-corrected/`; none are Git publication inputs.
The completed artifact checks are:

- Inspect exact image identity, Linux/amd64, `USER opencanvas`, size at most
  2 GiB and all source/canonical labels; save the exact image and hash its archive.
- Run only the local composition check with no network, a read-only filesystem,
  bounded temporary filesystem, no capabilities and no privilege escalation.
  Verify nonzero UID, absent pip/ensurepip, imports of affected modules and hashes
  of every installed API Python source file against the staged snapshot.
- Recover the BuildKit provenance from the saved OCI archive. Validate all
  content-addressed blobs, runtime subject and layer diff IDs. Record its real
  builder/completeness fields; unsigned metadata is not signed evidence.
- Generate SPDX 2.3 with installed Docker Scout v1.23.1 against the exact local
  immutable image digest; independently validate the matching saved archive. Independently compare installed Python and Debian package metadata,
  respecting layer whiteouts, and validate SPDX identifiers/relationships.
- Scan the exact local image digest with the existing High/Critical gate:
  `docker scout cves local://<image-id> --platform linux/amd64
  --only-severity critical,high --exit-code --format sarif --output <private-report>`.
  Acceptance requires exit zero, valid SARIF 2.1.0 and empty results in every run.
  A failed assessment is preserved; a repeat needs a demonstrated correction or
  qualifying transport-only failure with no assessment.

These checks establish local artifact composition and the stated scan result,
not managed runtime acceptance or deployment readiness. Source changes after
snapshot creation require comparison of the canonical inputs; documentation or
web-only changes do not justify rebuilding this API image.

## Exact candidate and retained receipts

| Binding/result | Value |
|---|---|
| Base source commit | `5a6e6b5f3a043ff539caf7a1dbddb3fccf899f37` |
| Source snapshot tree | `938deb08054781ab7ea65b35bce77f2e7735783b` |
| Canonical API input SHA-256 | `8bf9c6feaa1a73e8dc24004d5d1c2adb5693943394cf59b02f017bb9dc03970f` |
| OCI image index | `sha256:71f3ccb9a450a9773d3c904dd83fc8b6b97b98eccc7a1bdc890fd0633c5f6192` |
| Linux/amd64 runtime manifest | `sha256:ab4b417f4a9ba5077e03888f1debd0d063355d69251622cb019b23c12015ae2f` |
| Local tag | `mobius-m78-pilot:rc-938deb080547` |
| Saved archive SHA-256 | `cb8352f5ad5845d546088f4fa78484664e78dba2b0098f96f9d40caaba14fa7a` |
| Image bytes | 95112481 |
| Installed source verification | 97 API Python files; 54 copied script/migration/notice files |
| Runtime composition | UID 100/GID 101; affected imports passed; pip/ensurepip absent |
| OCI graph verification | 20 blobs; 14 layer diff IDs; exact provenance subject |
| Inventory match | 44 Python distributions and 87 Debian binary packages |
| SPDX 2.3 | 170 packages plus root; 493 file entries; 1,007 relationships |
| Docker Scout 1.23.1 | 0 Critical, 0 High; exit 0, empty SARIF results |
| Trusted signature | Unproved; no signer enrolled or key created |

The seven changed canonical paths relative to the base commit are
`api/routes/documents.py`, `api/routes/health.py`, `api/schemas.py`,
`services/jobs.py` and `services/indexer.py` under `apps/api/opencanvas_api`, and
`apps/api/scripts/telemetry_destination.py` and `telemetry_gateway.py`.
The earlier grounded/retrieval/deletion corrections are already in the base.
Dockerfile and Python dependency locks were unchanged. The final live-input
comparison matches the built canonical hash, and verified the real index,
all five stashes, prior image, prior archive and prior scan were preserved.

BuildKit's original SLSA v1 statement has an empty builder identity and no
signature. Its VCS revision identifies the base commit; the snapshot tree and
canonical hash are bound separately through verified OCI labels, source archive,
installed-source comparisons and `release-binding.json`. Completeness reports
`request=true`, `resolvedDependencies=false`. This is not authenticated CI
provenance. The SPDX structure and inventory were validated; no full published
SPDX schema or legal license clearance is claimed.

The first candidate, `sha256:7b04e4fda46b9ded040c609dfc50b0c513114cdf521c7dfe2a265c721eba9511`, remains retained under `image/` with its successful artifact checks and two failed Windows-path SBOM export receipts. Its managed-schema local browser run demonstrated a release defect: PostgreSQL rejected a native `retrieval_heads` insertion because `created_at`/`updated_at` were absent. The corrected insertion explicitly binds both to the publication timestamp. No migration or acceptance criterion changed.

The affected real-PostgreSQL browser journey and two publication/lease-rollback regressions passed after that correction. This concrete API input change justified the second build. Its SPDX export used the already-proven exact `local://` digest path; one fresh Critical/High scan passed. Both candidate histories and the original campaign image remain preserved. No claim is made that another build could never be necessary.

| Private evidence file under the image directory | SHA-256 |
|---|---|
| `build-receipt.json` | `82e7af71ff2db586a570f3a191b47420f92494cd5d4d2e3b9753315a3e701972` |
| `buildkit-provenance.json` | `10baba983aa810d089326c03ae6a1aae0f1dec2e41a6f92b345989af325b452b` |
| `candidate.spdx.json` | `8d637f4311933234c8c61e97603c49c5d6c2caaef310abd1cbf9ced91291a678` |
| `scout.sarif.json` | `69933e606e8fc010c7d1df52993f413523163ac7ca1c3247fc26bdbc6c946878` |
| `runtime-package-inventory.json` | `e4f624a2527fad072aaa120a46622ed3d781176900267af86ccdd4b4226b533a` |
| `oci-sbom-validation.json` | `8157e5f24f16d3c02d726388260987d30e7eb5ba9f0082badb78c3f360dac39c` |
| `release-binding.json` | `511eeedecbf55882c383bb54e8bc4a0bf1cdb8a651145e43cbc4c6dd9ceeccc2` |
| `final-source-preservation.json` | `a8d4ae5c5e69ac8c2cbea524627ff677a7c1e4aad6dc9f9eead1a278d435eb7f` |

The empty SARIF hash equals the earlier empty report because its serialized
content contains no findings or artifact identity. It is not reused evidence:
`scout-cves-intent.json` and `scout-cves-result.json` record this new exact local
image digest, invocation time and successful exit; the build receipt binds them
to the candidate. Raw command and provenance payloads remain outside Git.

## Signing decision

A bounded read of the repository's sole CI workflow, release/security documents,
existing retained-image metadata and the prior provenance search found no
documented authorized trusted signing identity or verification policy. CI grants
only `contents: read` and contains no signing/attestation job. `cosign` and
`notation` were not found on the local PATH. No credential store was opened, no
key was created and no identity was enrolled. This does not prove that an
externally held authorized signer does not exist.

The smallest remaining decision is to identify an existing trusted release
signer and its exact accepted certificate identity and OIDC issuer, or an
existing approved public key, and authorize that signer to endorse this local
candidate's provenance and release binding. Installing a verified Cosign binary
would then be necessary. Signing is separate from registry publication.

For an approved OIDC signer, the concrete detached-blob method is:

```text
cosign sign-blob buildkit-provenance.json --bundle provenance.sigstore.json
cosign verify-blob buildkit-provenance.json --bundle provenance.sigstore.json --certificate-identity <approved-exact-identity> --certificate-oidc-issuer <approved-exact-issuer>
cosign sign-blob release-binding.json --bundle release-binding.sigstore.json
cosign verify-blob release-binding.json --bundle release-binding.sigstore.json --certificate-identity <approved-exact-identity> --certificate-oidc-issuer <approved-exact-issuer>
```

The unsigned release binding names the exact source tree, canonical hash, OCI index
and runtime manifest digests, archive, provenance, SBOM and scan hashes. No
wildcard identity/issuer verification is acceptable. Public Sigstore signing
requires consent to its identity/digest transparency record; private raw
runtime artifacts are not uploaded or committed. This is a release signer's
endorsement of locally generated provenance, not a claim that the local builder
was an independently authenticated CI service or that the historical image was
signed. The selected trust policy must accept that distinction. Commands follow
the official [Sigstore blob-signing](https://docs.sigstore.dev/cosign/signing/signing_with_blobs/)
and [verification](https://docs.sigstore.dev/cosign/verifying/verify/) documentation.

Until the signer decision and verified signature are present, trusted signed
provenance remains open. Neither a successful local build nor an unsigned
BuildKit statement closes that requirement.
