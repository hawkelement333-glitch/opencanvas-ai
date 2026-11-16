# Milestone 7.8 local retained-image provenance reconciliation

Date: 2026-11-16. This completes the local retrieval and inventory portion of
the [remaining security evidence mapping](MILESTONE_7_8_REMAINING_EVIDENCE_RECONCILIATION.md#requirement-by-requirement-disposition).
It does not create a new image, repeat a vulnerability scan, or alter the
accepted PostgreSQL, object-storage or Redis results.

## Exact retained artifact

- Image index: `sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a`.
- Linux/amd64 runtime manifest: `sha256:241c55acd6e169546969b1c36f58806a146e3562f69011f5a3efc438a71eb769`.
- Private archive: `.runtime/milestone_7_8/o1/image.tar`.
- Archive SHA-256: `25d46785b855429dccdb7a6877976fb6874407a8ddab17ee8124a5c3c168e7c1`.
- Source snapshot tree: `2e4bccfe5e28df3e03775917dbc5b4ddc5f05c2f`.
- Canonical image-input SHA-256: `d94e350754821b1172a9b4452466391053e0221d3095e336e43379f6f33c312f`.

These bindings identify the retained image. A later source or dependency
correction must be assessed separately before applying this inventory or its
historical critical/high scan to a future release image.

## Recovered original provenance

The archive contains an original BuildKit in-toto statement with SLSA
provenance v1, rather than only OCI labels. Its attestation manifest is
`sha256:1da840b4c60407e402bc9a3ca503019713404242962cd404ed249b1e7199aa83`;
the statement blob SHA-256 is
`fcade045f8150da2a157432d2de91c869aa371d5217238a7aaa209189b17edf8`.
The statement subject and the attestation-manifest annotation both identify
the exact runtime manifest above. It records a build from
2026-11-15T22:28:35.575047942Z to 2026-11-15T22:28:46.022575216Z.

Fresh local validation checked the archive against the retained build receipt,
all **20 OCI blob hashes**, all **14 uncompressed layer diff IDs**, the
attestation/runtime relationship, source-tree and canonical-input labels, and
the retained Scout report hash. All checks passed. No image was executed.

This original provenance is **unsigned**, its builder identity is empty, and
its request/resolved-dependency completeness flags are false. Its VCS revision
is the base commit `73425f40b35f9b3dc925c78905d69ef7e27404eb`; the staged source
snapshot is separately identified by the OCI labels and retained build receipt.
Do not represent the base commit as the full built source tree or describe
hash integrity as authenticated builder identity.

## Retrospective SBOM and independent inventory

No original embedded SBOM or cryptographic signature was found in the exact
archive. Bounded filename searches covered `.runtime`, `evidence`, `validation`,
`preflight` and `docs`; Git history was searched for SBOM, provenance,
attestation and signature filenames. The only tracked history match was the
retained-image provenance test, not a signed image artifact. These searches
do not establish that no external signing record can exist.

Under the user's local-metadata authorization, the Codex `local_provenance`
agent generated a **retrospective SPDX 2.3 SBOM** using installed Docker Scout
**1.23.1**, at **2026-11-16T21:27:34Z**, from the existing local archive:

```text
docker scout sbom --format spdx --output .runtime/milestone_7_8/local-gap-20261116/provenance/retained-image.spdx.json archive://.runtime/milestone_7_8/o1/image.tar
```

The command exited 0 and indexed **170 packages**, plus the document-root
package. The document contains **493 file records**, **1,007 relationships**
and **665 unique SPDX IDs**. All relationship references resolve. This was
structural validation, not validation against the full published SPDX schema.

An independent Python standard-library reader reconstructed installed metadata
from the ordered image layers, applying whiteouts without extracting an image
filesystem. All **44 Python distributions** match the SBOM's name/version
records. All **87 installed Debian binary packages** match name/version or
Debian source-package/version records. SPDX package totals include source and
other component records; they are not the installed binary-package count.

Scout gives an archive-derived synthetic identifier to its document root. That
identifier is not relabeled as the retained image digest. The hashed input
archive, verified OCI chain and independent installed-metadata comparison bind
this inventory to the retained runtime. License declarations are an inventory,
not a legal license-compliance conclusion. No new vulnerability scan, registry
lookup, image build/push or Azure operation was performed.

## Private receipts and remaining assertion

All raw metadata remains outside Git under
`.runtime/milestone_7_8/local-gap-20261116/provenance/`:

- `original-buildkit-provenance.json`: original blob hash `fcade045f8150da2a157432d2de91c869aa371d5217238a7aaa209189b17edf8`.
- `oci-provenance-validation.json`: SHA-256 `0bf2cb96a9fbd2a61281af6b775b6dbe4dd15ecdeb80f5d0495cc26daa13ef42`.
- `retained-image.spdx.json`: SHA-256 `85bae8643a259e0ff663a4da3aa7bccd462e2d5a7cd59123b8b1058a72539cc9`.
- `runtime-package-inventory.json`: SHA-256 `ebb6239d689fc7c31c292f231fff4ce0d4bb10ffcf4395a46b4ce2a4e56a7cae`.
- `sbom-validation-receipt.json`: SHA-256 `116432673d038dd8453b091aa1d7c77dfd4227b1b7d8307c6a525e19571f3f2e`.
- `search-record.json`, the local validation scripts and `scout-sbom.log` retain
  the bounded searches, commands and generation details.

**Closed local gaps:** original provenance located and its content-addressed
bindings verified; exact-retained-image dependency inventory generated and
independently checked. This SBOM is retrospective and unsigned.

**Still unresolved:** the existing architecture section 15.3 requirement for
signed build provenance and the corresponding signature-verification record.
No signing key or historical signature was invented. A trusted signing-identity
and verification decision, or recovery of an authentic existing signing record,
is still needed. A newly signed review attestation would need to say when and
by whom it was produced; it cannot be represented as the original builder's
signature. This is a local/release-provenance boundary, not justification for
a new paid managed campaign.
