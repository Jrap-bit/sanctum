'use client';
import { useEffect, useRef } from 'react';

/** Guard reload/close and in-app links without storing private drafts. */
export function useUnsavedChanges(dirty: boolean) {
  const current = useRef(dirty); current.current = dirty;
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => {if (current.current) {event.preventDefault(); event.returnValue = '';}};
    const navigate = (event: MouseEvent) => {
      if (!current.current || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href]') : null;
      if (!link || link.download || (link.target && link.target !== '_self')) return;
      const url = new URL(link.href);
      if (url.origin !== location.origin || (url.pathname === location.pathname && url.search === location.search)) return;
      if (!window.confirm('Leave this page? Your unsaved changes will be lost.')) {event.preventDefault(); event.stopPropagation();}
    };
    window.addEventListener('beforeunload', unload);
    document.addEventListener('click', navigate, true);
    return () => {window.removeEventListener('beforeunload', unload); document.removeEventListener('click', navigate, true);};
  }, []);
}
