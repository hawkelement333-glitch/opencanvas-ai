# License recommendation

Audit date: July 17, 2026

This document is an engineering and release-readiness recommendation, not legal advice.
The project owner must make the final licensing decision after checking the current OpenAI
Build Week and submission-platform rules.

## Recommendation before release

Keep the project **All Rights Reserved** while the product and commercialization strategy
are unsettled. Do not add an open-source `LICENSE` silently. The repository currently has a
`COPYRIGHT` and `NOTICE`, but no license grant.

The verified Build Week FAQ/rules allow either a public repository with relevant licensing or a
private repository shared with `testing@devpost.com` and `build-week-event@openai.com`. Before
judges receive the repository, the owner should choose one of these paths:

1. **Recommended while All Rights Reserved:** keep the repository private and share it with both
   required judging addresses. This path does not require an open-source license.
2. If Patrick explicitly approves a public open-source release, add Apache License 2.0
   (recommended over MIT for this project) before making the repository public.
3. If a public but proprietary/source-available strategy is desired, obtain an explicit legal
   review of the proposed inspection and evaluation permission before publication. No such
   permission is granted by the present files.

## What copyright already does

Original project code and documentation generally receive copyright protection
automatically when fixed in a tangible form, subject to applicable law and ownership facts.
Registration is not claimed. Copyright does not protect every idea, method, fact, interface,
or independently created implementation.

The notice `Copyright (c) 2026 Patrick Parke. All rights reserved.` identifies the claimed
owner and year and makes the reservation of rights explicit. It does not create copyright,
prove ownership, register the work, or create protection beyond applicable law.

## Option comparison

### Proprietary / All Rights Reserved

- Grants no general permission to copy, modify, distribute, sublicense, or sell the project.
- Best preserves flexibility for private commercialization, dual licensing, or later investor
  review.
- Does not stop independent development, lawful exceptions, or infringement by itself.
- A public repository without a license is visible but is not meaningfully open source; judges
  still need a valid basis to inspect and run it.
- Provides no patent license to recipients.

This is preferable before commercialization when the owner has not chosen a community or
commercial licensing model and competition rules do not demand an open-source grant.

### MIT License

- Permits use, copying, modification, distribution, sublicensing, and sale, including
  commercial use, with preservation of the copyright and license notice.
- Is short and widely understood.
- Includes warranty and liability disclaimers.
- Does not contain an express contributor patent license or patent-termination clause.
- Permits proprietary derivatives and does not require source disclosure.

### Apache License 2.0

- Permits broad commercial and noncommercial use, modification, and distribution.
- Requires preservation of the license and relevant notices and identification of modified
  files.
- Includes an express patent license from contributors and patent-litigation termination.
- Permits proprietary derivatives and does not require source disclosure.
- Is longer and imposes more notice administration than MIT.

Apache 2.0 may be preferable to MIT for an AI product because its express contributor patent
terms reduce ambiguity as outside contributors and commercially relevant implementations are
added. It does not grant rights to third-party models, datasets, trademarks, or patents that a
contributor does not control.

## Commercial and dependency implications

All three project-level choices can coexist with the direct permissively licensed dependencies
identified in `THIRD_PARTY_NOTICES.md`, provided each dependency's conditions are honored.
The `orjson` distribution declares `MPL-2.0 AND (Apache-2.0 OR MIT)` and needs special review
when shipping binaries or modifying covered files; its file-level copyleft does not ordinarily
require unrelated OpenCanvas source to be opened.

A project license cannot relicense third-party code, OpenAI services, uploaded user content, or
material supplied under separate terms. API use and competition participation remain subject
to their own terms.

## Competition-specific limitation

The current official [Build Week FAQ](https://openai.devpost.com/details/faqs) and
[rules](https://openai.devpost.com/rules) were checked on July 17, 2026. They allow a public
repository with relevant licensing or a private repository shared with
`testing@devpost.com` and `build-week-event@openai.com`. They do not require an open-source
license for the private-sharing path.

The recommended submission posture is therefore: retain All Rights Reserved, keep the repository
private, and grant both judging addresses access. Making the repository public or adding
Apache-2.0 still requires Patrick's explicit approval. Re-check the live rules immediately before
submission because competition terms can change; repository access, Devpost submission, demo
publication, and final legal approval remain manual actions.
