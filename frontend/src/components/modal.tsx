'use client';

import { useEffect, useRef, type ReactNode } from 'react';

/** Native top-layer focus containment, inert background, and focus restoration. */
export function Modal({ open, onClose, labelledBy, describedBy, busy = false, children }: {
  open: boolean; onClose: () => void; labelledBy: string; describedBy?: string;
  busy?: boolean; children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!open || !ref.current) return;
    const dialog = ref.current;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    return () => {
      dialog.close();
      const target = trigger?.checkVisibility() ? trigger : trigger?.closest('details')?.querySelector('summary');
      if (target instanceof HTMLElement && target.isConnected) target.focus();
    };
  }, [open]);
  return <dialog ref={ref} className="dialog modal" aria-labelledby={labelledBy} aria-describedby={describedBy}
    aria-modal="true" aria-busy={busy} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}
    onClick={event => {
      if (busy || event.target !== event.currentTarget) return;
      const r = event.currentTarget.getBoundingClientRect();
      if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) onClose();
    }}>{children}</dialog>;
}
