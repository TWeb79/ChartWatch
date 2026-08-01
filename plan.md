# ChartWatch — Remaining TODOs

## Critical Bugs

- None remaining

## Medium Priority Bugs

- None remaining

## Improvements

- None remaining

## Completed Tasks

### UI Component System Unification (Visual Fixes)

1. **Button hierarchy** — `btn-primary` (filled accent) is now the only filled action button. `btn-danger` changed to outlined style (transparent bg, red border/text). Added `btn-ghost` class for secondary actions like Refresh. Start Cycle = primary, Stop = outlined danger, Refresh = ghost.

2. **Unified badge system** — Replaced `.status-pill`, `.prereq-pill`, `.health-pill` with single `.badge` class. All status indicators now share the same pill shape, padding, and dot prefix via `::before` pseudo-element. Added `.badge.checking` variant with spinner animation for pending states. Removed redundant `.status-dot` element from header.

3. **Form control standardization** — Dropdown, number input, and checkbox toggle now share consistent height (40px), border (1px solid var(--border)), border-radius (8px), and padding (8px 12px). Toggle label gets border and padding to match sibling inputs.

4. **Tightened empty states** — `.ollama-empty` class reduces padding and removes min-height for the "No response yet" state, keeping density consistent with the Scheduler card above it.

5. **Red rationing** — With Stop button now outlined, red is reserved purely for connection failure states (disconnected badges), restoring its urgency signal.
