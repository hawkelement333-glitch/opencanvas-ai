# Third-party notices

Audit date: July 17, 2026

OpenCanvas AI uses the third-party packages listed below. They remain the property of their
respective copyright holders and are governed by their own licenses, not the OpenCanvas AI All
Rights Reserved notice.

This is a direct-dependency and material-asset inventory, not an exhaustive legal opinion or a
substitute for reviewing the exact resolved distributions. JavaScript versions are pinned in
`pnpm-lock.yaml`. Python requirements are bounded ranges and are not resolved in a committed
lockfile; the observed validation-environment versions below are not reproducible pins and must
be re-audited for each release artifact.

## Redistribution conditions

The direct licenses are generally commercial-use-compatible:

- **MIT:** retain the upstream copyright and permission notice.
- **ISC:** retain the upstream copyright, permission, and warranty disclaimer.
- **BSD-3-Clause:** retain the upstream copyright, conditions, and disclaimer and do not imply
  endorsement.
- **Apache-2.0:** distribute the license, preserve applicable notices, mark modified files, and
  comply with its patent and NOTICE provisions.
- **MPL-2.0:** preserve notices and make source for modified MPL-covered files available under
  MPL-2.0 when its distribution conditions apply. MPL is file-level copyleft; it does not
  ordinarily require unrelated OpenCanvas files to use MPL.

When dependencies are shipped in a browser bundle, container, executable, or other binary,
include this inventory and the complete copyright/license texts from the exact resolved package
artifacts. Package source links below identify the authoritative upstream projects. No direct
dependency reviewed declared GPL, AGPL, a noncommercial restriction, or an unknown/custom
license.

## JavaScript runtime dependencies

| Package                 | Version | License | Upstream source                                               | Redistribution review                   |
| ----------------------- | ------: | ------- | ------------------------------------------------------------- | --------------------------------------- |
| `@tanstack/react-query` | 5.101.2 | MIT     | [TanStack/query](https://github.com/TanStack/query)           | Permitted; retain notice                |
| `@xyflow/react`         | 12.11.2 | MIT     | [xyflow/xyflow](https://github.com/xyflow/xyflow)             | Permitted; retain notice                |
| `clsx`                  |   2.1.1 | MIT     | [lukeed/clsx](https://github.com/lukeed/clsx)                 | Permitted; retain notice                |
| `lucide-react`          | 0.468.0 | ISC     | [lucide-icons/lucide](https://github.com/lucide-icons/lucide) | Permitted; retain notice and disclaimer |
| `next`                  | 16.2.10 | MIT     | [vercel/next.js](https://github.com/vercel/next.js)           | Permitted; retain notice                |
| `react`                 |  19.2.7 | MIT     | [facebook/react](https://github.com/facebook/react)           | Permitted; retain notice                |
| `react-dom`             |  19.2.7 | MIT     | [facebook/react](https://github.com/facebook/react)           | Permitted; retain notice                |
| `zod`                   |   4.4.3 | MIT     | [colinhacks/zod](https://github.com/colinhacks/zod)           | Permitted; retain notice                |
| `zustand`               |  5.0.14 | MIT     | [pmndrs/zustand](https://github.com/pmndrs/zustand)           | Permitted; retain notice                |

The competition build preserves React Flow's visible on-canvas attribution. React Flow remains
MIT-licensed; its current official policy says the attribution is not a legal license condition,
while asking users who hide it to support the project. Review the
[React Flow attribution policy](https://reactflow.dev/api-reference/types/pro-options) before any
future change to that display.

## JavaScript development dependencies

These tools normally are not shipped as application runtime code, but their notices must be
preserved if they are redistributed.

| Package                       | Version | License    | Upstream source                                                                                   |
| ----------------------------- | ------: | ---------- | ------------------------------------------------------------------------------------------------- |
| `@testing-library/jest-dom`   |   6.9.1 | MIT        | [testing-library/jest-dom](https://github.com/testing-library/jest-dom)                           |
| `@testing-library/react`      |  16.3.0 | MIT        | [testing-library/react-testing-library](https://github.com/testing-library/react-testing-library) |
| `@testing-library/user-event` |  14.6.1 | MIT        | [testing-library/user-event](https://github.com/testing-library/user-event)                       |
| `@playwright/test`            |  1.61.1 | Apache-2.0 | [microsoft/playwright](https://github.com/microsoft/playwright)                                   |
| `@types/node`                 | 24.10.1 | MIT        | [DefinitelyTyped](https://github.com/DefinitelyTyped/DefinitelyTyped)                             |
| `@types/react`                | 19.2.10 | MIT        | [DefinitelyTyped](https://github.com/DefinitelyTyped/DefinitelyTyped)                             |
| `@types/react-dom`            |  19.2.3 | MIT        | [DefinitelyTyped](https://github.com/DefinitelyTyped/DefinitelyTyped)                             |
| `eslint`                      |  9.39.1 | MIT        | [eslint/eslint](https://github.com/eslint/eslint)                                                 |
| `eslint-config-next`          | 16.2.10 | MIT        | [vercel/next.js](https://github.com/vercel/next.js)                                               |
| `jsdom`                       |  27.4.0 | MIT        | [jsdom/jsdom](https://github.com/jsdom/jsdom)                                                     |
| `prettier`                    |   3.9.5 | MIT        | [prettier/prettier](https://github.com/prettier/prettier)                                         |
| `typescript`                  |   6.0.2 | Apache-2.0 | [microsoft/TypeScript](https://github.com/microsoft/TypeScript)                                   |
| `vitest`                      |  4.1.10 | MIT        | [vitest-dev/vitest](https://github.com/vitest-dev/vitest)                                         |

## Material JavaScript transitive artifacts

An installed production-tree license scan reported MIT, Apache-2.0, ISC, BSD-3-Clause, 0BSD,
CC-BY-4.0, and one `Apache-2.0 AND LGPL-3.0-or-later` platform package. The following transitive
artifacts are material enough to call out separately:

| Package/artifact                             | Locked version | License                                                                                  | Upstream source                                                                                                     | Release implication                                                                                                                                                |
| -------------------------------------------- | -------------: | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sharp` and `@img/sharp-*` platform packages |         0.34.5 | Sharp: Apache-2.0; audited prebuilt platform package: `Apache-2.0 AND LGPL-3.0-or-later` | [lovell/sharp](https://github.com/lovell/sharp) and [lovell/sharp-libvips](https://github.com/lovell/sharp-libvips) | Prebuilt native artifacts include LGPL-covered libvips components; preserve notices and satisfy the exact binary distribution's LGPL source/relinking requirements |
| `caniuse-lite` data                          |   1.0.30001806 | CC-BY-4.0                                                                                | [browserslist/caniuse-lite](https://github.com/browserslist/caniuse-lite)                                           | Attribution is required when the data is redistributed                                                                                                             |

The installed scan ran on Windows, while the web container targets Alpine Linux. Platform-specific
Sharp/libvips packages can differ. Generate and review notices inside every actual target image;
do not treat the Windows package list as the final Docker-image SBOM. LGPL is weak copyleft, but
its conditions still matter for proprietary binary redistribution.

## Python runtime dependencies

The observed version is from the July 17 validation virtual environment. License expressions
were verified from installed metadata and official PyPI metadata. The declared ranges in
`apps/api/pyproject.toml` can resolve differently on a clean install.

| Package             | Declared range | Observed version | License                           | Upstream source                                                             | Redistribution review                                                           |
| ------------------- | -------------: | ---------------: | --------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `aiofiles`          |   `>=24.1,<26` |           25.1.0 | Apache-2.0                        | [Tinche/aiofiles](https://github.com/Tinche/aiofiles)                       | Permitted; Apache notices apply                                                 |
| `alembic`           |    `>=1.16,<2` |           1.18.5 | MIT                               | [sqlalchemy/alembic](https://github.com/sqlalchemy/alembic)                 | Permitted; retain notice                                                        |
| `asyncpg`           |    `>=0.30,<1` |           0.31.0 | Apache-2.0                        | [MagicStack/asyncpg](https://github.com/MagicStack/asyncpg)                 | Permitted; Apache notices apply                                                 |
| `fastapi`           |   `>=0.116,<1` |          0.139.2 | MIT                               | [fastapi/fastapi](https://github.com/fastapi/fastapi)                       | Permitted; retain notice                                                        |
| `httpx`             |    `>=0.28,<1` |           0.28.1 | BSD-3-Clause                      | [encode/httpx](https://github.com/encode/httpx)                             | Permitted; BSD notice applies                                                   |
| `openai`            |       `>=2,<3` |           2.46.0 | Apache-2.0                        | [openai/openai-python](https://github.com/openai/openai-python)             | Permitted; Apache notices apply; API terms are separate                         |
| `orjson`            |    `>=3.10,<4` |           3.11.9 | `MPL-2.0 AND (Apache-2.0 OR MIT)` | [ijl/orjson](https://github.com/ijl/orjson)                                 | Permitted with multi-license/MPL obligations; review binaries and modifications |
| `pgvector`          |     `>=0.4,<1` |            0.5.0 | MIT                               | [pgvector/pgvector-python](https://github.com/pgvector/pgvector-python)     | Permitted; retain notice                                                        |
| `pydantic-settings` |    `>=2.10,<3` |           2.14.2 | MIT                               | [pydantic/pydantic-settings](https://github.com/pydantic/pydantic-settings) | Permitted; retain notice                                                        |
| `python-multipart`  |  `>=0.0.20,<1` |           0.0.32 | Apache-2.0                        | [Kludex/python-multipart](https://github.com/Kludex/python-multipart)       | Permitted; Apache notices apply                                                 |
| `pypdf`             |     `>=5.7,<7` |           6.14.2 | BSD-3-Clause                      | [py-pdf/pypdf](https://github.com/py-pdf/pypdf)                             | Permitted; BSD notice applies                                                   |
| `python-docx`       |     `>=1.2,<2` |            1.2.0 | MIT                               | [python-openxml/python-docx](https://github.com/python-openxml/python-docx) | Permitted; retain notice                                                        |
| `sqlalchemy`        |  `>=2.0.40,<3` |           2.0.51 | MIT                               | [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy)           | Permitted; retain notice                                                        |
| `structlog`         |   `>=25.4,<26` |           25.5.0 | `MIT OR Apache-2.0`               | [hynek/structlog](https://github.com/hynek/structlog)                       | Permitted under the selected upstream option                                    |
| `uvicorn`           |    `>=0.35,<1` |           0.51.0 | BSD-3-Clause                      | [Kludex/uvicorn](https://github.com/Kludex/uvicorn)                         | Permitted; BSD notice applies                                                   |

## Python build and development dependencies

| Package          | Declared range |             Observed version | License    | Upstream source                                                                                 |
| ---------------- | -------------: | ---------------------------: | ---------- | ----------------------------------------------------------------------------------------------- |
| `hatchling`      |       `>=1.27` | build-isolated; not retained | MIT        | [pypa/hatch backend](https://github.com/pypa/hatch/tree/master/backend)                         |
| `aiosqlite`      |    `>=0.21,<1` |                       0.22.1 | MIT        | [omnilib/aiosqlite](https://github.com/omnilib/aiosqlite)                                       |
| `mypy`           |    `>=1.17,<2` |                       1.20.2 | MIT        | [python/mypy](https://github.com/python/mypy)                                                   |
| `pytest`         |    `>=8.4,<10` |                        9.1.1 | MIT        | [pytest-dev/pytest](https://github.com/pytest-dev/pytest)                                       |
| `pytest-asyncio` |     `>=1.1,<2` |                        1.4.0 | Apache-2.0 | [pytest-dev/pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)                       |
| `ruff`           |    `>=0.12,<1` |                      0.15.22 | MIT        | [astral-sh/ruff](https://github.com/astral-sh/ruff)                                             |
| `testcontainers` |    `>=4.13,<5` |                       4.14.2 | Apache-2.0 | [testcontainers/testcontainers-python](https://github.com/testcontainers/testcontainers-python) |
| `types-aiofiles` |   `>=24.1,<26` |              25.1.0.20260518 | Apache-2.0 | [python/typeshed](https://github.com/python/typeshed)                                           |

## Material bundled assets and sample data

No fonts, icons outside the `lucide-react` dependency, images, videos, binary documents,
third-party datasets, or vendored source trees were found in the audited repository. The two
small text fixtures under `apps/api/tests/fixtures/` and the generated DOCX/PDF fixture content
appear to be project-specific synthetic test data. Ownership was assessed from repository
content only and was not independently proven.

## Release follow-up

Before distributing final Docker images or downloadable binaries:

1. Resolve exact Python versions with a reproducible lock or constraints artifact.
2. Generate a complete transitive software bill of materials and license bundle from the exact
   installed artifacts.
3. Verify that each release image retains the copied project notices, and add the complete
   third-party license bundle generated from that image's exact resolved artifacts.
4. Re-run dependency vulnerability and license scans after every resolution change.
