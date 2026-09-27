import { useCallback, useEffect, useState } from 'react';
import { config } from '../../../config';
import { apiErrorMessage } from '../../../utils/apiError';
import type { KnowledgeDocument, KnowledgeInsights } from '../types';

const POLL_MS = 3000;
const BUSY: KnowledgeDocument['status'][] = ['queued', 'indexing'];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${config.API_BASE_URL}${path}`, { credentials: 'include', ...init });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(apiErrorMessage(body, 'Request failed'));
  return body as T;
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/**
 * Knowledge base state for the admin panel (Fase 14). Indexing runs in the
 * backend's job queue, so while any document is queued/indexing the list is
 * polled until it settles (ready / failed).
 */
export function useKnowledgeBase() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [insights, setInsights] = useState<KnowledgeInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [uploading, setUploading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setDocuments(await request<KnowledgeDocument[]>('/tenant/knowledge'));
      setInsights(await request<KnowledgeInsights>('/tenant/knowledge/insights?days=30').catch(() => null));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const busy = documents.some(d => BUSY.includes(d.status));
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [busy, refresh]);

  const run = async (action: () => Promise<string | void>) => {
    setError('');
    setNotice('');
    try {
      const message = await action();
      if (message) setNotice(message);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const upload = (file: File, sourceType: string) => run(async () => {
    const form = new FormData();
    form.append('file', file);
    form.append('source_type', sourceType);
    setUploading(true);
    try {
      const result = await request<{ message: string; warnings: string[] }>('/tenant/knowledge', {
        method: 'POST', body: form,
      });
      return [result.message, ...result.warnings].join(' ');
    } finally {
      setUploading(false);
    }
  });

  const remove = (filename: string) => run(async () => {
    await request(`/tenant/knowledge/${encodeURIComponent(filename)}`, { method: 'DELETE' });
  });

  const review = (documentId: string, approve: boolean) => run(async () => {
    await request(`/tenant/knowledge/${documentId}/review`, json({ approve }));
    return approve ? 'Correction approved — it is being indexed.' : 'Correction rejected.';
  });

  const reindex = (force = false) => run(async () => {
    const { queued } = await request<{ queued: number }>('/tenant/knowledge/reindex', json({ force }));
    return `${queued} document(s) queued for re-indexing.`;
  });

  return { documents, insights, loading, error, notice, uploading, busy, upload, remove, review, reindex, setError };
}
