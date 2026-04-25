// Anonymous session UUID per ING-06.
// Generated on first call, persisted in localStorage.
// NEVER used as identity, NEVER used as auth.
// Backend stores it on the clip row but never returns it.
// Anyone with localStorage access already has full app access — there is
// no privilege boundary to protect (T-03-01: accept).

const KEY = "session_id";

export function getOrCreateSessionId(): string {
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(KEY, id);
  }
  return id;
}
