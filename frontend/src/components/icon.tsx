import type { SVGProps } from 'react';

export type IconName = 'home'|'patient'|'users'|'handover'|'key'|'rules'|'audit'|'activity'|'logout'|'menu'|'close'|'arrow'|'plus'|'notes'|'document'|'sparkle'|'indicator'|'report'|'search'|'check'|'clock'|'alert'|'upload'|'shield'|'chevron'|'calendar';
const paths: Record<IconName, React.ReactNode> = {
  home:<><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V10Z"/><path d="M9 21v-7h6v7"/></>,
  patient:<><circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></>,
  users:<><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2H3ZM17 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 2 4v2h-3"/></>,
  handover:<><path d="M4 7h15m0 0-4-4m4 4-4 4M20 17H5m0 0 4-4m-4 4 4 4"/></>,
  key:<><circle cx="8" cy="14" r="4"/><path d="m11 11 9-9 2 2-2 2 2 2-3 3-2-2-3 3"/></>,
  rules:<><path d="M5 4h14v16H5zM9 9h6M9 13h6M9 17h3"/></>,
  audit:<><path d="M5 3h11l3 3v15H5zM16 3v4h3M9 11h6M9 15h6M9 19h4"/></>,
  activity:<><path d="M3 12h4l3-7 4 14 3-7h4"/></>,
  logout:<><path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M14 8l4 4-4 4m-6-4h10"/></>,
  menu:<><path d="M4 6h16M4 12h16M4 18h16"/></>,
  close:<><path d="M5 5l14 14M19 5 5 19"/></>,
  arrow:<><path d="M4 12h16m-6-6 6 6-6 6"/></>,
  plus:<><path d="M12 5v14M5 12h14"/></>,
  notes:<><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
  document:<><path d="M6 2h8l5 5v15H6zM14 2v6h5M9 13h7M9 17h5"/></>,
  sparkle:<><path d="m12 2 2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4L12 2Z"/></>,
  indicator:<><path d="M4 19V7m5 12V4m5 15v-8m5 8V9M2 21h20"/></>,
  report:<><path d="M5 3h14v18H5zM9 8h6M9 12h6m-6 4h3"/></>,
  search:<><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  check:<><path d="m4 12 5 5L20 6"/></>,
  clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  alert:<><path d="m12 3 10 18H2L12 3Zm0 6v5m0 3v.2"/></>,
  upload:<><path d="m12 16 0-12m-5 5 5-5 5 5M4 16v4h16v-4"/></>,
  shield:<><path d="M12 2 4 5v6c0 5 3 8 8 11 5-3 8-6 8-11V5l-8-3Zm-4 9 3 3 5-5"/></>,
  chevron:<><path d="m9 5 7 7-7 7"/></>,
  calendar:<><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18"/></>,
};
export function Icon({name,size=18,...props}:{name:IconName;size?:number}&SVGProps<SVGSVGElement>) { return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>; }
