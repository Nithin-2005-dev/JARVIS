# Frontend architecture

The `frontend/` application uses Next.js 14, React 18, TypeScript, Tailwind CSS, Lucide icons, and a small custom SVG topology view. The SVG choice keeps node positions deterministic and avoids introducing graph business logic or an additional interaction framework. Recharts is available for future data-driven trend charts; this milestone only renders the severity distribution from persisted incident counts and omits empty history.

Routes: `/` overview; `/incidents` explorer; `/incidents/[incidentId]` investigation; `/services` and `/services/[serviceId]`; `/intelligence`; `/recommendations`.

`src/lib/api.ts` centralizes base URL, JSON decoding, and error messages. Reusable controls live under `src/components`. API failures render visible errors; no fixture fallback is present. Responsive navigation collapses to an icon rail on medium viewports and a compact header on mobile. The incident workspace keeps missing optional sections local to that section.
