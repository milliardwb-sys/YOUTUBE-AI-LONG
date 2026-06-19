# Render template foundation

Date: 2026-06-19

## What changed

- Added a `SlideTemplate` layer inside `VisualService`.
- Each generated slide now gets a template id, human name, layout role, palette, title/body wrapping rules, and footer label.
- Generated slide folders now include `slides/render_templates.json`.
- Single-scene regeneration writes `slides/scene_###.template.json` for the regenerated slide.

## Current templates

- `source_review_v1`: source/screenshot review composition.
- `decision_matrix_v1`: comparison/data-board composition.
- `workflow_map_v1`: process diagram composition.
- `editorial_brief_v1`: expert/trend editorial composition.
- `studio_focus_v1`: general-purpose studio slide composition.

## Why this matters

The project still renders PNG slides and combines them with ffmpeg, but the visual pipeline now has a stable template contract. This gives the next production renderer a clean manifest to consume, whether it becomes Remotion, After Effects automation, or a hosted render service.

## Current limits

- Templates are still rendered by PIL, not motion graphics.
- There is no per-customer brand kit upload yet.
- The template manifest is local project metadata; it is not yet exposed as a dedicated API resource.
