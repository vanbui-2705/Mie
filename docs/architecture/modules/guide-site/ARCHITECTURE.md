# Guide Site Module

## Scope

Owns the user-facing FlowMeta documentation website. It is currently a nested
Git repository and is not part of the parent repository's tracked source.

## Responsibilities

- Product guides and help content.
- Documentation navigation and presentation.
- Cloudflare/Vinext build and hosting metadata.
- Brand-aligned public documentation.

## Current source

- `guide-site/app/`
- `guide-site/content/`
- `guide-site/public/`
- `guide-site/tools/`
- `guide-site/package.json`
- Local repository metadata in `guide-site/.git`

## Boundaries

- Product behavior is documented here but implemented in other modules.
- Browser profiles, build outputs and screenshots are development artefacts.
- The nested repository must be handled explicitly before any future monorepo
  import; its history must not be discarded.

## Invariants

- User instructions match deployed behavior.
- Secrets and local browser profiles remain untracked.
- Hosting metadata is produced from the same source revision as the site build.

## Checks

- TypeScript and lint where configured.
- Next or Vinext production build.
- Link and mobile-layout smoke tests.

