'use client';

import { useEffect, useRef, useState } from 'react';

export type JobEvent = {
  jobId: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress?: number | null;
  stage?: string | null;
  message?: string | null;
  delta?: string | null;
};

export function useJobStream(
  jobId: string | null,
  onFinished?: (event: JobEvent) => void
): { event: JobEvent | null; text: string; live: boolean } {
  const [event, setEvent] = useState<JobEvent | null>(null);
  const [text, setText] = useState<string>('');
  const [live, setLive] = useState<boolean>(false);
  const onFinishedRef = useRef(onFinished);

  useEffect(() => {
    onFinishedRef.current = onFinished;
  });

  useEffect(() => {
    setEvent(null);
    setText('');
    setLive(false);

    if (!jobId || process.env.NEXT_PUBLIC_DEMO_MODE === '1' || typeof window === 'undefined') {
      return;
    }

    let disposed = false;
    let ws: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryCount = 0;
    let terminalReceived = false;
    let finishedCalled = false;

    const connect = () => {
      if (disposed) return;
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${protocol}//${window.location.host}/api/v1/ws/jobs/${encodeURIComponent(jobId)}`;

      try {
        const socket = new WebSocket(url);
        ws = socket;

        socket.onopen = () => {
          if (disposed) {
            socket.close();
            return;
          }
          setLive(true);
        };

        socket.onmessage = (messageEvent) => {
          if (disposed) return;
          try {
            const data: JobEvent = JSON.parse(messageEvent.data);
            setEvent(data);
            if (typeof data.delta === 'string' && data.delta) {
              setText((prev) => prev + data.delta);
            }
            if (['completed', 'failed', 'cancelled'].includes(data.state)) {
              terminalReceived = true;
              if (!finishedCalled) {
                finishedCalled = true;
                onFinishedRef.current?.(data);
              }
            }
          } catch {
            // Ignore malformed messages
          }
        };

        socket.onerror = () => {
          if (disposed) return;
          setLive(false);
        };

        socket.onclose = (closeEvent) => {
          if (disposed) return;
          setLive(false);
          if (terminalReceived) return;
          if ([4401, 4403, 4404].includes(closeEvent.code)) return;
          if (retryCount < 3) {
            const delays = [1000, 2000, 4000];
            const delay = delays[retryCount++];
            retryTimer = setTimeout(() => {
              if (!disposed) {
                connect();
              }
            }, delay);
          }
        };
      } catch {
        setLive(false);
      }
    };

    connect();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.close();
      }
      setLive(false);
    };
  }, [jobId]);

  return { event, text, live };
}
