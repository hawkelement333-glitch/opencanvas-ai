# Milestone 7.7 Publication Lifecycle Continuation

## Local consolidation boundary

The only production publication orchestrator is
`api_image_publication._publish_api_image`. It has two explicit entry modes:
`FRESH_UPLOAD` and `ALREADY_PUSHED_RECONCILIATION`. The retired standalone
finalizer command cannot materialize or consume a second ledger.

The canonical order is: admit the current image record; create the ephemeral
publisher; prove initial denial; grant exact `pull,push`; publish and verify
the immutable digest; revoke and prove publisher denial; delete the publisher;
create a distinct ephemeral finalizer; grant exact `pull,delete`; delete only
the exact mutable source tag; normalize `tags: null` and `tags: []` as empty;
prove the immutable manifest remains; revoke and prove finalizer denial; delete
the finalizer; persist sanitized publication evidence; hand the immutable
digest to downstream deployment.

No downstream step may build, push, recreate a source tag, use a mutable tag,
issue a second publication ledger, or run the retired finalizer command.

## Reachability inventory

| Path                                                    | Classification                           | Disposition                                                                                                                           |
| ------------------------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `managed_binding_lifecycle._publish_api_image_stage`    | `CANONICAL_COMPLETE` wrapper             | Delegates without publication logic.                                                                                                  |
| `api_image_publication._publish_api_image_stage`        | `CANONICAL_COMPLETE` entry               | Persists only a completed immutable-digest result.                                                                                    |
| `api_image_publication._publish_api_image`              | `CANONICAL_COMPLETE` orchestrator        | Owns admission, publisher, upload, revocation, finalizer handoff, and immutable reference.                                            |
| `reconcile-already-pushed-publication`                  | `CANONICAL_COMPLETE` reconciliation entry | Requires integrity-bound retained push evidence and a read-only immutable-registry observation; it has no upload authority or Docker push path. |
| `acr_tag_finalization.finalize_current_publication`     | `CANONICAL_COMPLETE` internal transition | Owns only exact finalizer authority, one source-tag deletion, null/empty tag normalization, manifest survival, and finalizer cleanup. |
| `acr_tag_finalization.execute_finalization` and `main`  | `OBSOLETE`                               | The standalone command is retired and cannot consume a second ledger.                                                                 |
| publisher-side `_remove_source_tag` and failure cleanup | `OBSOLETE`                               | Removed: `pull,push` can never delete the mutable tag.                                                                                |
| lifecycle post-secret and downstream stages             | `CANONICAL_COMPLETE` consumers           | Require the persisted immutable digest; they contain no push or tag-delete logic.                                                     |
| test fixtures and parser checks                         | `TEST_ONLY`                              | Exercise token scope, propagation, parsers, evidence, and failure cleanup.                                                            |

No production publication-capable path remains `UNKNOWN`, and the state machine
rejects skipped, repeated, or out-of-order states.

## Regression matrix

The affected tests cover BuildKit isolation, Docker/DNS primary-error
preservation, push evidence persistence, `AcrPush` deletion denial, exact
`pull,push` versus `pull,delete` scope, transient OAuth `401` and `403`, empty
manifest HEAD bodies, raw-manifest versus ACR-properties parsing, distinct
manifest/config identities, post-delete `null` and empty tags, independent
control-plane and image-source commits, current-image finalizer reachability,
outer cleanup, finalizer cleanup after parser/network failures, immutable-digest
handoff, historical-image drift rejection, and registration of every lifecycle
publication entrypoint. The pure simulations cover transient-401 success,
transient-403 success, and propagation timeout with no delete transition.

## Future live continuation contract

A future Azure continuation must first reconcile the independently recorded
cleanup failure and prove cleanup generation 2 executable. It may then invoke
only `reconcile-already-pushed-publication` from `PAUSED_PRESERVED`, using a
valid `AlreadyPushedPublicationRecord` and an integrity-bound read-only registry
observation. This mode must not build, push, create an upload publisher, grant
`AcrPush`, or issue a new full publication ledger. If the source tag remains,
it invokes the same internal exact `AcrPull,AcrDelete` finalizer once; if the
tag is already absent while the immutable manifest remains proved, no finalizer
is created. In either case it persists the immutable digest before downstream
handoff.

This document records local control flow only. It does not constitute live
Azure publication, finalization, runtime deployment, migration, validation,
soak, cleanup, or Milestone 7.8 authorization.

## Truthful already-pushed evidence reconstruction

The historical Docker-push evidence is immutable. It retains the successful
push interval, exit and timeout state, sanitized output hashes, source commit,
canonical build-input hash, local image/config identity, platform, repository,
source tag, and its integrity values. It does **not** retain the immutable
registry-manifest digest. That missing field must never be added to the
historical artifact or represented as if it had been observed during the push.

| Field | Historical source | State | Future live source | Rule |
| --- | --- | --- | --- | --- |
| Image source, build input, local image ID, config digest | Prebuilt image and Docker-push evidence | Retained | None | Must agree exactly. |
| Repository, source tag, platform, push timestamps, exit state, output hashes | Docker-push evidence | Retained | None | Must agree exactly; never rewritten. |
| Registry login-server binding | Historical host fingerprint | Retained as fingerprint | Read-only registry observation | The configured private host must hash to the retained value. |
| Immutable manifest digest and raw manifest-body hash | None | Missing historically | Read-only registry observation | Required; inference is prohibited. |
| Source-tag presence and source-tag digest | None | Missing historically | Read-only registry observation | If present, it must point to the observed immutable digest. |
| Current control-plane HEAD authorization | None | Missing historically | Narrow reconstruction authorization | Required and integrity-bound. |
| Cleanup generation/deadline and cost ceiling | Future authorization | Future binding | Narrow reconstruction authorization | Must be generation 2 and within the authorized cost boundary. |

The local `HistoricalPushEvidence` model contains only the retained fields.
`LiveRegistryPublicationObservation` is an integrity-bound, sanitized,
read-only future observation: it includes the raw manifest-body SHA-256,
manifest/config identities, platform, media type, read-only request classes,
sanitized statuses/correlation hashes, and an explicit `mutationPerformed=false`
assertion. It is fresh for at most fifteen minutes.

`AlreadyPushedReconstructionAuthorization` is local data, not a live receipt.
It binds the current control-plane HEAD, historical and live integrity values,
cleanup generation/deadline, $225 ceiling, and only
`reconcile-already-pushed-publication`. It expressly prohibits build, push,
retag, upload-publisher creation, `AcrPush`, and manifest or repository
deletion.

Only `reconstruct_already_pushed_publication_record` may join those evidence
classes. It recomputes the current canonical build-input hash and fails closed
unless every image identity, registry host binding, source-tag relationship,
freshness bound, and integrity value agrees. Its output is a new record marked
exactly `RECONSTRUCTED_FROM_LIVE_READ_ONLY_REGISTRY_PROOF`; the historical
artifacts remain unchanged. The output can enter only
`PublicationMode.ALREADY_PUSHED_RECONCILIATION`.

The future `AlreadyPushedReconciliationReceipt` is also modeled locally. Before
any live issuance it must bind the control-plane and image-source commits,
build input, local/config/manifest identities, reconstructed/historical/live
integrities, cleanup generation/deadline, $225 ceiling, the exact
`AcrPull,AcrDelete` finalizer roles, and one source-tag delete maximum. It
prohibits a build, push, retag, upload publisher, `AcrPush`, manifest deletion,
repository deletion, a second receipt, and a second finalizer.

The next live-only continuation must: prove generation-2 cleanup and cost
safety; capture one read-only registry observation; write its integrity-bound
observation; create a narrow current-HEAD reconstruction authorization;
reconstruct and validate the canonical record; issue one narrow reconciliation
receipt; run `reconcile-already-pushed-publication`; create one finalizer only
if the source tag is present; and then hand the immutable digest downstream.
It must not edit this repository while active.

The single future live authorization must name
`api_image_publication._publish_api_image` with
`PublicationMode.ALREADY_PUSHED_RECONCILIATION` as the canonical state machine,
use
the already-pushed bridge image from source commit
`7321e69b8296660c53015a05e5b01b9adf1e302f`, reconcile the existing registry
state first, and create only one ephemeral finalizer after publisher revocation.
It may grant only `AcrPull` and `AcrDelete`, retain the finalizer through its
bounded OAuth-propagation window, delete the existing source tag exactly once,
prove immutable-manifest survival, persist `IMAGE_PUBLISHED` and
`PUBLISHER_REVOKED`, and hand only the immutable digest to downstream stages.
It must prohibit repository edits while active, rebuilding, pushing, retagging,
a second full publication ledger, a second finalizer, mutable-tag deployment,
and alternate publication implementations.
