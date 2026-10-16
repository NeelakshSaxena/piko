/** A small set of line icons (24x24). Decorative: always hidden from assistive technology. */
const PATHS = {
  overview: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  map: 'M3 11l18-8-8 18-2-8z',
  people: 'M9 11a3 3 0 100-6 3 3 0 000 6zM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 6.5a2.5 2.5 0 010 5M18 14.5c2 .6 3 2.4 3 5.5',
  sos: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM12 8v5M12 16h.01',
  message: 'M4 5h16v11H9l-5 4z',
  activity: 'M3 12h4l3-7 4 14 3-7h4',
  device: 'M8 3h8a1 1 0 011 1v16a1 1 0 01-1 1H8a1 1 0 01-1-1V4a1 1 0 011-1zM11 18h2',
  bell: 'M6 16v-5a6 6 0 1112 0v5l2 2H4zM10 20a2 2 0 004 0',
  settings: 'M4 7h10M18 7h2M4 17h2M10 17h10M14 5v4M6 15v4',
  search: 'M11 4a7 7 0 100 14 7 7 0 000-14zM21 21l-5-5',
  battery: 'M3 8h15v8H3zM20 11v2M7 11v2',
  signal: 'M4 18v-2M9 18v-5M14 18V9M19 18V5',
  clock: 'M12 4a8 8 0 100 16 8 8 0 000-16zM12 8v4l3 2',
  download: 'M12 4v10M8 10l4 4 4-4M5 19h14',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4',
  pin: 'M12 21s7-6.2 7-11a7 7 0 10-14 0c0 4.8 7 11 7 11zM12 12a2 2 0 100-4 2 2 0 000 4z',
  refresh: 'M20 12a8 8 0 10-2.5 5.8M20 5v5h-5',
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
