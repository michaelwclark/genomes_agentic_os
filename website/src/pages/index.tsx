import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

import styles from './index.module.css';

type Card = {
  title: string;
  href: string;
  body: string;
};

const FIRST_STOPS: Card[] = [
  {
    title: 'What this actually is',
    href: '/start/what-this-is',
    body: 'The problem it solves, in ordinary English, before any jargon. Read this one first.',
  },
  {
    title: 'Install it',
    href: '/start/install',
    body: 'Get the command-line tool, create an OS folder, and check that it worked.',
  },
  {
    title: 'The seven ideas',
    href: '/start/',
    body: 'Domains, projects, work items, workflows, automations, runs and hosts — one short page each.',
  },
  {
    title: 'Plain-English glossary',
    href: '/start/glossary',
    body: 'Every piece of internal vocabulary, translated. Keep it open in a second tab.',
  },
];

const DEEPER: Card[] = [
  {
    title: 'Handbook',
    href: '/docs/',
    body: 'The full numbered handbook, grouped by the job you are doing rather than by page number.',
  },
  {
    title: 'Command reference',
    href: '/docs/17-cli-reference',
    body: 'Every `agentic-os` command group, with flags and what each one writes to disk.',
  },
  {
    title: 'Operating manual',
    href: '/operating-manual/',
    body: 'The manual that gets copied into an installed OS: concepts, file formats, recipes, checklists.',
  },
];

function CardGrid({cards}: {cards: Card[]}) {
  return (
    <div className={styles.cardGrid}>
      {cards.map((card) => (
        <Link key={card.href} to={card.href} className={styles.card}>
          <Heading as="h3" className={styles.cardTitle}>
            {card.title}
          </Heading>
          <p className={styles.cardBody}>{card.body}</p>
        </Link>
      ))}
    </div>
  );
}

function Hero() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={styles.hero}>
      <div className="container">
        <p className={styles.heroEyebrow}>Documentation</p>
        <Heading as="h1" className={styles.heroTitle}>
          {siteConfig.title}
        </Heading>
        <p className={styles.heroSubtitle}>
          A shared filing system that you and your AI agents both work out of.
          The work lives in ordinary folders and files on your own machine, so
          every conversation picks up where the last one stopped instead of
          starting from nothing.
        </p>
        <div className={styles.heroButtons}>
          <Link className="button button--primary button--lg" to="/start/what-this-is">
            Start here
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/">
            Browse the handbook
          </Link>
        </div>
      </div>
    </header>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="Documentation"
      description="Genome's Agentic OS — a file-first operating system that people and AI agents share. Plain-English introduction, full handbook, and command reference.">
      <Hero />
      <main className="container margin-vert--xl">
        <section>
          <Heading as="h2" className={styles.sectionTitle}>
            New here
          </Heading>
          <p className={styles.sectionLede}>
            These four pages assume you know nothing about this system. They
            explain what each thing is for and where it applies before naming
            it.
          </p>
          <CardGrid cards={FIRST_STOPS} />
        </section>

        <section className="margin-top--xl">
          <Heading as="h2" className={styles.sectionTitle}>
            Once you know the shape of it
          </Heading>
          <p className={styles.sectionLede}>
            The reference material. Written for people who are already operating
            the system and need detail rather than orientation.
          </p>
          <CardGrid cards={DEEPER} />
        </section>
      </main>
    </Layout>
  );
}
