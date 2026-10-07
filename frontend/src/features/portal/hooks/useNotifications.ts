import { useCallback, useEffect, useRef, useState } from 'react';
import { config } from '../../../config';

// GET /api/me/notifications (src/api/routers/notifications.py, Fase 16).
export type AppNotification = {
  id: string;
  kind: 'ticket_opened' | 'resolved' | 'escalated' | 'pending_human' | 'fix_proposed' | 'issue_opened';
  title: string;
  body: string;
  // Only present for admins: links into the engineering repo.
  link: string | null;
  ticket_external_id: string | null;
  read: boolean;
  created_at: string | null;
};

const POLL_INTERVAL_MS = 15000;

/**
 * The signed-in user's notifications, polled (and refreshed when the tab
 * regains focus). `onNew` receives each notification the first time this
 * page sees it — the chat uses it to post ticket updates into the
 * conversation they came from.
 */
export function useNotifications(onNew?: (n: AppNotification) => void) {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const seen = useRef<Set<string> | null>(null);
  const onNewRef = useRef(onNew);
  useEffect(() => {
    onNewRef.current = onNew;
  }, [onNew]);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${config.API_BASE_URL}/me/notifications`, { credentials: 'include' });
      if (!res.ok) return;
      const data: { unread: number; items: AppNotification[] } = await res.json();
      // The first load only records what already existed: nothing is "new" yet.
      if (seen.current === null) {
        seen.current = new Set(data.items.map(n => n.id));
      } else {
        for (const n of [...data.items].reverse()) {
          if (!seen.current.has(n.id)) {
            seen.current.add(n.id);
            onNewRef.current?.(n);
          }
        }
      }
      setItems(data.items);
      setUnread(data.unread);
    } catch {
      // Offline for a moment — the next poll catches up.
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    window.addEventListener('focus', refresh);
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', refresh);
    };
  }, [refresh]);

  const markAllRead = useCallback(async () => {
    await fetch(`${config.API_BASE_URL}/me/notifications/read-all`, { method: 'POST', credentials: 'include' });
    await refresh();
  }, [refresh]);

  return { items, unread, refresh, markAllRead };
}
