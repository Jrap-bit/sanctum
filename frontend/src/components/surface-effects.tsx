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
        const lights: {element: HTMLElement; x: number; y: number}[] = [];
        let surface = latest.target.closest<HTMLElement>(surfaces);
        while (surface) {
          const rect = surface.getBoundingClientRect();
          lights.push({element: surface, x: latest.clientX - rect.left, y: latest.clientY - rect.top});
          surface = surface.parentElement?.closest<HTMLElement>(surfaces) || null;
        }
        // Batch layout reads before style writes across nested surfaces.
        for (const light of lights) {
          light.element.style.setProperty('--spotlight-x', `${light.x}px`);
          light.element.style.setProperty('--spotlight-y', `${light.y}px`);
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
