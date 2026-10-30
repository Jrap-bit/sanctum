'use client';

import { useEffect } from 'react';

// One delegated listener keeps lighting consistent, including asynchronously
// loaded content, without rendering React state on pointer movement.
const surfaces = '.workflow-tool, .workspace-header, .panel, .auth-card, .button, .preset-card, .dropzone, .record-summary';

export function SurfaceEffects() {
  useEffect(() => {
    const preference = window.matchMedia('(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)');
    let frame = 0;
    let latest: PointerEvent | null = null;

    const track = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return;
      latest = event;
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        if (!latest || !(latest.target instanceof Element)) return;
        let surface = latest.target.closest<HTMLElement>(surfaces);
        while (surface) {
          const rect = surface.getBoundingClientRect();
          surface.style.setProperty('--spotlight-x', `${latest.clientX - rect.left}px`);
          surface.style.setProperty('--spotlight-y', `${latest.clientY - rect.top}px`);
          surface = surface.parentElement?.closest<HTMLElement>(surfaces) || null;
        }
        latest = null;
      });
    };

    const syncPreference = () => {
      document.removeEventListener('pointermove', track);
      window.cancelAnimationFrame(frame);
      frame = 0;
      latest = null;
      if (preference.matches) document.addEventListener('pointermove', track, { passive: true });
    };

    syncPreference();
    preference.addEventListener('change', syncPreference);
    return () => {
      document.removeEventListener('pointermove', track);
      preference.removeEventListener('change', syncPreference);
      window.cancelAnimationFrame(frame);
    };
  }, []);

  return null;
}
