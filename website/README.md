# Documentation site

The [Docusaurus](https://docusaurus.io/) site that publishes this repository's
documentation. This folder is the **only** Node.js surface in the repository —
the root stays Python-only.

## Run it

```bash
cd website
npm install
npm run start     # dev server with live reload
npm run build     # production build into website/build
npm run typecheck # tsc over the config, sidebar and homepage
```

## How content gets in

**No content is copied, moved, or symlinked.** The docs plugin's `path` points
at the repository root and `include` is restricted to two globs:

```ts
path: '..',
include: ['docs/**/*.md', 'operating-manual/**/*.md'],
```

So `docs/` and `operating-manual/` are published exactly where they already
live. This is why every relative link that works when browsing the repository on
GitHub also works on the site, and why there are no redirects to maintain.

To add a page, add a Markdown file under `docs/` or `operating-manual/` and list
it in `sidebars.ts`. Nothing in this folder needs to change.

`numberPrefixParser` is off, so URLs keep the repository's own filenames —
`docs/17-cli-reference.md` is served at `/docs/17-cli-reference`. That is
deliberate: the handbook refers to its own pages by number, and turning the
parser on collides `docs/02-architecture.md` with the `docs/architecture/`
folder.

## The link check

`onBrokenLinks` is set to `throw`, and so is the Markdown link hook. **A green
build is the link check** — every internal link across all 129 pages is
resolved at build time.

Do not downgrade either setting to `warn` to get a build passing. If a link
breaks, fix the link. Links that legitimately point outside the two doc trees
(into `src/`, `harness/`, `templates/`, `apps/`) are written as absolute GitHub
URLs so they resolve both on the site and in the repository.

`onBrokenAnchors` is left at `warn`; heading anchors across 400-odd links are
not worth a hard failure.

## Publishing

The site is hosted on **GitHub Pages** at
<https://michaelwclark.github.io/genomes_agentic_os/>, which is what `url` and
`baseUrl` in `docusaurus.config.ts` already encode.

`.github/workflows/docs.yml` builds on every pull request that touches the
docs and, on a push to `main`, deploys that same build. The `deploy` job needs
`build`, so a broken internal link stops the publish.

**One-time repository setting.** Pages has to be turned on with GitHub Actions
as the source before the first deployment, or the `deploy` job fails with a 404
from the Pages API. Either set *Settings → Pages → Source* to *GitHub Actions*,
or run:

```bash
gh api -X POST repos/michaelwclark/genomes_agentic_os/pages -f 'build_type=workflow'
```

This cannot be folded into the workflow. `actions/configure-pages` has an
`enablement` input, but it rejects `GITHUB_TOKEN` and requires a personal access
token or GitHub App credential. Adding one would hand the docs workflow a
standing repository-administration secret to save a single click.

## Structure

| Path | What it is |
| --- | --- |
| `docusaurus.config.ts` | Site config, navbar, footer, theme |
| `sidebars.ts` | The four sidebars and the information architecture |
| `src/pages/index.tsx` | The landing page |
| `src/css/custom.css` | Theme variables, light and dark |

The four sidebars, in order of how much prior knowledge they assume: **Start
here** (plain-English introduction, source lives in `docs/start/`), **Handbook**
(the numbered pages, grouped by task), **Reference** (look-it-up material), and
**Operating manual**.
