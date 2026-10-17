# DEMO design brief

The primary audience is a visitor who has never worked on this project. Lead with
how the system handles information and engineering constraints; the five frozen
strategies are application examples, not the homepage or a performance claim.

## Visual references

Adapted principles from [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md):
[Vercel](https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/vercel/DESIGN.md)
for restrained type, thin dividers and grid discipline;
[Stripe](https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/stripe/DESIGN.md)
for spacious technical explanations and diagram-led product storytelling.
The user also prefers the visual character of large US investment firms and
technology companies. [Goldman Sachs](https://www.goldmansachs.com/) and
[BlackRock](https://www.blackrock.com/corporate) inform the editorial hierarchy
and restrained institutional tone; diagrams provide the technical character.
The latest explicit references are [Citadel](https://www.citadel.com/) and
[Apple](https://developer.apple.com/documentation/technologyoverviews/liquid-glass): institutional hierarchy and restrained
navy, with translucent white controls, cold blue/cyan light and subtle optical
depth. Glass is confined to navigation and diagrams; data, alerts and financial
status retain opaque readable surfaces. Blur uses small surfaces, no animated
background or full-screen filter, and an opaque reduced-transparency fallback.
No external assets, fonts, copied brand artwork or frontend dependency bundle.

## Composition and interaction

- A light, full-width exhibition shell: white / cool neutral surfaces, navy ink,
  blue active state and a restrained cyan diagram accent. Shared tokens stay in
  the existing theme; console-specific composition stays in console.css.
- Start with a large interactive architecture exhibit: information availability,
  frozen inference, risk allocation and simulated execution. Explain inputs,
  transformations and outputs; traceability and cache discipline cross the chain.
- Four sections within one workspace: technology, applications, evidence, daily
  simulation. Keep legacy URLs as redirects to the appropriate section.
- Application cases have three related views: model principles, the selected method's
  existing ML workbench, and recorded decisions. The five methods retain their native
  outputs; a score, action proposal and gross-exposure class are not interchangeable.
- Keep the accepted five-method picker above all application tools; use its original
  focus callback and roster projection. Other methods remain queryable without
  changing the showcase. Do not repeat the strategy selector inside the workbench.
- Carry one strategy, sample, observation date and security focus across ML, charts
  and historical queries. Consume legacy navigation through the shared shell, rather
  than resetting the view on a rerun. No parallel model or account state.
- Load only the selected section and requested method projection; leave unrelated
  performance histories closed. The illustration does not invoke models, data
  acquisition or account queries. Unavailable historical records stay unavailable.
- Language and display controls stay visible. Preserve canonical selections across
  Chinese, English and Japanese, and reduce motion when requested by the system.
- Illustrations are labelled as explanatory. Do not synthesize account status,
  returns or measured resource improvements. Research, targets, orders and fills
  retain their original owners and timestamps.

## Guided demonstration and research use

Reuse the existing demo_tour lifecycle for a seven-stop system walkthrough.
Each stop explains the problem, the implemented mechanism and its engineering
benefit, then points to evidence. Do not present unmeasured speed, predictive
superiority or a frozen replay as new validation. Exiting or manually navigating
keeps the chosen strategy/date; navigation never submits an order.

Research mode opens existing queries directly. Presentation mode starts with
explanations and reveals recorded details on request. The technical capability
explorer exposes six direct capability choices and retains the complete catalogue.
It reuses existing source-defined descriptions, feature atlas and synthetic
PIT demonstration; it distinguishes historical research from current application.

## Acceptance

Verify actual desktop and narrow-screen rendering, diagram keyboard interaction,
all three languages, selection persistence, chart and recorded table availability,
and the original simulated-account status. Opening or switching the exhibit must
not execute trades or recompute research. Engineering checks do not establish
research effectiveness or user acceptance of the visual design.

Daily browsing reuses one ephemeral account capture through each selected ML render.
Native method calendars project validated dates and source identity rather than
copying the complete HGB history tree. Historical samples read no account state;
HGB retains its full package path and source validation remains authoritative.
