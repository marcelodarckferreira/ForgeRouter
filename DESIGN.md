---
version: alpha
name: "ForgeRouter"
description: "Dense operational console for routing and supervising a fleet of AI agents and LLM providers."
colors:
  background: "#08090b"
  surface: "#0c0c0f"
  raised: "#101013"
  border: "#27272a"
  text: "#f4f4f5"
  muted: "#a1a1aa"
  primary: "#8b5cf6"
  data: "#2dd4bf"
  success: "#86efac"
  warning: "#fdba74"
  danger: "#ef4444"
typography:
  sans:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
rounded:
  sm: "0.5rem"
  DEFAULT: "0.625rem"
  card: "1.125rem"
  panel: "1.375rem"
  pill: "9999px"
spacing:
  control-x: "0.75rem"
  card: "1.125rem"
  panel-row-x: "1.375rem"
components:
  button:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
  focus-ring:
    backgroundColor: "{colors.primary}"
  card:
    backgroundColor: "{colors.raised}"
  panel:
    backgroundColor: "{colors.surface}"
  agent-identity:
    textColor: "{colors.text}"
  select:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
  divider:
    backgroundColor: "{colors.border}"
  data-chip:
    textColor: "{colors.data}"
  status-success:
    textColor: "{colors.success}"
  status-warning:
    textColor: "{colors.warning}"
  status-danger:
    textColor: "{colors.danger}"
  secondary-text:
    textColor: "{colors.muted}"
---

# ForgeRouter Design System

## Overview

### Creative North Star

ForgeRouter resembles a focused mission-control console: dark instrument surfaces, restrained violet controls and teal data traces. Density communicates operational capability without becoming a generic analytics template.

### Product context and register

- **Audience and primary job:** Operators register agents, control their eligible LLMs and diagnose routing health.
- **Target market and locale:** Internal/global technical operation; the current maintained interface uses English product copy.
- **Usage scene:** Repeated desktop use with responsive access for narrow screens and high information density.
- **Register:** Product/admin.
- **Memorable signature:** Colored capability and routing chips behave like a live switchboard.
- **Restraint:** Forms, destructive actions and identity controls prioritize familiarity and clarity.
- **Anti-references:** No decorative AI gradients, oversized marketing typography or glassmorphism that obscures dense data.
- **Token ownership/runtime mapping:** `frontend/src/style.css` remains the canonical runtime token source. This file mirrors accepted values and intent; feature work must consume those variables rather than introduce a parallel token layer.

## Colors

Neutral surfaces use `background`, `surface` and `raised`; violet is the primary interaction/focus accent and teal is reserved for routing/data. Success, warning and danger remain semantic. Light theme remaps neutral CSS variables without changing these roles.

## Typography

Inter/system sans carries interface copy; JetBrains Mono/system mono carries identifiers, keys and model names. Compact numeric data uses stable weight and avoids decorative casing.

## Layout

The sticky sidebar and naturally scrolling content area own page layout. Panels and card grids reflow below 900px. Images reserve explicit square geometry; table/list overflow stays inside its existing surface.

## Elevation & Depth

Hierarchy comes from tonal layers and one-pixel borders. Static cards use a restrained raised-to-surface gradient; menus may use a single functional shadow above content.

## Shapes

Controls use 8–10px radii, cards 18px, panels 22px and compact tags full pills. Circular agent images are the only identity-specific shape.

## Components

### Foundational visual states

Interactive controls define visible hover, focus, pressed, disabled and busy states. Images fall back to an initial while preserving geometry. Loading must not resize controls.

### Buttons and actions

One solid primary action leads each decision area. Secondary actions use raised neutral surfaces; destructive actions remain separated and receive danger treatment.

### Navigation and data display

Agent identity is always presented as profile image plus name when an agent is represented visually. Cost and capability chips use real buttons when they change model association, with pressed state conveyed by text decoration and tone as well as color.

### Forms and overlays

Fields use the existing dark input surface and violet focus border. Agent image selection offers both a visible picker and drag-and-drop, with client resizing and server validation. Authored agent selectors show the same image-plus-name identity in trigger and options.

### Iconography

Lucide outline icons use compact 12–18px sizing. Icon-only actions require accessible names; core actions retain text labels.

### Motion

Motion is limited to 100–200ms state feedback. Reduced-motion users receive immediate state changes without transforms.

### Content and data visualization

Copy is direct and operational. Numeric values remain scan-friendly; chart color never replaces the agent image and name in legends.

## Do's and Don'ts

- **Do:** Reuse shared identity, picker and selector components everywhere an agent appears.
- **Do:** Keep group toggles aligned with the same association persistence used by individual models.
- **Don't:** Render a generic bot icon or bare agent name as a substitute for known agent identity.
- **Don't:** Introduce raw color values when an existing semantic variable or established role applies.
