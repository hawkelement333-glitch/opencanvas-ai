# SolarPlexus Mobius Visual System

Milestone 3.75 establishes a living knowledge universe for the existing product. The visual system must clarify evidence, context, citations, processing state, and Trace before it adds atmosphere.

## Brand Rules

- Product name: `SolarPlexus Mobius`.
- Use a near-black cosmic base, ultraviolet depth, solar-gold emphasis, and cyan evidence accents.
- The `O` in `SolarPlexus` may carry a restrained black-hole treatment when space allows.
- Keep the ring visible and the full wordmark readable at small sizes.
- Use a normal capital `B` in `Mobius`; do not replace it with a symbol.
- Avoid generic wallpaper, heavy blur behind body text, constant particles, and decorative motion.

## Token System

- Background: `--bg`, `--bg-deep`.
- Surfaces: `--surface`, `--surface-raised`, `--surface-soft`.
- Text: `--text`, `--text-soft`, `--text-faint`.
- Lines: `--line`, `--line-strong`.
- Semantic accents: `--solar`, `--violet`, `--violet-deep`, `--cyan`, `--success`, `--danger`.

Tokens are global CSS custom properties so the shell, canvas, evidence panel, documents, and account pages can share the same contrast model.

## Typography

Use the existing system font stack. Keep headings compact inside operational surfaces. Do not scale type with viewport width except existing route-level empty states.

## Universe Hierarchy

- Universe: application shell, account controls, runtime state, and system entry points.
- Galaxy · Workspace: a user-owned workspace boundary.
- Solar System: a canvas presented as a focused project cluster inside a workspace. Navigation uses the compact `Solar System · {canvas name}` form so real names remain legible.
- Star · Answer Hub: generated answers and major response anchors.
- Planet · Document: durable source documents.
- Moon · Supporting Note: user-authored notes.
- Asteroid · Evidence Fragment: citations, chunks, and small evidence passages.
- Person: stored person objects when the application has real person data.
- Background Context: stable supporting metadata and definitions.
- Observed Change: dynamic evidence, alerts, conflicts, or processing discoveries.
- Society · Organization Network: stored organizations, teams, or stakeholder networks.

Every metaphorical label must be paired with the real product label.

## Node Families

- Notes use `Moon · Supporting Note`.
- Documents use `Planet · Document` and show file type, size, passage count, and processing state.
- AI responses use `Star · Answer Hub` and show citation availability.
- Citations use `Asteroid · Evidence Fragment` and preserve exact source identity.

Nodes must always display real titles and real object types. Do not create decorative-only nodes.

## Edge Families

- `Pathway · User-created relationship`: user-created canvas edge.
- `Pathway · Generated from selected context`: generated answer linked to selected context.
- `Pathway · Citation to exact source passage`: validated citation edge.

Pathways require text labels or inspector explanations and must not rely on color alone. The compact canvas legend uses `Relationship`, `Selected context`, and `Citation`, while accessible names retain the full semantic labels above.

## Evidence States

Preserve the Milestone 3.5 evidence states:

- Supported
- Inference
- Conflict
- Unsupported
- Insufficient evidence
- Excluded from context

Each state needs a text label, icon, semantic color, and accessible explanation when surfaced.

## Processing States

Use backend state names directly:

- Uploaded
- Queued
- Processing
- Extracting
- Chunking
- Embedding
- Indexing
- Ready
- Retryable failure
- Retrying
- Permanent failure
- Deleting
- Deleted

Do not invent percentages. Pair construction-like language with the real stage label.

## Semantic Zoom

- Galaxy scale: workspace boundaries and high-level health.
- Solar-system scale: canvas resources, major nodes, and pathways.
- Star/planet scale: notes, documents, responses, processing state, and context state.
- Moon/asteroid scale: citations, chunks, passages, claims, and local context.

Essential controls must remain available at every scale.

## City-Like Resource Model

Resource displays can show only calculated application data:

- Documents
- Ready sources
- Processing sources
- Failed sources
- Selected context
- Citations
- Responses
- Token or cost data where available

Do not create a fake economy, population, traffic, or progress model.

## Accessibility

- Preserve visible focus states.
- Meet WCAG AA for core text and controls.
- Use labels, icons, and shape or line treatment, not color alone.
- Keep keyboard-accessible citations, source preview, Trace links, and canvas controls.
- Ensure screen-reader labels use plain product terms alongside the metaphor.

## Motion

Use motion only for state communication: selection, context activation, processing pulse, citation focus, panel entrance, and user-triggered pathway tracing. Respect `prefers-reduced-motion`.

## Responsive Behavior

Target viewports:

- `1440 x 900`
- `1280 x 800`
- `1024 x 768`
- `768 x 1024`
- `390 x 844`

Narrow screens should use focused panels or list-like views instead of shrinking the full canvas into an unreadable map.

## Performance

- Avoid large background images.
- Preserve React Flow performance.
- Prefer CSS gradients and linework over heavy animation libraries.
- Use level-of-detail rendering where practical.
- Keep bundle-size changes inspectable.

## Demo Preservation

`APP_MODE=demo` and `pnpm demo` remain deterministic. Visual changes may improve presentation, but they must not change demo facts, seeded content, supported answers, insufficient-evidence behavior, citations, exact passages, Trace outcomes, protected identifiers, or provider isolation.
