# Milestone 7.7 Publication Lifecycle Continuation

## Local consolidation boundary

The only production publication entrypoint is the `publish-api-image` stage of
the active Milestone 7.7 lifecycle ledger. The legacy standalone finalizer
command is retired; its finalization code is an internal transition invoked by
that stage and cannot materialize or consume a second ledger.

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
cleanup failure and prove a future executable cleanup path. It must then use
one fresh lifecycle ledger and one lifecycle process. The process may resume
only from the canonical `publish-api-image` state transition, with private
networking, exact repository scopes, and all evidence redacted. A failed
publisher or finalizer transition must revoke temporary authority and preserve
the environment; it must not open a parallel publication path.

This document records local control flow only. It does not constitute live
Azure publication, finalization, runtime deployment, migration, validation,
soak, cleanup, or Milestone 7.8 authorization.

The single future live authorization must name
`api_image_publication._publish_api_image` as the canonical state machine, use
the already-pushed bridge image from source commit
`7321e69b8296660c53015a05e5b01b9adf1e302f`, reconcile the existing registry
state first, and create only one ephemeral finalizer after publisher revocation.
It may grant only `AcrPull` and `AcrDelete`, retain the finalizer through its
bounded OAuth-propagation window, delete the existing source tag exactly once,
prove immutable-manifest survival, persist `IMAGE_PUBLISHED` and
`PUBLISHER_REVOKED`, and hand only the immutable digest to downstream stages.
It must prohibit local patching, rebuilding, pushing, retagging, a second
ledger, a second finalizer, mutable-tag deployment, and alternate publication
implementations.
