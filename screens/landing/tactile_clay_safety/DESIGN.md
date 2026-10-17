---
name: Tactile Clay Safety
colors:
  surface: '#fcf8ff'
  surface-dim: '#dbd7ef'
  surface-bright: '#fcf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f6f2ff'
  surface-container: '#efebff'
  surface-container-high: '#e9e5fe'
  surface-container-highest: '#e3e0f8'
  on-surface: '#1b1a2b'
  on-surface-variant: '#484551'
  inverse-surface: '#302e41'
  inverse-on-surface: '#f3eeff'
  outline: '#797582'
  outline-variant: '#c9c4d2'
  surface-tint: '#6152a4'
  primary: '#5e4fa2'
  on-primary: '#ffffff'
  primary-container: '#7768bd'
  on-primary-container: '#fffbff'
  inverse-primary: '#cabeff'
  secondary: '#146c46'
  on-secondary: '#ffffff'
  secondary-container: '#9ff1c1'
  on-secondary-container: '#1a704a'
  tertiary: '#6d584c'
  on-tertiary: '#ffffff'
  tertiary-container: '#877063'
  on-tertiary-container: '#fffbff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e6deff'
  primary-fixed-dim: '#cabeff'
  on-primary-fixed: '#1c035e'
  on-primary-fixed-variant: '#49398b'
  secondary-fixed: '#a2f4c4'
  secondary-fixed-dim: '#86d7a9'
  on-secondary-fixed: '#002112'
  on-secondary-fixed-variant: '#005232'
  tertiary-fixed: '#faddce'
  tertiary-fixed-dim: '#ddc1b2'
  on-tertiary-fixed: '#27180f'
  on-tertiary-fixed-variant: '#564338'
  background: '#fcf8ff'
  on-background: '#1b1a2b'
  surface-variant: '#e3e0f8'
typography:
  display-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  title-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 26px
  title-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.03em
  telemetry:
    fontFamily: Plus Jakarta Sans
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: 0.02em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-tablet: 1.5rem
  gutter-desktop: 2rem
  margin: 1rem
  margin-tablet: 2rem
  margin-desktop: 3rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
---

## Brand & Style

This design system is engineered for personal protection, family location coordination, and calm-state emergency preparedness. Rather than leaning into the alarmist, stark, dark-ops visual tropes common to tracking and security applications, this interface adopts a gentle, reassuring, and comforting demeanor. The experience must feel protective rather than panoptic, calming anxious parents and empowering vulnerable individuals through physical warmth and accessibility.

The core design philosophy merges **Tactile Claymorphism** with **Material 3 architectural foundations**. UI elements are treated as soft, sculpted clay objects resting upon warm ivory planes. Surfaces invite physical touch through voluminous multi-tier ambient shadows, pillowy raised contours, smooth inset wells, and tactile toggles that physically yield on interaction. Emergency SOS mechanics remain strictly distinct: insulated by deliberate spatial hierarchies and reserved vibrant hues to prevent sensory fatigue or accidental triggering.

## Colors

The palette establishes an emotional baseline of warmth, trust, and gentle clarity.

### Color Roles
- **Canvas Background (`#F5F2EA`)**: A warm ivory foundation that eliminates harsh OLED glare and creates a paper-like, domestic warmth.
- **Surface / Clay Elevated (`#FAF8F4`)**: A high-luminance, pillowy ceramic white used for cards, floating controls, and navigation docks.
- **Primary Lavender (`#8273C8`) & Soft Lavender (`#DCD5F5`)**: The core brand accent and interactive anchor. Used for active navigation, confirmed safe statuses, tactile radio buttons, and focused states.
- **Pale Sky Blue (`#D8E9F5`)**: Auxiliary status and family zone indicator. Represents informational presence, network heartbeats, and gentle geofence bubbles.
- **Mint Sanctuary (`#D4EBDD`) & Forest Mint (`#33845C`)**: Status indicators representing "Safe Home", full battery, intact communication paths, and peaceful check-ins.
- **Soft Peach (`#F5D8C9`) & Clay Rose (`#E7B9B8`)**: Friendly human-centric identifiers for family member avatars, status tags, and customizable personal safe-space boundaries.
- **Primary Text (`#29283A`) & Secondary Text (`#777588`)**: A muted slate-indigo scale ensuring crisp WCAG AAA legibility without the harshness of pure black.
- **Caution / Warning (`#B87A2C`)**: Used for low battery alerts, degraded GPS signals, and non-immediate geofence exits.
- **Critical Emergency / SOS (`#C83F4D`)**: Strictly quarantined for panic toggles, silent dispatch triggers, and acute distress states. It must never appear for decorative purposes or minor warnings.

## Typography

The type system is powered by **Plus Jakarta Sans**, chosen for its friendly, wide apertures, humanist geometry, and rounded stroke terminals. This balances modern clarity with an unpretentious, approachable cadence.

### Numeric & Telemetry Rules
All real-time coordinates, battery percentages, ETA calculations, and chronological safety logs must enforce OpenType tabular figures (`font-variant-numeric: tabular-nums;` or `font-feature-settings: "tnum" 1`). This eliminates jitter during continuous geofence updates and speed telemetry readouts.

### Hierarchy & Legibility
- **Display and Headlines**: Kept in weights 600 and 700 with slight negative tracking to preserve cohesion on large pillowed cards.
- **Labels**: Set slightly tighter in scale with upper-mid weights (600) to reinforce button affordances and chip tap-targets without feeling institutional.
- **Body Text**: Rendered strictly with `#29283A` at minimum 14px for general descriptions and 16px for safety check-in flows to maximize readability during motion or distress.

## Layout & Spacing

Layouts follow a fluid, device-responsive structure built on an 8px base rhythm (with 4px micro-steps for compact badges).

### Grid Structure
- **Mobile (<600dp)**: 4-column layout with 16px (`1rem`) outer margins and 16px gutters. Clay cards stretch full-width or pair into 2-column tactile tiles.
- **Tablet (600dp - 1023dp)**: 8-column layout with 32px (`2rem`) margins and 24px (`1.5rem`) gutters. Used for split-view map visualizers and safety family registries.
- **Desktop / Foldable expanded (1024dp+)**: 12-column layout centered at a maximum canvas width of 1280px with 48px outer margins.

### Spatial Breathing Room
Tactile clay elements require increased white space compared to flat or material-pure layouts. Shadows and soft bevels demand padding isolation: elements should avoid edge-touching, using at least `space-md` (16px) between adjacent interactive clay surfaces to avoid overlapping shadow cones.

## Elevation & Depth

Depth in this system is created using sculpted clay tactility, pairing exterior diffuse ambient drop shadows with inner directional specular highlights.

### The Clay Formula
Every raised surface is composed of three layered light mechanics:
1. **Inner Highlight**: An inset shadow at `top: 1.5px, left: 1.5px` with a 2px to 3px blur using semi-transparent pure white (`rgba(255, 255, 255, 0.85)`). This creates the rounded, soft-rolled ceramic rim.
2. **Inner Rim Shade**: A soft, secondary bottom-right inset shadow (`rgba(200, 190, 175, 0.15)`) accentuating the pillowy underside.
3. **Ambient Drop Shadow**: Soft, multi-layered diffuse shadows using a warm chromatic tint derived from the background (`rgba(72, 60, 102, 0.08)`) instead of flat neutral black.

### Elevation Tiers
- **Tier 0 (Debossed Well)**: Inset controls, search trays, and toggle tracks.
  - Drop shadow: None.
  - Inset shadow: `inset 2px 3px 6px rgba(41, 40, 58, 0.08), inset -2px -2px 4px rgba(255, 255, 255, 0.9)`.
- **Tier 1 (Resting Clay Tile / Card)**: Primary cards and family member status pills.
  - Box shadow: `0 8px 20px -4px rgba(65, 50, 92, 0.07), 0 3px 8px -2px rgba(65, 50, 92, 0.04)`.
  - Inset light: `inset 1.5px 1.5px 2px rgba(255, 255, 255, 0.9)`.
- **Tier 2 (Floating Action / Active Switch / Bottom Sheet)**: Interactive touchpoints, quick-dial chips, modal controls.
  - Box shadow: `0 14px 28px -6px rgba(65, 50, 92, 0.12), 0 6px 12px -3px rgba(65, 50, 92, 0.06)`.
  - Inset light: `inset 2px 2px 3px rgba(255, 255, 255, 0.95)`.
- **Tier 3 (Emergency Beacon / Active Modal)**: Raised critical focus.
  - Box shadow: `0 20px 40px -8px rgba(200, 63, 77, 0.22), 0 8px 16px -4px rgba(65, 50, 92, 0.08)`.
  - Inset light: `inset 2px 2px 3px rgba(255, 255, 255, 0.6)`.

## Shapes

The design language uses extra-rounded geometry to convey physical safety, friendliness, and soft responsiveness.

### Corner Radius Scales
- **Standard Cards & Surfaces**: Standardized strictly between `22px` and `28px` corner radius. This curved silhouette gives cards their signature pillowy form factor.
- **Buttons, Floating Pills & Chips**: Fully rounded pill shapes (`9999px`) to invite natural fingertip compression.
- **Debossed Input Wells & Inset Tracks**: Fixed at `18px` to `20px` to mirror the inner curvature of containing cards.
- **Avatar Badges & Critical Status Tokens**: Concentric circular housings (`50%`) with elevated clay ring borders (`3px solid #FAF8F4`).

## Components

### Buttons
- **Primary Clay Button**: Pill-shaped (`9999px`), background `#8273C8`, label white (`#FFFFFF`) with `title-md`. Elevated with Tier 2 lavender-tinted drop shadows and an upper-left interior white glare line. On tap/active state, the button physically compresses downward by 1.5px, shedding its drop shadow and shifting to an inset well profile.
- **Secondary / Soft Button**: Background `#DCD5F5` with text `#29283A`. Light clay elevation (Tier 1) for neutral operations like "Add Stop" or "Share Battery".
- **Emergency SOS Activator**: A dedicated, oversized tactile clay disc (minimum 72x72dp) colored in Critical Emergency Red (`#C83F4D`) with high-depth drop shadows (`rgba(200, 63, 77, 0.35)`). Requires a sustained hold with radial clay fill animation to avoid erratic triggering.

### Cards & Tiles
- **Family Status Card**: Pillowed `#FAF8F4` container with a radius of `26px`. Features generous internal padding (`space-lg`), housing member avatar, real-time battery status in telemetry typography, and geofence indicators styled as soft pastel mint or sky blue status chips.
- **Map Floating Clay Pod**: Compact, high-elevation surfaces displaying speed, address, or breadcrumb history, floating detached above map viewports.

### Inset Wells & Input Fields
- Text inputs and search containers abandon standard lines or crisp borders. They are built as debossed clay wells (`#F0EDE4`) carved into `#FAF8F4` cards with interior inset shadow depth.
- Placeholders use `#777588`, transitioning to `#29283A` on input, with an active focus accentuating a soft 2px `#8273C8` outer halo without harsh outlines.

### Chips & Filters
- Compact pill elements (`32px` height) with `16px` horizontal padding.
- Inactive: `#F5F2EA` with subtle Tier 1 elevation.
- Active: Filled with Soft Lavender (`#DCD5F5`) or Calm Mint (`#D4EBDD`), accompanied by a soft, pressed drop shadow.

### Checkboxes, Radios & Switches
- **Switches**: Composed of a debossed well track (`48x28dp`) in `#E8E4DA` and a spherical clay toggle knob (`22x22dp`) in `#FAF8F4` with Tier 2 ambient drop shadows. Active switch slides rightward, tinting track to `#8273C8`.
- **Checkboxes & Radios**: Extra-rounded square or circular clay discs that sink physically into the canvas when selected, showing a Forest Mint (`#33845C`) or Lavender check icon.

### Safe Zone Geofence Visualizers
- On-map boundaries render with clay-inspired volumetric strokes: a thick `4px` translucent band (`rgba(130, 115, 200, 0.4)`) backed by a soft, diffused surface tint (`rgba(216, 233, 245, 0.25)`).