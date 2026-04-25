/**
 * useEventSource — wraps the native browser EventSource API.
 *
 * Opens a single persistent connection to GET /events on mount.
 * Browser handles auto-reconnect natively on network failure (RTM-02 free).
 * Mount ONLY on Feed.tsx — HTTP/1.1 browsers cap 6 connections per domain.
 *
 * The onEvent callback is kept in a ref so callers can use an inline function
 * without causing the EventSource to be torn down and rebuilt on every render.
 */
import { useEffect, useRef } from "react";
import { API_BASE } from "../api";
import type { ServerEvent } from "../types";

export function useEventSource(onEvent: (e: ServerEvent) => void): void {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    const es = new EventSource(`${API_BASE}/events`);

    es.onmessage = (m: MessageEvent) => {
      try {
        const ev = JSON.parse(m.data as string) as ServerEvent;
        handlerRef.current(ev);
      } catch {
        // Ignore malformed frames — server may send other event types
      }
    };

    es.onerror = () => {
      // No manual reconnect needed — browser reconnects automatically
      // unless readyState === EventSource.CLOSED (non-2xx response).
    };

    return () => {
      es.close();
    };
  }, []); // Empty deps: open once on mount, close on unmount
}
