import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const GITHUB_REPO = 'https://github.com/michaelwclark/genomes_agentic_os';

/**
 * The site renders the repository's own markdown in place.
 *
 * `path` points at the repository root and `include` is restricted to the two
 * documentation trees, so `docs/` and `operating-manual/` are published exactly
 * where they already live. Nothing is copied, moved, or symlinked, which is why
 * every relative link that works on GitHub also works on the site.
 */
const config: Config = {
  title: "Genome's Agentic OS",
  tagline: 'A shared filing system your agents and you both work out of',
  favicon: 'img/favicon.ico',

  future: {
    v4: true,
  },

  url: 'https://michaelwclark.github.io',
  baseUrl: '/genomes_agentic_os/',
  organizationName: 'michaelwclark',
  projectName: 'genomes_agentic_os',
  trailingSlash: false,

  // A red build is the link check. Do not downgrade `onBrokenLinks`.
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'warn',

  markdown: {
    // Parse `.md` as CommonMark and `.mdx` as MDX. The repository's markdown is
    // written for GitHub and contains bare `<placeholder>` angle brackets that
    // MDX would reject.
    format: 'detect',
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          path: '..',
          include: ['docs/**/*.md', 'operating-manual/**/*.md'],
          exclude: ['**/node_modules/**'],
          // Keep the repository's own numbered filenames in the URL. Stripping
          // them would collide `docs/02-architecture.md` with the
          // `docs/architecture/` folder, and page numbers are how this
          // repository refers to its own handbook.
          numberPrefixParser: false,
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          editUrl: `${GITHUB_REPO}/tree/main/`,
          breadcrumbs: true,
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      defaultMode: 'dark',
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: "Genome's Agentic OS",
      logo: {
        alt: "Genome's Agentic OS",
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'startHere',
          position: 'left',
          label: 'Start here',
        },
        {
          type: 'docSidebar',
          sidebarId: 'handbook',
          position: 'left',
          label: 'Handbook',
        },
        {
          type: 'docSidebar',
          sidebarId: 'reference',
          position: 'left',
          label: 'Reference',
        },
        {
          type: 'docSidebar',
          sidebarId: 'manual',
          position: 'left',
          label: 'Operating manual',
        },
        {
          href: GITHUB_REPO,
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'New here',
          items: [
            {label: 'What this is', to: '/start/what-this-is'},
            {label: 'Install it', to: '/start/install'},
            {label: 'Plain-English glossary', to: '/start/glossary'},
          ],
        },
        {
          title: 'Go deeper',
          items: [
            {label: 'Handbook', to: '/docs/'},
            {label: 'CLI reference', to: '/docs/17-cli-reference'},
            {label: 'Operating manual', to: '/operating-manual/'},
          ],
        },
        {
          title: 'Source',
          items: [
            {label: 'GitHub', href: GITHUB_REPO},
            {label: 'Releases', href: `${GITHUB_REPO}/releases`},
          ],
        },
      ],
      copyright: `Genome's Agentic OS. Built and operated by Michael W Clark.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'toml', 'yaml', 'json', 'python', 'diff'],
    },
    docs: {
      sidebar: {
        hideable: true,
        autoCollapseCategories: true,
      },
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
