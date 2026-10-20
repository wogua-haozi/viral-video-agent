export interface RevisionAttempt { query: string; idempotency_key: string; }

export class RevisionStorageError extends Error {
  constructor() { super('无法读取或保存未决修订，请保留当前标签页，检查浏览器站点存储后再试。'); }
}

const storageKey = (userId: string, sourceJobId: string) => `viral-video:revision-attempts:${JSON.stringify([userId, sourceJobId])}`;

export function readRevisionAttempts(userId: string, sourceJobId: string): RevisionAttempt[] {
  try {
    const stored = sessionStorage.getItem(storageKey(userId, sourceJobId));
    if (!stored) return [];
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed) || !parsed.every((item) => typeof item?.query === 'string' && typeof item?.idempotency_key === 'string' && item.idempotency_key)) throw new RevisionStorageError();
    return parsed;
  } catch {
    throw new RevisionStorageError();
  }
}

// Keep every unresolved payload: changing A to B and back must still replay A.
export function saveRevisionAttempt(userId: string, sourceJobId: string, query: string): RevisionAttempt {
  const attempts = readRevisionAttempts(userId, sourceJobId);
  const attempt = attempts.find((item) => item.query === query) || { query, idempotency_key: crypto.randomUUID() };
  try {
    sessionStorage.setItem(storageKey(userId, sourceJobId), JSON.stringify([...attempts.filter((item) => item.query !== query), attempt]));
  } catch {
    throw new RevisionStorageError();
  }
  return attempt;
}

export function clearRevisionAttempt(userId: string, sourceJobId: string, attempt: RevisionAttempt): void {
  const remaining = readRevisionAttempts(userId, sourceJobId).filter((item) => item.idempotency_key !== attempt.idempotency_key);
  try {
    if (remaining.length) sessionStorage.setItem(storageKey(userId, sourceJobId), JSON.stringify(remaining));
    else sessionStorage.removeItem(storageKey(userId, sourceJobId));
  } catch {
    throw new RevisionStorageError();
  }
}
