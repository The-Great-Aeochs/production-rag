# UI design and frontend maintenance

The interface prioritizes trying a sample question, reading its answer, and
checking a source. The visual choices are a design judgment for a technical
product; there is no objective test for whether an interface "looks AI-generated."

## Guidance used

- [Nielsen Norman Group: usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/): clear status, familiar language, consistency,
  error prevention, user control, and minimal presentation. The demo identifies
  prewritten answers, unavailable live inference has an explicit explanation,
  streaming can be stopped, role edits require Save, and removing a member
  requires confirmation.
- [NN/g: visual design principles](https://www.nngroup.com/articles/principles-visual-design/): use hierarchy, scale, and contrast to prioritize the task.
  The homepage places the working demo before implementation details and uses
  one typeface. Decorative diagrams, repeated badges, and promotional slogans
  were removed.
- [GOV.UK: buttons](https://design-system.service.gov.uk/components/button/): action labels use sentence case and describe the result. Navigation uses links;
  submitting a question and changing membership use buttons.
- [WCAG 2.2 target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html): the minimum criterion is 24 CSS pixels, with exceptions. This
  interface generally uses 44-pixel controls, visible focus indicators, semantic
  tables, and labels. Mobile examples wrap instead of requiring a horizontal
  carousel. Reduced-motion preferences disable the loading animation.

These changes are not a claim of complete WCAG conformance. Production login,
assistive technology, and user testing still require verification against the
configured deployment.

## Code organization

- `components/workspace.tsx` coordinates workspace selection and permissions.
  Chat, documents, members, activity, and sidebar views are separate components.
- `components/workspace/use-workspace-chat.ts` owns streaming, session state,
  cancellation, and cleanup. A workspace change remounts chat to clear its state;
  moving between sections of one workspace preserves the conversation.
- `components/answer.tsx` shares safe Markdown rendering and individual source
  disclosures. Raw HTML and remote model-generated images remain blocked.
- `lib/api-client.ts` centralizes browser request and error handling. It sends
  only same-origin gateway requests; authorization remains on the server.
- `lib/workspace.ts` holds shared API types and role labels. Database membership
  remains authoritative; visual controls do not grant permissions.

Run `npm run typecheck`, `npm test`, `npm run format:check`, and `npm run build`
from `web/`. Browser QA should cover sample selection, source disclosures,
mobile navigation, keyboard focus, unavailable services, and workspace roles.
