# Visual Design Guide

This guide governs visual interfaces created for the Codex Harness Observatory. Specific teaching or task requirements may override it.

## Priorities

1. Make the information understandable.
2. Show a high amount of useful information in the available space.
3. Remove anything that does not support understanding or action.

Minimalism means fewer elements, words, containers, and visual effects. It does not mean large empty areas.

## Theme

- Use a light theme only. Do not add dark mode or a theme switch.
- Use white or lightly tinted neutral surfaces with dark text.
- Maintain clear text and control contrast. Do not rely on faint gray text to create hierarchy.
- Use color sparingly for selection, relationships, warnings, errors, and other meanings that benefit from rapid recognition.
- Never make color the only carrier of meaning.
- Give each event type a stable semantic color. Reuse that color for the same type in later widgets, always paired with a text label or other non-color encoding.

## Information density

- Prefer compact layouts with low padding and short gaps.
- Start with a 4 px spacing unit. Typical gaps and padding should be 4, 8, or 12 px. Use 16 px only when separating major regions.
- Keep repeated rows compact enough that several are visible at once.
- Use alignment, typography, and thin dividers before adding containers.
- Prefer tables and aligned lists for repeated structured data. Reserve cards for distinct objects that need independent selection or comparison.
- Avoid cards nested inside cards, oversized headers, large empty states, and decorative whitespace.
- Keep important controls and context visible without forcing unnecessary scrolling.

Density must not obscure relationships. Add space only when it separates concepts, improves scanning, or prevents interaction errors.

## Content and hierarchy

- Use one clear title for a view or region.
- Use direct labels. Prefer `Tool call` to `Tool execution activity details`.
- Do not add eyebrow text, subtitles, taglines, introductory prose, or helper text unless the interface would otherwise be ambiguous.
- Do not restate a heading in the sentence below it.
- Avoid word padding such as `currently`, `successfully`, `please note`, or `in order to` when it adds no meaning.
- Use sentence case. Avoid decorative all-caps labels and excessive letter spacing.
- Use sans-serif text for interface language. Use monospace only for code, commands, paths, identifiers, and wire data.
- De-emphasize long identifiers in overview views. Show their complete values where they can be inspected or copied.
- Put raw evidence behind a clear disclosure when a semantic summary can explain it first.

## Duplication

Do not show the same information more than once unless the repetition has a specific support reason. Acceptable reasons include:

- preserving orientation while another region scrolls;
- supporting a direct side-by-side comparison;
- keeping the affected object visible beside an action;
- providing an accessible text equivalent for a non-text encoding.

Convenience, visual balance, and filling empty space are not sufficient reasons. If the support reason cannot be named, remove the duplicate.

## Status and indicators

Show a status only when it is current, can vary, and changes how the user should interpret or act on the interface.

- Use precise states such as `Running`, `Waiting for approval`, `Failed`, and `Complete`.
- Distinguish status from type. `Tool`, `Context`, and `Model response` are classifications, not statuses.
- Do not show a permanent `Live`, `Ready`, `Connected`, or `Success` badge when that state is already implied by the functioning view.
- Do not display both a status badge and adjacent prose that says the same thing.
- Pair warnings and errors with the relevant object and, when known, the required action.
- Use motion only for an active process whose progress would otherwise be unclear.

## Controls and interaction

- Give controls short labels that describe their action.
- Keep frequently used filters and navigation visible and compact.
- Hide advanced or forensic detail through disclosure, not by removing access to it.
- Make the selected row, active filter, and keyboard focus unambiguous.
- Prefer inline expansion or a stable detail pane when it preserves context.
- Empty states should name what is absent and give an action only when one is available.
- Avoid confirmation dialogs for reversible actions. Require confirmation when an action is destructive or difficult to reverse.

## Observatory-specific application

- Treat the event timeline as a dense list, not a collection of large cards.
- Lead each event with the human-readable event or tool name. Do not make an opaque identifier the primary label.
- Keep sequence, time, type, phase, and meaningful status aligned so events can be compared vertically.
- Treat displayed event categories as a changeable teaching layer over the recorded trace vocabulary. Preserve the original Core category in the raw event evidence.
- Keep protocol and semantic layers visually distinct: App Server uses slate blue, tools use blue, MCP uses teal, and decisions use amber, always alongside their text category.
- Show thread, turn, step, call, and response identifiers on demand unless an identifier is needed to follow a relationship.
- Explain the semantic meaning of an event once. Keep the complete event envelope and payload artifacts available as evidence.
- Do not repeat envelope fields in the semantic view unless they support interpretation, correlation, or comparison.
- Make model messages, tool requests, tool results, patches, approval decisions, and agent coordination visually distinguishable without giving each one excessive decoration.

## Review checklist

Before accepting an interface change, check:

- Can any element or sentence be removed without losing meaning?
- Is any fact shown twice without a named support reason?
- Does each status indicator represent a variable, consequential state?
- Could padding or gaps be reduced without harming comprehension or interaction?
- Are repeated data aligned for comparison?
- Are raw identifiers subordinate to human-readable names?
- Is the interface fully usable in its light theme without a dark-mode dependency?
- Are color, focus, and status meanings still understandable without color alone?
