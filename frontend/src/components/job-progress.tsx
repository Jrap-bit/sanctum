'use client';

import type { JobEvent } from '@/lib/ws';

export function JobProgress({
  label,
  event,
  fallback,
}: {
  label: string;
  event: JobEvent | null;
  fallback?: number;
}) {
  const isIndeterminate = Boolean(event && event.progress === null);
  const rawProgress = isIndeterminate ? null : (event?.progress ?? fallback ?? 0);
  const clampedProgress = rawProgress !== null ? Math.max(0, Math.min(100, Math.round(rawProgress))) : null;
  const stageOrState = event?.stage || event?.state;
  const text = isIndeterminate
    ? (stageOrState || label)
    : (stageOrState ? `${stageOrState} · ${clampedProgress}%` : `${clampedProgress}%`);

  return (
    <div className="job-progress" role="status">
      <div
        className={`progress${isIndeterminate ? ' indeterminate' : ''}`}
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        {...(!isIndeterminate && clampedProgress !== null ? { 'aria-valuenow': clampedProgress } : {})}
        aria-valuetext={text}
      >
        <span style={!isIndeterminate && clampedProgress !== null ? { transform: `scaleX(${clampedProgress / 100})` } : undefined} />
      </div>
      <small>{text}</small>
    </div>
  );
}
