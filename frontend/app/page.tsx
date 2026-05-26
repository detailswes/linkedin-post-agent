"use client";
import { useState, useRef, useEffect, useCallback } from "react";

import {
  API_BASE_URL as API,
  clearServerCsrf,
  csrfHeaders,
  refreshCsrfFromServer,
} from "../lib/api";
type Stage = "idle" | "generating" | "awaiting_approval" | "approved";
type TokenStatus = "ok" | "expiring_soon" | "expired" | null;
type AgentId = "research" | "writer" | "editor" | null;

interface LogLine  { id: number; text: string; type: "status" | "error"; }
interface VariantDraft {
  draft_id: string;
  variant: string | null;
  label?: string | null;
  topic: string;
  content: string;
}
interface PostRecord {
  id: string; topic: string; content: string;
  outcome: "approved" | "rejected"; feedback: string | null;
  posted_to_linkedin: boolean; created_at: number; iteration: number;
}
interface ToneProfile {
  approved_count: number; rejected_count: number;
  common_feedback: string[]; approved_samples: string[];
}
interface SavedDraftEntry {
  id: string;
  topic: string;
  content: string;
  created_at: number;
}
interface MemoryData {
  posts: PostRecord[];
  saved_drafts: SavedDraftEntry[];
  tone_profile: ToneProfile;
}
interface MemoryStats {
  total_posts: number; approved_count: number;
  rejected_count: number; has_tone_profile: boolean;
  saved_drafts_count?: number;
}

const EDITOR_RESTORE_KEY = "postforge_editor_restore_v1";
const EDITOR_RESTORE_TTL_MS = 20 * 60 * 1000;

type EditorRestoreV1 = {
  v: 1;
  savedAt: number;
  stage: "awaiting_approval";
  sessionId: string;
  topic: string;
  post: string;
  variantDrafts: VariantDraft[];
  selectedDraftId: string | null;
  iteration: number;
  feedback: string;
};

function clearEditorRestore() {
  try {
    sessionStorage.removeItem(EDITOR_RESTORE_KEY);
  } catch {
    /* ignore */
  }
}

function readEditorRestore(): EditorRestoreV1 | null {
  try {
    const raw = sessionStorage.getItem(EDITOR_RESTORE_KEY);
    if (!raw) return null;
    const o = JSON.parse(raw) as EditorRestoreV1;
    if (o.v !== 1 || o.stage !== "awaiting_approval" || !o.sessionId || !Array.isArray(o.variantDrafts)) {
      return null;
    }
    if (Date.now() - o.savedAt > EDITOR_RESTORE_TTL_MS) {
      sessionStorage.removeItem(EDITOR_RESTORE_KEY);
      return null;
    }
    return o;
  } catch {
    return null;
  }
}

/** Persist awaiting-approval editor state so OAuth return can restore the draft. */
function writeEditorRestoreSnapshot(payload: {
  sessionId: string;
  topic: string;
  post: string;
  variantDrafts: VariantDraft[];
  selectedDraftId: string | null;
  iteration: number;
  feedback: string;
}) {
  try {
    const body: EditorRestoreV1 = {
      v: 1,
      savedAt: Date.now(),
      stage: "awaiting_approval",
      ...payload,
    };
    sessionStorage.setItem(EDITOR_RESTORE_KEY, JSON.stringify(body));
  } catch {
    /* ignore */
  }
}

/* ── Icons ── */
const IconLinkedin = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"/>
    <rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/>
  </svg>
);
const IconCheck = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12"/>
  </svg>
);
const IconX = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
  </svg>
);
const IconRefresh = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4.95"/>
  </svg>
);
const IconSend = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13"/>
    <polygon points="22 2 15 22 11 13 2 9 22 2"/>
  </svg>
);
const IconCopy = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
  </svg>
);
const IconSparkle = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 2l2.4 7.6H22l-6.4 4.8 2.4 7.6L12 17.6l-6 4.4 2.4-7.6L2 9.6h7.6z"/>
  </svg>
);
const IconUpload = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/>
    <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/>
  </svg>
);
const IconWarn = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
    <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
  </svg>
);
const IconBrain = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9.5 2a2.5 2.5 0 0 1 5 0v.5A2.5 2.5 0 0 1 12 5a2.5 2.5 0 0 1-2.5-2.5V2z"/>
    <path d="M4.5 6.5A2.5 2.5 0 0 1 7 4h10a2.5 2.5 0 0 1 2.5 2.5v.5"/>
    <path d="M2 10a3 3 0 0 1 3-3h14a3 3 0 0 1 3 3v4a3 3 0 0 1-3 3H5a3 3 0 0 1-3-3v-4z"/>
    <path d="M6 13h.01M12 13h.01M18 13h.01"/>
  </svg>
);
const IconHistory = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="1 4 1 10 7 10"/>
    <path d="M3.51 15a9 9 0 1 0 .49-4.95L1 10"/>
  </svg>
);
const IconTrash = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/>
    <path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
  </svg>
);

function Spinner({ size = 14, color = "var(--accent)" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="2.5" strokeLinecap="round"
      style={{ animation: "spin 0.9s linear infinite", display: "block", flexShrink: 0 }}>
      <path d="M12 2a10 10 0 0 1 0 20" opacity="0.25"/>
      <path d="M12 2a10 10 0 0 1 10 10"/>
    </svg>
  );
}

/* ── Memory panel ── */
function MemoryPanel({
  onClose,
  initialTab = "history",
  onStatsSynced,
  linkedinConnected,
  onRequestLinkedInForDraftPost,
  onDraftPublishNeedsReconnect,
}: {
  onClose: () => void;
  initialTab?: "history" | "tone" | "drafts";
  /** Re-fetch `/auth/linkedin/me` memory counts so the connect bar matches this panel after load / delete / clear. */
  onStatsSynced?: () => void;
  linkedinConnected: boolean;
  onRequestLinkedInForDraftPost: () => void;
  onDraftPublishNeedsReconnect?: () => void;
}) {
  const [data, setData]       = useState<MemoryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [tab, setTab]         = useState<"history" | "tone" | "drafts">(initialTab);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [publishErr, setPublishErr] = useState<string | null>(null);

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    setPublishErr(null);
  }, [tab]);

  const loadMemory = useCallback(() => {
    setLoading(true);
    fetch(`${API}/api/memory`, { credentials: "include" })
      .then(async r => {
        if (!r.ok) {
          setData(null);
          setLoading(false);
          return;
        }
        const d = (await r.json()) as MemoryData;
        setData({
          posts: d.posts ?? [],
          saved_drafts: d.saved_drafts ?? [],
          tone_profile: d.tone_profile ?? {
            approved_count: 0, rejected_count: 0, common_feedback: [], approved_samples: [],
          },
        });
        setLoading(false);
        onStatsSynced?.();
      })
      .catch(() => {
        setData(null);
        setLoading(false);
      });
  }, [onStatsSynced]);

  useEffect(() => {
    loadMemory();
  }, [loadMemory]);

  const handleClear = async () => {
    if (!confirm("Clear all memory? This resets your tone profile and post history.")) return;
    setClearing(true);
    await refreshCsrfFromServer();
    await fetch(`${API}/api/memory`, { method: "DELETE", credentials: "include", headers: csrfHeaders() });
    await loadMemory();
    setClearing(false);
  };

  const handleDeleteDraft = async (id: string) => {
    if (!confirm("Remove this saved draft?")) return;
    setDeletingId(id);
    await refreshCsrfFromServer();
    const del = await fetch(`${API}/api/memory/saved-drafts/${id}`, {
      method: "DELETE",
      credentials: "include",
      headers: csrfHeaders(),
    });
    if (del.ok) await loadMemory();
    setDeletingId(null);
  };

  const handlePublishDraft = async (id: string) => {
    if (!linkedinConnected) {
      onRequestLinkedInForDraftPost();
      return;
    }
    if (!confirm("Post this draft to LinkedIn now? It will appear on your profile.")) return;
    setPublishErr(null);
    setPublishingId(id);
    try {
      await refreshCsrfFromServer();
      const res = await fetch(`${API}/api/memory/saved-drafts/${id}/publish`, {
        method: "POST",
        credentials: "include",
        headers: csrfHeaders(),
      });
      const body = (await res.json().catch(() => ({}))) as {
        linkedin_posted?: boolean;
        needs_reconnect?: boolean;
        linkedin_result?: { error?: string; expired?: boolean };
        detail?: string | unknown;
      };
      if (res.ok && body.linkedin_posted) {
        await loadMemory();
        return;
      }
      if (body.needs_reconnect) {
        onDraftPublishNeedsReconnect?.();
        setPublishErr(body.linkedin_result?.error || "Reconnect LinkedIn to post.");
        return;
      }
      if (res.status === 403 && typeof body.detail === "string") {
        setPublishErr(body.detail);
        return;
      }
      if (res.ok && !body.linkedin_posted) {
        setPublishErr(body.linkedin_result?.error || "Could not post to LinkedIn.");
        return;
      }
      const apiErr = typeof body.detail === "string" ? body.detail : null;
      setPublishErr(apiErr || body.linkedin_result?.error || "Could not post to LinkedIn.");
    } catch {
      setPublishErr("Network error — try again.");
    } finally {
      setPublishingId(null);
    }
  };

  const formatDate = (ts: number) =>
    new Date(ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 100,
      backgroundColor: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: "20px",
    }} onClick={onClose}>
      <div style={{
        width: "100%", maxWidth: 600, maxHeight: "80vh",
        backgroundColor: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: 16, display: "flex", flexDirection: "column",
        overflow: "hidden",
      }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "16px 20px", borderBottom: "1px solid var(--border)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <IconBrain />
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-1)" }}>Writing Memory</span>
            {data && (
              <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                <span style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 99,
                  backgroundColor: "var(--accent-bg)", color: "var(--accent)",
                  fontFamily: "var(--mono)",
                }}>{data.posts.length === 1 ? "1 post" : `${data.posts.length} posts`}</span>
                {(data.saved_drafts?.length ?? 0) > 0 && (
                  <span style={{
                    fontSize: 10, padding: "2px 8px", borderRadius: 99,
                    backgroundColor: "var(--surface-2)", color: "var(--text-2)",
                    border: "1px solid var(--border)", fontFamily: "var(--mono)",
                  }}>{data.saved_drafts.length === 1 ? "1 draft" : `${data.saved_drafts.length} drafts`}</span>
                )}
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={handleClear} disabled={clearing} style={{
              display: "flex", alignItems: "center", gap: 5,
              padding: "5px 10px", borderRadius: 7,
              backgroundColor: "var(--red-bg)", border: "1px solid var(--red-border)",
              color: "var(--red)", fontSize: 11, cursor: "pointer",
            }}>
              {clearing ? <Spinner size={11} color="var(--red)" /> : <IconTrash />}
              Clear
            </button>
            <button onClick={onClose} style={{
              padding: "5px 10px", borderRadius: 7,
              backgroundColor: "var(--surface-2)", border: "1px solid var(--border)",
              color: "var(--text-2)", fontSize: 11, cursor: "pointer",
            }}>Close</button>
          </div>
        </div>

        {/* Tabs */}
        <div style={{
          display: "flex", gap: 0,
          borderBottom: "1px solid var(--border)",
          backgroundColor: "var(--surface-2)",
        }}>
          {(["history", "drafts", "tone"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: "10px 20px", fontSize: 12, fontWeight: tab === t ? 600 : 400,
              color: tab === t ? "var(--accent)" : "var(--text-3)",
              background: "none", border: "none", cursor: "pointer",
              borderBottom: tab === t ? "2px solid var(--accent)" : "2px solid transparent",
            }}>
              {t === "history" ? "Post history" : t === "drafts" ? "Drafts" : "Tone profile"}
            </button>
          ))}
        </div>

        {/* Body */}
        <div style={{ overflowY: "auto", flex: 1, padding: "16px 20px" }}>
          {loading && (
            <div style={{ color: "var(--text-4)", fontSize: 13, textAlign: "center", paddingTop: 32 }}>
              Loading memory...
            </div>
          )}

          {/* ── History tab ── */}
          {!loading && tab === "history" && (
            <>
              {data?.posts.length === 0 && (
                <div style={{ color: "var(--text-4)", fontSize: 13, textAlign: "center", paddingTop: 32 }}>
                  No posts yet. Generate and approve your first post to start building memory.
                </div>
              )}
              {data?.posts.map(p => (
                <div key={p.id} style={{
                  marginBottom: 12, padding: "12px 14px", borderRadius: 10,
                  backgroundColor: "var(--surface-2)", border: "1px solid var(--border)",
                }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{
                        fontSize: 10, padding: "2px 8px", borderRadius: 99,
                        backgroundColor: p.outcome === "approved" ? "var(--green-bg)" : "var(--red-bg)",
                        border: `1px solid ${p.outcome === "approved" ? "var(--green-border)" : "var(--red-border)"}`,
                        color: p.outcome === "approved" ? "var(--green)" : "var(--red)",
                        fontFamily: "var(--mono)",
                      }}>
                        {p.outcome === "approved" ? "✓ approved" : "✗ rejected"}
                      </span>
                      {p.posted_to_linkedin && (
                        <span style={{
                          fontSize: 10, padding: "2px 8px", borderRadius: 99,
                          backgroundColor: "rgba(10,102,194,0.12)",
                          border: "1px solid rgba(10,102,194,0.3)",
                          color: "#4a9fd4", fontFamily: "var(--mono)",
                        }}>posted</span>
                      )}
                      {p.iteration > 1 && (
                        <span style={{ fontSize: 10, color: "var(--text-4)", fontFamily: "var(--mono)" }}>
                          {p.iteration} iterations
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: 10, color: "var(--text-4)", fontFamily: "var(--mono)" }}>
                      {formatDate(p.created_at)}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text-2)", marginBottom: 4 }}>
                    {p.topic}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-3)", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                    {p.content.slice(0, 180)}{p.content.length > 180 ? "..." : ""}
                  </div>
                  {p.feedback && (
                    <div style={{
                      marginTop: 8, padding: "6px 10px", borderRadius: 6,
                      backgroundColor: "var(--surface-3)", fontSize: 11,
                      color: "var(--text-3)", fontStyle: "italic",
                    }}>
                      Rejection reason: {p.feedback}
                    </div>
                  )}
                </div>
              ))}
            </>
          )}

          {/* ── Drafts tab ── */}
          {!loading && tab === "drafts" && (
            <>
              {publishErr && (
                <div style={{
                  marginBottom: 12, padding: "10px 12px", borderRadius: 8,
                  backgroundColor: "var(--red-bg)", border: "1px solid var(--red-border)",
                  color: "var(--red)", fontSize: 12,
                }}>{publishErr}</div>
              )}
              {(data?.saved_drafts?.length ?? 0) === 0 && (
                <div style={{ color: "var(--text-4)", fontSize: 13, textAlign: "center", paddingTop: 32 }}>
                  No saved drafts yet. When a post is ready, use <strong>Save as draft</strong> to keep it here.
                  From this tab, with LinkedIn connected, use <strong>Post</strong> on a draft to publish it.
                </div>
              )}
              {data?.saved_drafts?.map(s => (
                <div key={s.id} style={{
                  marginBottom: 12, padding: "12px 14px", borderRadius: 10,
                  backgroundColor: "var(--surface-2)", border: "1px solid var(--border)",
                }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6, flexWrap: "wrap", gap: 8 }}>
                    <span style={{
                      fontSize: 10, padding: "2px 8px", borderRadius: 99,
                      backgroundColor: "var(--surface-3)", border: "1px solid var(--border)",
                      color: "var(--text-2)", fontFamily: "var(--mono)",
                    }}>draft</span>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 10, color: "var(--text-4)", fontFamily: "var(--mono)" }}>
                        {formatDate(s.created_at)}
                      </span>
                      <button
                        type="button"
                        onClick={() => handlePublishDraft(s.id)}
                        disabled={publishingId !== null || deletingId === s.id}
                        style={{
                          fontSize: 10, padding: "3px 10px", borderRadius: 6,
                          backgroundColor: "rgba(10,102,194,0.15)", border: "1px solid rgba(10,102,194,0.35)",
                          color: "#4a9fd4", cursor: publishingId !== null || deletingId === s.id ? "not-allowed" : "pointer",
                          display: "inline-flex", alignItems: "center", gap: 5,
                        }}
                      >
                        {publishingId === s.id ? <Spinner size={10} color="#4a9fd4" /> : <IconUpload />}
                        {publishingId === s.id ? "Posting…" : "Post"}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteDraft(s.id)}
                        disabled={deletingId === s.id || publishingId !== null}
                        style={{
                          fontSize: 10, padding: "3px 8px", borderRadius: 6,
                          backgroundColor: "var(--red-bg)", border: "1px solid var(--red-border)",
                          color: "var(--red)", cursor: deletingId === s.id || publishingId !== null ? "wait" : "pointer",
                        }}
                      >
                        {deletingId === s.id ? "…" : "Delete"}
                      </button>
                    </div>
                  </div>
                  <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text-2)", marginBottom: 4 }}>
                    {s.topic || "(no topic)"}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-3)", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                    {s.content.slice(0, 220)}{s.content.length > 220 ? "..." : ""}
                  </div>
                </div>
              ))}
            </>
          )}

          {/* ── Tone tab ── */}
          {!loading && tab === "tone" && data && (
            <>
              {/* Stats row */}
              <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
                {[
                  { label: "Approved", value: data.tone_profile.approved_count, color: "var(--green)", bg: "var(--green-bg)", border: "var(--green-border)" },
                  { label: "Rejected", value: data.tone_profile.rejected_count, color: "var(--red)",   bg: "var(--red-bg)",   border: "var(--red-border)" },
                  { label: "Total",    value: data.posts.length,                 color: "var(--accent)", bg: "var(--accent-bg)", border: "rgba(139,120,255,0.25)" },
                ].map(s => (
                  <div key={s.label} style={{
                    flex: 1, padding: "12px", borderRadius: 10,
                    backgroundColor: s.bg, border: `1px solid ${s.border}`,
                    textAlign: "center",
                  }}>
                    <div style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.value}</div>
                    <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>{s.label}</div>
                  </div>
                ))}
              </div>

              {/* What to avoid */}
              {data.tone_profile.common_feedback.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
                    What you've asked to change (drafts try to avoid these)
                  </div>
                  {data.tone_profile.common_feedback.slice(-5).map((fb, i) => (
                    <div key={i} style={{
                      padding: "7px 12px", marginBottom: 6, borderRadius: 8,
                      backgroundColor: "var(--red-bg)", border: "1px solid var(--red-border)",
                      fontSize: 12, color: "var(--red)",
                    }}>— {fb}</div>
                  ))}
                </div>
              )}

              {/* Style samples */}
              {data.tone_profile.approved_samples.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
                    Your approved style (used as a guide for new posts)
                  </div>
                  {data.tone_profile.approved_samples.map((s, i) => (
                    <div key={i} style={{
                      padding: "10px 12px", marginBottom: 8, borderRadius: 8,
                      backgroundColor: "var(--green-bg)", border: "1px solid var(--green-border)",
                      fontSize: 12, color: "var(--text-2)", lineHeight: 1.6,
                      whiteSpace: "pre-wrap",
                    }}>
                      {s.slice(0, 250)}{s.length > 250 ? "..." : ""}
                    </div>
                  ))}
                </div>
              )}

              {data.tone_profile.approved_count === 0 && (
                <div style={{ color: "var(--text-4)", fontSize: 13, textAlign: "center", paddingTop: 16 }}>
                  Approve your first post to start building a tone profile.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Token expiry banner ── */
function TokenExpiryBanner({ status, daysRemaining, onReconnect, beforeOAuth }: {
  status: TokenStatus; daysRemaining: number; onReconnect: () => void;
  beforeOAuth?: () => void;
}) {
  if (!status || status === "ok") return null;
  const expired = status === "expired";
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "8px 14px", borderRadius: 8, marginTop: 8,
      backgroundColor: expired ? "var(--red-bg)" : "rgba(250,188,46,0.1)",
      border: `1px solid ${expired ? "var(--red-border)" : "rgba(250,188,46,0.35)"}`,
      fontSize: 12, color: expired ? "var(--red)" : "#d4a017",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <IconWarn />
        {expired ? "Your LinkedIn connection has expired."
          : `LinkedIn connection expires in ${daysRemaining} day${daysRemaining !== 1 ? "s" : ""}.`}
      </div>
      <a href={`${API}/auth/linkedin/login`} onClick={() => { beforeOAuth?.(); onReconnect(); }} style={{
        fontSize: 12, fontWeight: 600, color: expired ? "var(--red)" : "#d4a017",
        textDecoration: "underline", cursor: "pointer",
      }}>Reconnect →</a>
    </div>
  );
}

/* ── LinkedIn connect bar ── */
function LinkedInConnectBar({ connected, name, tokenStatus, daysRemaining,
  memoryStats, onDisconnect, onReconnect, onOpenMemory, beforeLinkedInOAuth }: {
  connected: boolean; name: string; tokenStatus: TokenStatus;
  daysRemaining: number; memoryStats: MemoryStats | null;
  onDisconnect: () => void; onReconnect: () => void; onOpenMemory: () => void;
  beforeLinkedInOAuth?: () => void;
}) {
  const postN = memoryStats?.total_posts ?? 0;
  const draftN = memoryStats?.saved_drafts_count ?? 0;
  const memoryHighlight = !!(memoryStats?.has_tone_profile || postN > 0 || draftN > 0);
  const memoryLabel = (() => {
    if (!memoryStats) return "Memory";
    const parts: string[] = [];
    if (postN > 0) parts.push(`${postN} post${postN !== 1 ? "s" : ""}`);
    if (draftN > 0) parts.push(`${draftN} draft${draftN !== 1 ? "s" : ""}`);
    return parts.length ? parts.join(" · ") : "Memory";
  })();

  if (connected) {
    return (
      <div style={{
        padding: "10px 16px", borderRadius: 10, marginBottom: 16,
        backgroundColor: "rgba(10,102,194,0.12)", border: "1px solid rgba(10,102,194,0.3)",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ color: "#0a66c2" }}><IconLinkedin /></div>
            <span style={{ fontSize: 13, color: "var(--text-1)", fontWeight: 500 }}>
              Connected as <strong>{name}</strong>
            </span>
            {tokenStatus === "ok" && (
              <span style={{
                fontSize: 10, padding: "2px 8px", borderRadius: 99,
                backgroundColor: "rgba(61,214,140,0.12)", border: "1px solid rgba(61,214,140,0.3)",
                color: "var(--green)", fontFamily: "var(--mono)",
              }}>live · {daysRemaining}d left</span>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {/* Memory button — shows post / draft counts when present */}
            <button onClick={onOpenMemory} style={{
              display: "flex", alignItems: "center", gap: 5,
              padding: "4px 10px", borderRadius: 7,
              backgroundColor: memoryHighlight ? "var(--accent-bg)" : "var(--surface-2)",
              border: `1px solid ${memoryHighlight ? "rgba(139,120,255,0.3)" : "var(--border)"}`,
              color: memoryHighlight ? "var(--accent)" : "var(--text-3)",
              fontSize: 11, cursor: "pointer",
            }}>
              <IconBrain />
              {memoryLabel}
            </button>
            <button onClick={onDisconnect} style={{
              fontSize: 12, color: "var(--text-3)", background: "none",
              border: "none", cursor: "pointer", textDecoration: "underline",
            }}>Disconnect</button>
          </div>
        </div>
        <TokenExpiryBanner
          status={tokenStatus}
          daysRemaining={daysRemaining}
          onReconnect={onReconnect}
          beforeOAuth={beforeLinkedInOAuth}
        />
      </div>
    );
  }
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "10px 16px", borderRadius: 10, marginBottom: 16,
      backgroundColor: "var(--surface-2)", border: "1px solid var(--border)",
    }}>
      <span style={{ fontSize: 13, color: "var(--text-2)" }}>
        Link LinkedIn to publish from PostForge and train writing memory — more networks coming.
      </span>
      <a
        href={`${API}/auth/linkedin/login`}
        onClick={() => beforeLinkedInOAuth?.()}
        style={{
        display: "flex", alignItems: "center", gap: 7, padding: "7px 16px", borderRadius: 8,
        backgroundColor: "#0a66c2", color: "#fff", fontSize: 13, fontWeight: 600, textDecoration: "none",
      }}>
        <IconLinkedin /> Add LinkedIn
      </a>
    </div>
  );
}

/* ── Reconnect required banner ── */
function ReconnectRequiredBanner() {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "12px 16px", borderRadius: 10, marginBottom: 16,
      backgroundColor: "var(--red-bg)", border: "1px solid var(--red-border)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--red)" }}>
        <IconWarn />
        <span>Connection expired — the post was <strong>not</strong> published.</span>
      </div>
      <a href={`${API}/auth/linkedin/login`} style={{
        display: "flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 8,
        backgroundColor: "#0a66c2", color: "#fff", fontSize: 13, fontWeight: 600,
        textDecoration: "none", whiteSpace: "nowrap",
      }}>
        <IconLinkedin /> Reconnect &amp; repost
      </a>
    </div>
  );
}

/* ── Trending topics ── */
function TrendingTopicsSkeleton() {
  const widths = [118, 88, 142, 105, 92, 128, 96, 115];
  return (
    <div style={{ marginTop: 28, width: "100%" }}>
      <div style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>
        Trending topics
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {widths.map((w, i) => (
          <div key={i} style={{
            width: w, height: 30, borderRadius: 99,
            backgroundColor: "var(--surface-2)", border: "1px solid var(--border)",
            animation: "pulse 1.6s ease-in-out infinite", animationDelay: `${i * 0.08}s`,
          }} />
        ))}
      </div>
    </div>
  );
}

function TrendingTopics({ onSelect }: { onSelect: (t: string) => void }) {
  const [topics, setTopics]   = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [hovered, setHovered] = useState<number | null>(null);

  useEffect(() => {
    fetch(`${API}/api/trending-topics`).then(r => r.json())
      .then(d => { setTopics(d.topics ?? []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <TrendingTopicsSkeleton />;
  if (!topics.length) return null;

  return (
    <div style={{ marginTop: 28, width: "100%" }}>
      <div style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>
        Trending topics · click to generate
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {topics.map((topic, i) => (
          <button key={i} onClick={() => onSelect(topic)}
            onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)}
            style={{
              padding: "6px 14px", borderRadius: 99,
              backgroundColor: hovered === i ? "var(--accent-bg)" : "var(--surface-2)",
              border: `1px solid ${hovered === i ? "rgba(139,120,255,0.45)" : "var(--border)"}`,
              color: hovered === i ? "var(--accent-2)" : "var(--text-2)",
              fontSize: 12.5, fontFamily: "inherit", cursor: "pointer",
              transition: "border-color 0.15s, color 0.15s, background-color 0.15s",
            }}>
            {topic}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Agent pipeline ── */
const AGENTS = [
  { id: "research", label: "Researching", emoji: "🔍" },
  { id: "writer",   label: "Writing",     emoji: "✍️" },
  { id: "editor",   label: "Editing",     emoji: "✨" },
];

function AgentPipeline({ currentAgent, currentVariantLabel }: {
  currentAgent: AgentId; currentVariantLabel: string | null;
}) {
  const active = AGENTS.find(a => a.id === currentAgent);
  return (
    <div style={{ display: "flex", gap: 10, marginBottom: 24, flexWrap: "wrap" }}>
      <div className="fade-up" style={{
        display: "flex", alignItems: "center", gap: 8, padding: "8px 16px", borderRadius: 10,
        backgroundColor: "var(--accent-bg)",
        border: "1px solid rgba(139,120,255,0.35)",
        color: "var(--accent)",
        fontSize: 13, fontWeight: 600, transition: "all 0.3s",
      }}>
        <Spinner size={12} />
        <span>{active ? `${active.emoji} ${active.label}` : "⏳ Starting soon…"}</span>
        {currentVariantLabel && (
          <span style={{ fontSize: 10, fontFamily: "var(--mono)", opacity: 0.7 }}>
            {currentVariantLabel}
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Main ── */
export default function Home() {
  const [topic, setTopic]         = useState("");
  const [stage, setStage]         = useState<Stage>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [logs, setLogs]           = useState<LogLine[]>([]);
  const [post, setPost]           = useState("");
  const [variantDrafts, setVariantDrafts] = useState<VariantDraft[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [feedback, setFeedback]   = useState("");
  const [iteration, setIteration] = useState(1);
  const [copied, setCopied]       = useState(false);
  const [currentAgent, setCurrentAgent] = useState<AgentId>(null);
  const [currentVariantLabel, setCurrentVariantLabel] = useState<string | null>(null);
  const lastStageKeyRef = useRef<string | null>(null);
  const [inputFocused, setInputFocused]       = useState(false);
  const [feedbackFocused, setFeedbackFocused] = useState(false);

  // LinkedIn + memory state
  const [liConnected, setLiConnected]         = useState(false);
  const [liName, setLiName]                   = useState("");
  const [liTokenStatus, setLiTokenStatus]     = useState<TokenStatus>(null);
  const [liDaysRemaining, setLiDaysRemaining] = useState(0);
  const [liPosting, setLiPosting]             = useState(false);
  const [savingDraft, setSavingDraft]         = useState(false);
  const [draftSaveErr, setDraftSaveErr]       = useState<string | null>(null);
  /** After save draft: show success or "already saved" (deduped on server). */
  const [draftSaveHint, setDraftSaveHint] = useState<null | "saved" | "duplicate">(null);
  const [memoryPanelTab, setMemoryPanelTab]   = useState<"history" | "tone" | "drafts">("history");
  const [liPostResult, setLiPostResult]       = useState<{ success: boolean; message: string } | null>(null);
  const [needsReconnect, setNeedsReconnect]   = useState(false);
  const [memoryStats, setMemoryStats]         = useState<MemoryStats | null>(null);
  const [showMemory, setShowMemory]           = useState(false);
  const [nextTopics, setNextTopics]           = useState<string[]>([]);
  const [loadingNextTopics, setLoadingNextTopics] = useState(false);
  /** LinkedIn connect prompt: set when user tries publish or save-to-memory without OAuth. */
  const [linkedinConnectModalFor, setLinkedinConnectModalFor] = useState<null | "publish" | "save_draft" | "post_draft">(null);
  const [appSessionReady, setAppSessionReady] = useState(false);
  const [bootShowRestoreHint, setBootShowRestoreHint] = useState(false);

  const logCounter = useRef(0);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const esRef      = useRef<EventSource | null>(null);

  const refreshMemoryStats = useCallback(() => {
    fetch(`${API}/auth/linkedin/me`, { credentials: "include" })
      .then(r => r.json())
      .then(d => { if (d.memory) setMemoryStats(d.memory); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        await refreshCsrfFromServer();
        if (cancelled) return;
        const r = await fetch(`${API}/auth/linkedin/me`, { credentials: "include" });
        const d = await r.json();
        if (cancelled) return;
        if (d.connected) {
          setLiConnected(true);
          setLiName(d.name);
          setLiTokenStatus(d.token_status ?? "ok");
          setLiDaysRemaining(d.days_remaining ?? 0);
          if (d.memory) setMemoryStats(d.memory);
          await refreshCsrfFromServer();
        } else {
          setLiConnected(false);
          setLiName("");
          setLiDaysRemaining(0);
          if (d.token_status === "expired") {
            setLiTokenStatus("expired");
          } else {
            setLiTokenStatus(null);
          }
          if (d.memory) setMemoryStats(d.memory);
        }

        const restore = readEditorRestore();
        if (restore && d.connected) {
          await refreshCsrfFromServer();
          if (cancelled) return;
          setSessionId(restore.sessionId);
          setTopic(restore.topic);
          setPost(restore.post);
          setVariantDrafts(restore.variantDrafts);
          setSelectedDraftId(restore.selectedDraftId);
          setIteration(restore.iteration);
          setFeedback(restore.feedback);
          setStage("awaiting_approval");
          setLiPostResult(null);
          setNeedsReconnect(false);
          clearEditorRestore();
        }
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setAppSessionReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!appSessionReady) {
      setBootShowRestoreHint(!!readEditorRestore());
    }
  }, [appSessionReady]);

  useEffect(() => { logsEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  const addLog = useCallback((text: string, type: LogLine["type"]) => {
    setLogs(prev => [...prev, { id: logCounter.current++, text, type }]);
  }, []);

  const startStream = useCallback((sid: string, opts?: { variant?: string; feedback?: string; preserveDrafts?: boolean }) => {
    esRef.current?.close();
    setCurrentAgent(null);
    setCurrentVariantLabel(null);
    lastStageKeyRef.current = null;
    if (!opts?.preserveDrafts) {
      setVariantDrafts([]);
      setSelectedDraftId(null);
    }

    const wireEs = (es: EventSource) => {
    es.addEventListener("status", (e) => addLog(JSON.parse((e as MessageEvent).data).message, "status"));
    es.addEventListener("variant_start", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as { variant?: string; label?: string };
      if (d?.label) setCurrentVariantLabel(d.label);
      // Reset the single live status for each variant run.
      setCurrentAgent(null);
      lastStageKeyRef.current = null;
      addLog(`— ${d.label ?? d.variant ?? "Variant"} —`, "status");
    });
    es.addEventListener("stage", (e) => {
      const { agent, label, variant_label } = JSON.parse((e as MessageEvent).data) as {
        agent: AgentId;
        label: string;
        variant?: string;
        variant_label?: string;
      };
      if (variant_label) setCurrentVariantLabel(variant_label);

      // De-dupe any accidental repeats of the same stage event
      const stageKey = `${variant_label ?? ""}:${agent ?? ""}:${label ?? ""}`;
      if (lastStageKeyRef.current === stageKey) return;
      lastStageKeyRef.current = stageKey;

      setCurrentAgent(agent);
      addLog(variant_label ? `[${variant_label}] ${label}` : label, "status");
    });
    es.addEventListener("variants", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as { drafts: VariantDraft[] };
      const drafts = d.drafts ?? [];
      setVariantDrafts(drafts);
      if (drafts.length) {
        setSelectedDraftId(drafts[0].draft_id);
        setPost(drafts[0].content);
      }
      setCurrentAgent(null);
      setStage("awaiting_approval");
      es.close();
    });
    // Only treat **server-sent** SSE `event: error` (MessageEvent + data) as fatal.
    // Native EventSource `error` also fires on `close()` and transient disconnects; those must not
    // reset the UI to idle or we flash back to the topic screen while the job is still running.
    es.addEventListener("error", (e: Event) => {
      if (!(e instanceof MessageEvent) || !e.data) return;
      let msg = "Generation failed.";
      try {
        msg = JSON.parse((e as MessageEvent).data).message ?? msg;
      } catch {
        msg = "Unknown server error";
      }
      addLog(msg, "error");
      setCurrentAgent(null);
      setStage("idle");
      es.close();
    });
    // Let the browser retry the SSE connection while the job is queued / network blips (Render free tier).
    es.onerror = () => {};
    };

    void (async () => {
      try {
        await refreshCsrfFromServer();
        const res = await fetch(`${API}/api/generate`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          credentials: "include",
          body: JSON.stringify({
            session_id: sid,
            variant: opts?.variant ?? undefined,
            feedback: opts?.feedback ?? undefined,
          }),
        });
        if (!res.ok) {
          const t = await res.text();
          addLog(t || `Generate failed (${res.status})`, "error");
          setStage("idle");
          return;
        }
        const data = (await res.json()) as { job_id?: string };
        if (!data.job_id) {
          addLog("No job_id returned from server", "error");
          setStage("idle");
          return;
        }

        const es = new EventSource(`${API}/api/stream/jobs/${data.job_id}`, { withCredentials: true });
        esRef.current = es;
        wireEs(es);
      } catch {
        addLog("Cannot reach backend — is it running on port 8000?", "error");
        setStage("idle");
      }
    })();
  }, [addLog]);

  const handleStart = useCallback(async (value: string) => {
    const cleaned = value.trim();
    if (!cleaned) return;
    clearEditorRestore();
    setLinkedinConnectModalFor(null);
    setStage("generating"); setLogs([]); setPost(""); setVariantDrafts([]); setSelectedDraftId(null);
    setIteration(1); setFeedback(""); setLiPostResult(null); setNeedsReconnect(false);
    try {
      await refreshCsrfFromServer();
      const res  = await fetch(`${API}/api/start`, {
        method: "POST", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        credentials: "include",
        body: JSON.stringify({ topic: cleaned }),
      });
      if (!res.ok) {
        setStage("idle");
        return;
      }
      const data = (await res.json()) as { session_id?: string };
      if (!data.session_id) {
        setStage("idle");
        return;
      }
      setTopic(cleaned);
      setSessionId(data.session_id);
      startStream(data.session_id);
    } catch {
      setStage("idle");
    }
  }, [startStream]);

  const handleApprove = async () => {
    if (!sessionId) return;
    if (!selectedDraftId) return;
    if (!liConnected) {
      setLinkedinConnectModalFor("publish");
      return;
    }
    setLiPosting(true); setNeedsReconnect(false);
    try {
      await refreshCsrfFromServer();
      const res  = await fetch(`${API}/api/approve`, {
        method: "POST", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        credentials: "include",
        body: JSON.stringify({ session_id: sessionId, approved: true, draft_id: selectedDraftId }),
      });
      const data = await res.json();

      if (data.needs_reconnect) {
        setNeedsReconnect(true); setLiConnected(false); setLiTokenStatus("expired");
      } else if (liConnected) {
        setLiPostResult(data.linkedin_posted
          ? { success: true,  message: "✅ Published via your connected account." }
          : { success: false, message: `⚠ Publish failed: ${data.linkedin_result?.error || "Unknown error"}` }
        );
      }
      setStage("approved");

      // Refresh memory stats after approve
      refreshMemoryStats();

      // Fetch next-topic suggestions (Perplexity-like)
      setLoadingNextTopics(true);
      const prevSuggestions = nextTopics;
      setNextTopics([]);
      fetch(`${API}/api/suggestions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        credentials: "include",
        body: JSON.stringify({ topic, post_text: post, exclude: prevSuggestions }),
      })
        .then(r => r.json())
        .then(d => setNextTopics(d.topics ?? []))
        .catch(() => setNextTopics([]))
        .finally(() => setLoadingNextTopics(false));
    } finally {
      setLiPosting(false);
      clearEditorRestore();
    }
  };

  const contentForSaveDraft = (): string | null => {
    if (variantDrafts.length > 0) {
      if (!selectedDraftId) return null;
      const v = variantDrafts.find(d => d.draft_id === selectedDraftId);
      const t = v?.content?.trim();
      return t && t.length > 0 ? t : null;
    }
    const t = post.trim();
    return t.length > 0 ? t : null;
  };

  const handleSaveDraft = async () => {
    if (!sessionId || !topic.trim()) return;
    const content = contentForSaveDraft();
    if (!content) return;
    if (!liConnected) {
      setLinkedinConnectModalFor("save_draft");
      return;
    }
    setSavingDraft(true);
    setDraftSaveErr(null);
    try {
      await refreshCsrfFromServer();
      const res = await fetch(`${API}/api/memory/saved-drafts`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        credentials: "include",
        body: JSON.stringify({
          topic,
          content,
          session_id: sessionId,
          source_draft_id: variantDrafts.length > 0 ? (selectedDraftId ?? undefined) : undefined,
        }),
      });
      if (res.ok) {
        const data = (await res.json()) as { already_saved?: boolean };
        refreshMemoryStats();
        if (data.already_saved) {
          setDraftSaveHint("duplicate");
          setTimeout(() => setDraftSaveHint(null), 5000);
        } else {
          setDraftSaveHint("saved");
          setTimeout(() => setDraftSaveHint(null), 5000);
          setMemoryPanelTab("drafts");
          setShowMemory(true);
        }
      } else {
        let msg = "Could not save draft.";
        try {
          const err = await res.json() as { detail?: string | unknown };
          if (typeof err.detail === "string") msg = err.detail;
        } catch { /* ignore */ }
        setDraftSaveErr(msg);
      }
    } catch {
      setDraftSaveErr("Network error — try again.");
    } finally {
      setSavingDraft(false);
    }
  };

  const handleReject = async () => {
    if (!sessionId) return;
    const fb = feedback.trim();

    const selected = variantDrafts.find(d => d.draft_id === selectedDraftId);
    const selectedLabel = selected?.label ?? (selected?.variant ? selected.variant.replaceAll("_", " ") : null);
    if (selectedLabel) {
      setCurrentVariantLabel(selectedLabel);
      addLog(`Regenerating selected style: ${selectedLabel}`, "status");
    }

    await refreshCsrfFromServer();
    const res  = await fetch(`${API}/api/approve`, {
      method: "POST", headers: { "Content-Type": "application/json", ...csrfHeaders() },
      credentials: "include",
      body: JSON.stringify({
        session_id: sessionId,
        approved: false,
        draft_id: selectedDraftId ?? undefined,
        feedback: fb,
      }),
    });
    const data = await res.json();
    setIteration(data.iteration);
    setPost(""); setFeedback(""); setStage("generating"); setLogs([]); setLiPostResult(null);
    if (data.status === "regenerating_variant" && data.variant) {
      // Preserve the other drafts; only the selected variant regenerates.
      startStream(sessionId, { variant: data.variant, feedback: data.feedback ?? fb, preserveDrafts: true });
    } else {
      // Full regeneration clears all drafts.
      setVariantDrafts([]); setSelectedDraftId(null);
      startStream(sessionId);
    }
  };

  const handleDisconnect = async () => {
    await fetch(`${API}/auth/linkedin/logout`, { method: "POST", credentials: "include" });
    clearServerCsrf();
    setLiConnected(false); setLiName(""); setLiTokenStatus(null);
    setLiDaysRemaining(0); setMemoryStats(null);
    await refreshCsrfFromServer();
  };

  const handleReset = () => {
    esRef.current?.close();
    clearEditorRestore();
    setLinkedinConnectModalFor(null);
    setStage("idle"); setTopic(""); setLogs([]); setPost(""); setFeedback("");
    setIteration(1); setSessionId(null);
    setVariantDrafts([]); setSelectedDraftId(null);
    setCurrentAgent(null); setCurrentVariantLabel(null); setLiPostResult(null); setNeedsReconnect(false);
    setNextTopics([]); setLoadingNextTopics(false);
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(post);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const stashEditorForOAuthReturn = useCallback(() => {
    if (!sessionId) return;
    if (stage !== "awaiting_approval") return;
    writeEditorRestoreSnapshot({
      sessionId,
      topic,
      post,
      variantDrafts,
      selectedDraftId,
      iteration,
      feedback,
    });
  }, [sessionId, stage, topic, post, variantDrafts, selectedDraftId, iteration, feedback]);

  const connectBarProps = {
    connected: liConnected, name: liName, tokenStatus: liTokenStatus,
    daysRemaining: liDaysRemaining, memoryStats,
    onDisconnect: handleDisconnect,
    onReconnect: () => { setLiConnected(false); setLiTokenStatus(null); },
    onOpenMemory: () => { setMemoryPanelTab("history"); setShowMemory(true); },
    beforeLinkedInOAuth: stashEditorForOAuthReturn,
  };

  if (!appSessionReady) {
    return (
      <div style={{
        minHeight: "100vh", backgroundColor: "var(--bg)",
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        padding: 24,
      }}>
        <Spinner size={32} color="var(--accent)" />
        <p style={{
          marginTop: 20, fontSize: 15, color: "var(--text-2)", textAlign: "center",
          maxWidth: 360, lineHeight: 1.55,
        }}>
          {bootShowRestoreHint
            ? "Finishing LinkedIn sign-in and restoring your draft…"
            : "Loading PostForge…"}
        </p>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", backgroundColor: "var(--bg)", display: "flex", flexDirection: "column" }}>

      {showMemory && (
        <MemoryPanel
          initialTab={memoryPanelTab}
          onClose={() => setShowMemory(false)}
          onStatsSynced={refreshMemoryStats}
          linkedinConnected={liConnected}
          onRequestLinkedInForDraftPost={() => setLinkedinConnectModalFor("post_draft")}
          onDraftPublishNeedsReconnect={() => {
            setLiConnected(false);
            setLiTokenStatus("expired");
            refreshMemoryStats();
          }}
        />
      )}

      {linkedinConnectModalFor && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: "fixed", inset: 0, zIndex: 200,
            backgroundColor: "rgba(0,0,0,0.55)", backdropFilter: "blur(4px)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: 20,
          }}
          onClick={() => setLinkedinConnectModalFor(null)}
        >
          <div style={{
            width: "100%", maxWidth: 420,
            backgroundColor: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: 16, padding: "24px 26px",
            boxShadow: "0 24px 48px rgba(0,0,0,0.45)",
          }} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
              <div style={{ color: "#0a66c2" }}><IconLinkedin /></div>
              <h2 style={{ fontSize: 17, fontWeight: 700, color: "var(--text-1)", margin: 0 }}>
                {linkedinConnectModalFor === "save_draft"
                  ? "Connect LinkedIn to save drafts"
                  : linkedinConnectModalFor === "post_draft"
                    ? "Connect LinkedIn to post a saved draft"
                    : "Connect LinkedIn to publish"}
              </h2>
            </div>
            <p style={{ fontSize: 14, color: "var(--text-2)", lineHeight: 1.6, marginBottom: 22 }}>
              {linkedinConnectModalFor === "save_draft" ? (
                <>
                  Saved drafts live in Writing Memory on your account. Your work stays on this page.
                  After you connect, click <strong>Save as draft</strong> again to store it.
                </>
              ) : linkedinConnectModalFor === "post_draft" ? (
                <>
                  After you connect, open <strong>Writing Memory</strong> → <strong>Drafts</strong> and tap <strong>Post</strong> on the draft you want to publish.
                </>
              ) : (
                <>
                  Your draft stays on this page. After you connect, click <strong>Approve &amp; publish</strong> again to post.
                </>
              )}
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <a
                href={`${API}/auth/linkedin/login`}
                onClick={stashEditorForOAuthReturn}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                  padding: "12px 18px", borderRadius: 10,
                  backgroundColor: "#0a66c2", color: "#fff",
                  fontSize: 14, fontWeight: 600, textDecoration: "none",
                }}
              >
                <IconLinkedin /> Add LinkedIn
              </a>
              <button
                type="button"
                onClick={() => setLinkedinConnectModalFor(null)}
                style={{
                  padding: "10px 16px", borderRadius: 10,
                  backgroundColor: "var(--surface-2)", border: "1px solid var(--border)",
                  color: "var(--text-2)", fontSize: 13, cursor: "pointer",
                }}
              >
                Not now
              </button>
            </div>
          </div>
        </div>
      )}

      <div style={{
        position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none",
        backgroundImage: `linear-gradient(var(--border) 1px, transparent 1px),
                          linear-gradient(90deg, var(--border) 1px, transparent 1px)`,
        backgroundSize: "48px 48px",
        maskImage: "radial-gradient(ellipse 80% 80% at 50% 0%, black 20%, transparent 100%)",
      }} />
      <div style={{
        position: "fixed", top: -120, left: "50%", transform: "translateX(-50%)",
        width: 600, height: 300, borderRadius: "50%",
        background: "radial-gradient(ellipse, rgba(139,120,255,0.12) 0%, transparent 70%)",
        pointerEvents: "none", zIndex: 0,
      }} />

      {/* ── HEADER ── */}
      <header style={{
        position: "sticky", top: 0, zIndex: 50,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 24px", height: 56,
        backgroundColor: "rgba(13,13,18,0.85)", backdropFilter: "blur(20px)",
        borderBottom: "1px solid var(--border)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 8, backgroundColor: "var(--accent-bg)",
            border: "1px solid rgba(139,120,255,0.3)",
            display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)",
          }}><IconSparkle /></div>
          <span style={{ fontWeight: 700, fontSize: 15, color: "var(--text-1)", letterSpacing: "-0.02em" }}>PostForge</span>
          <span style={{
            fontSize: 10, fontFamily: "var(--mono)", color: "var(--accent)",
            backgroundColor: "var(--accent-bg)", border: "1px solid rgba(139,120,255,0.25)",
            padding: "2px 8px", borderRadius: 99, letterSpacing: "0.06em", fontWeight: 500,
          }}>AI</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {liConnected && (
            <>
              {/* Memory badge in header */}
              {memoryStats && (memoryStats.total_posts > 0 || (memoryStats.saved_drafts_count ?? 0) > 0) && (
                <button onClick={() => { setMemoryPanelTab("history"); setShowMemory(true); }} style={{
                  display: "flex", alignItems: "center", gap: 5,
                  padding: "5px 10px", borderRadius: 99,
                  backgroundColor: "var(--accent-bg)", border: "1px solid rgba(139,120,255,0.25)",
                  color: "var(--accent)", fontSize: 11, cursor: "pointer", fontFamily: "var(--mono)",
                }}>
                  <IconBrain />
                  {[
                    memoryStats.total_posts > 0 ? `${memoryStats.total_posts} posts` : null,
                    (memoryStats.saved_drafts_count ?? 0) > 0 ? `${memoryStats.saved_drafts_count} drafts` : null,
                  ].filter(Boolean).join(" · ")}
                </button>
              )}
              <div style={{
                display: "flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 99,
                backgroundColor: liTokenStatus === "expiring_soon" ? "rgba(250,188,46,0.1)" : "rgba(10,102,194,0.12)",
                border: `1px solid ${liTokenStatus === "expiring_soon" ? "rgba(250,188,46,0.35)" : "rgba(10,102,194,0.3)"}`,
                fontSize: 12, color: liTokenStatus === "expiring_soon" ? "#d4a017" : "#4a9fd4",
              }}>
                {liTokenStatus === "expiring_soon" && <IconWarn />}
                <IconLinkedin /> {liName}
                {liTokenStatus === "expiring_soon" && (
                  <span style={{ fontSize: 10, fontFamily: "var(--mono)" }}>{liDaysRemaining}d left</span>
                )}
              </div>
            </>
          )}
          {stage !== "idle" && (
            <button onClick={handleReset} style={{
              display: "flex", alignItems: "center", gap: 7, padding: "7px 14px", borderRadius: 8,
              backgroundColor: "var(--surface)", border: "1px solid var(--border)",
              color: "var(--text-2)", fontSize: 13, fontWeight: 500,
            }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--border-hover)")}
              onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--border)")}
            ><IconRefresh /> New post</button>
          )}
        </div>
      </header>

      {/* ── MAIN ── */}
      <main style={{
        flex: 1, position: "relative", zIndex: 1,
        display: "flex", flexDirection: "column", alignItems: "center",
        padding: "0 20px 80px",
      }}>
        {/* ══ IDLE ══ */}
        {stage === "idle" && (
          <div className="fade-up" style={{
            width: "100%", maxWidth: 680,
            display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 80,
          }}>
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 32,
              padding: "5px 14px", borderRadius: 99,
              backgroundColor: "var(--accent-bg)", border: "1px solid rgba(139,120,255,0.25)",
              fontSize: 11, color: "var(--accent)", fontFamily: "var(--mono)",
              letterSpacing: "0.07em", textTransform: "uppercase",
            }}><IconSparkle /> Research · write · refine</div>

            <h1 style={{
              fontSize: "clamp(36px, 6vw, 58px)", fontWeight: 800, lineHeight: 1.08,
              letterSpacing: "-0.04em", textAlign: "center", marginBottom: 18, color: "var(--text-1)",
            }}>
              Write your next<br /><span className="shimmer-text">social post</span>
            </h1>
            <p style={{
              fontSize: 16, color: "var(--text-2)", textAlign: "center",
              lineHeight: 1.65, maxWidth: 420, marginBottom: 40,
            }}>
              AI researches your topic, drafts in your voice, and learns from your feedback — publish when you connect a channel.
            </p>

            <div style={{ width: "100%", marginBottom: 8 }}>
              <LinkedInConnectBar {...connectBarProps} />
            </div>

            {/* Memory hint when active */}
            {memoryStats && memoryStats.has_tone_profile && (
              <div style={{
                width: "100%", marginBottom: 12, padding: "8px 14px", borderRadius: 8,
                backgroundColor: "var(--accent-bg)", border: "1px solid rgba(139,120,255,0.2)",
                display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--accent-2)",
              }}>
                <IconBrain />
                Writing memory on — new posts will follow your approved style and past feedback.
                <button onClick={() => setShowMemory(true)} style={{
                  marginLeft: "auto", fontSize: 11, color: "var(--accent)",
                  background: "none", border: "none", cursor: "pointer", textDecoration: "underline",
                }}>View →</button>
              </div>
            )}

            <div style={{
              width: "100%", backgroundColor: "var(--surface)",
              border: `1px solid ${inputFocused ? "var(--border-focus)" : "var(--border)"}`,
              borderRadius: 16, overflow: "hidden",
              transition: "border-color 0.2s, box-shadow 0.2s",
              boxShadow: inputFocused ? "0 0 0 3px var(--accent-glow)" : "none",
            }}>
              <textarea value={topic} onChange={e => setTopic(e.target.value)}
                onFocus={() => setInputFocused(true)} onBlur={() => setInputFocused(false)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleStart(e.currentTarget.value); } }}
                placeholder="What do you want to post about? e.g. Three lessons from your industry in 2026…"
                rows={4}
                style={{
                  display: "block", width: "100%", background: "transparent",
                  border: "none", outline: "none", color: "var(--text-1)",
                  fontSize: 15, lineHeight: 1.65, padding: "20px 20px 12px",
                  fontFamily: "inherit", resize: "none",
                }}
              />
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "10px 14px 14px", borderTop: "1px solid var(--border)",
              }}>
                <span style={{ fontSize: 12, color: "var(--text-4)", fontFamily: "var(--mono)" }}>
                  ↵ enter · shift+enter for newline
                </span>
                <button onClick={() => handleStart(topic)} disabled={!topic.trim()} style={{
                  display: "flex", alignItems: "center", gap: 8, padding: "10px 20px", borderRadius: 10,
                  backgroundColor: topic.trim() ? "var(--accent)" : "var(--surface-3)",
                  color: topic.trim() ? "#fff" : "var(--text-4)",
                  border: "none", fontWeight: 600, fontSize: 14,
                  boxShadow: topic.trim() ? "0 0 20px rgba(139,120,255,0.35)" : "none",
                  opacity: topic.trim() ? 1 : 0.5, cursor: topic.trim() ? "pointer" : "not-allowed",
                }}>
                  <IconSend /> Generate
                </button>
              </div>
            </div>

            <TrendingTopics onSelect={t => handleStart(t)} />
          </div>
        )}

        {/* ══ GENERATING ══ */}
        {stage === "generating" && (
          <div className="fade-up" style={{ width: "100%", maxWidth: 680, paddingTop: 48 }}>
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              padding: "6px 14px", borderRadius: 99, marginBottom: 28,
              backgroundColor: "var(--surface-2)", border: "1px solid var(--border)",
              fontSize: 13, color: "var(--text-2)", maxWidth: "100%",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              <span style={{ fontSize: 10, color: "var(--accent)", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.07em" }}>topic</span>
              <span style={{ color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis" }}>{topic}</span>
            </div>
            <AgentPipeline currentAgent={currentAgent} currentVariantLabel={currentVariantLabel} />
            <div style={{
              backgroundColor: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 14, overflow: "hidden", boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
            }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 6, padding: "11px 16px",
                backgroundColor: "var(--surface-2)", borderBottom: "1px solid var(--border)",
              }}>
                {["#ff5f57", "#febc2e", "#28c840"].map(c => (
                  <div key={c} style={{ width: 11, height: 11, borderRadius: "50%", backgroundColor: c }} />
                ))}
                <div style={{ flex: 1 }} />
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-4)" }}>
                  <div className="pulsing" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: "var(--green)" }} />
                  {iteration > 1 ? `iteration ${iteration}` : "live output"}
                </div>
              </div>
              <div style={{ height: 320, overflowY: "auto", padding: "16px 20px", fontFamily: "var(--mono)", fontSize: 12.5, lineHeight: 1.75 }}>
                {logs.length === 0 && <div style={{ color: "var(--text-4)" }}>Preparing your post…<span className="cursor" /></div>}
                {logs.map((line, idx) => (
                  <div key={line.id} className="slide-in" style={{
                    animationDelay: `${Math.min(idx * 0.04, 0.4)}s`,
                    color: line.type === "error" ? "var(--red)" : "var(--accent-2)",
                    display: "flex", gap: 10, alignItems: "flex-start",
                  }}>
                    <span style={{ color: line.type === "error" ? "var(--red)" : "var(--accent)", marginTop: 1, flexShrink: 0, fontSize: 10 }}>›</span>
                    <span>{line.text}</span>
                  </div>
                ))}
                {logs.length > 0 && <div className="cursor" style={{ height: 20 }} />}
                <div ref={logsEndRef} />
              </div>
            </div>
          </div>
        )}

        {/* ══ AWAITING APPROVAL ══ */}
        {stage === "awaiting_approval" && (
          <div className="fade-up" style={{ width: "100%", maxWidth: 680, paddingTop: 48 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div className="pulsing" style={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: "var(--green)" }} />
                <span style={{ fontSize: 13, color: "var(--text-2)", fontFamily: "var(--mono)" }}>
                  Post ready · iteration {iteration}
                </span>
              </div>
              <span style={{ fontSize: 11, color: "var(--text-4)", fontFamily: "var(--mono)" }}>
                ~{post.split(/\s+/).filter(Boolean).length} words
              </span>
            </div>
            <LinkedInConnectBar {...connectBarProps} />
            {/* Variant picker */}
            {variantDrafts.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                  gap: 10,
                }}>
                {variantDrafts.map(v => {
                  const selected = v.draft_id === selectedDraftId;
                  return (
                    <button
                      key={v.draft_id}
                      onClick={() => {
                        if (selectedDraftId === v.draft_id) {
                          setSelectedDraftId(null);
                          return;
                        }
                        setSelectedDraftId(v.draft_id);
                        setPost(v.content);
                      }}
                      style={{
                        textAlign: "left",
                        padding: "12px 14px",
                        borderRadius: 12,
                        backgroundColor: selected ? "var(--accent-bg)" : "var(--surface)",
                        border: `1px solid ${selected ? "rgba(139,120,255,0.45)" : "var(--border)"}`,
                        cursor: "pointer",
                      }}>
                      <div style={{ fontSize: 12, fontWeight: 650, color: selected ? "var(--accent)" : "var(--text-1)" }}>
                        {v.label ?? v.variant ?? "variant"}
                      </div>
                      <div style={{ marginTop: 6, fontSize: 11, color: "var(--text-4)" }}>
                        {v.content.split(/\s+/).slice(0, 18).join(" ")}{v.content.split(/\s+/).length > 18 ? "…" : ""}
                      </div>
                    </button>
                  );
                })}
                </div>
                {!selectedDraftId && (
                  <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-4)", fontFamily: "var(--mono)" }}>
                    Select a version to publish or save as draft.
                  </div>
                )}
              </div>
            )}

            <div style={{
              backgroundColor: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 16, padding: "28px 28px 20px", marginBottom: 16,
              position: "relative", overflow: "hidden",
            }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: "linear-gradient(90deg, var(--accent) 0%, var(--accent-2) 40%, transparent 100%)" }} />
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
                <div style={{ width: 40, height: 40, borderRadius: "50%", backgroundColor: "var(--accent-bg)", border: "1px solid rgba(139,120,255,0.3)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)" }}>
                  <IconLinkedin />
                </div>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-1)" }}>Draft preview</div>
                  <div style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--mono)" }}>PostForge</div>
                </div>
              </div>
              <p style={{ fontSize: 15, lineHeight: 1.78, color: "var(--text-1)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{post}</p>
              <div style={{
                marginTop: 20, paddingTop: 16,
                borderTop: "1px solid var(--border)",
              }}>
                <div style={{ fontSize: 10, fontFamily: "var(--mono)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>
                  {variantDrafts.length > 1 ? "Save selected version only" : "Save without publishing"}
                </div>
                <button
                  type="button"
                  onClick={handleSaveDraft}
                  disabled={savingDraft || liPosting || !sessionId || !topic.trim() || !contentForSaveDraft()}
                  style={{
                    width: "100%", display: "flex", alignItems: "center", justifyContent: "center",
                    gap: 8, padding: "12px 16px", borderRadius: 10,
                    backgroundColor: "var(--surface-2)", border: "1px solid var(--border)",
                    color: "var(--text-2)", fontSize: 13, fontWeight: 600,
                    opacity: (savingDraft || liPosting || !sessionId || !topic.trim() || !contentForSaveDraft()) ? 0.45 : 1,
                    cursor: (savingDraft || liPosting || !sessionId || !topic.trim() || !contentForSaveDraft()) ? "not-allowed" : "pointer",
                  }}
                >
                  {savingDraft ? <><Spinner size={14} color="var(--accent)" /> Saving…</> : "Save as draft"}
                </button>
                {draftSaveErr && (
                  <div style={{ marginTop: 10, fontSize: 12, color: "var(--red)", textAlign: "center" }}>{draftSaveErr}</div>
                )}
                {draftSaveHint === "saved" && (
                  <div style={{ marginTop: 10, fontSize: 12, color: "var(--green)", textAlign: "center" }}>
                    Saved — Writing Memory → Drafts (this version only).
                  </div>
                )}
                {draftSaveHint === "duplicate" && (
                  <div style={{ marginTop: 10, fontSize: 12, color: "var(--text-3)", textAlign: "center" }}>
                    This exact draft is already in Writing Memory — nothing new was added.
                  </div>
                )}
              </div>
            </div>
            <div style={{
              backgroundColor: "var(--surface)",
              border: `1px solid ${feedbackFocused ? "var(--border-focus)" : "var(--border)"}`,
              borderRadius: 12, padding: "14px 16px", marginBottom: 14,
              transition: "border-color 0.2s, box-shadow 0.2s",
              boxShadow: feedbackFocused ? "0 0 0 3px var(--accent-glow)" : "none",
            }}>
              <div style={{ fontSize: 10, fontFamily: "var(--mono)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 10 }}>
                Feedback for regeneration (optional) · saved to memory
              </div>
              <textarea value={feedback} onChange={e => setFeedback(e.target.value)}
                onFocus={() => setFeedbackFocused(true)} onBlur={() => setFeedbackFocused(false)}
                placeholder="Make it shorter, add more data, change the tone..."
                rows={2}
                style={{ display: "block", width: "100%", background: "transparent", border: "none", outline: "none", color: "var(--text-1)", fontSize: 14, lineHeight: 1.6, fontFamily: "inherit", resize: "none" }}
              />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", gap: 10 }}>
                <button onClick={handleApprove} disabled={liPosting} style={{
                  flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
                  gap: 9, padding: "14px 20px", borderRadius: 11,
                  backgroundColor: "var(--green-bg)", border: "1px solid var(--green-border)",
                  color: "var(--green)", fontSize: 14, fontWeight: 600,
                  opacity: liPosting ? 0.6 : 1, cursor: liPosting ? "not-allowed" : "pointer",
                }}
                  onMouseEnter={e => !liPosting && (e.currentTarget.style.backgroundColor = "rgba(61,214,140,0.14)")}
                  onMouseLeave={e => (e.currentTarget.style.backgroundColor = "var(--green-bg)")}
                >
                  {liPosting ? <><Spinner size={14} color="var(--green)" /> Publishing...</>
                    : liConnected ? <><IconUpload /> Approve &amp; publish</>
                    : <><IconLinkedin /> Publish to LinkedIn</>}
                </button>
                <button onClick={handleReject} disabled={liPosting} style={{
                  flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
                  gap: 9, padding: "14px 20px", borderRadius: 11,
                  backgroundColor: "var(--red-bg)", border: "1px solid var(--red-border)",
                  color: "var(--red)", fontSize: 14, fontWeight: 600,
                  opacity: liPosting ? 0.4 : 1, cursor: liPosting ? "not-allowed" : "pointer",
                }}
                  onMouseEnter={e => !liPosting && (e.currentTarget.style.backgroundColor = "rgba(255,107,107,0.14)")}
                  onMouseLeave={e => (e.currentTarget.style.backgroundColor = "var(--red-bg)")}
                >
                  <IconX size={16} /> Regenerate
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ══ APPROVED ══ */}
        {stage === "approved" && (
          <div className="fade-up" style={{ width: "100%", maxWidth: 680, paddingTop: 64, textAlign: "center" }}>
            <div style={{
              width: 60, height: 60, borderRadius: "50%", margin: "0 auto 24px",
              backgroundColor: "var(--green-bg)", border: "1px solid var(--green-border)",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--green)", boxShadow: "0 0 32px rgba(61,214,140,0.2)",
            }}><IconCheck size={26} /></div>
            <h2 style={{ fontSize: 26, fontWeight: 800, letterSpacing: "-0.03em", color: "var(--text-1)", marginBottom: 16 }}>Post approved!</h2>
            {needsReconnect && <ReconnectRequiredBanner />}
            {!needsReconnect && liPostResult && (
              <div style={{
                display: "inline-flex", alignItems: "center", gap: 8,
                padding: "10px 18px", borderRadius: 10, marginBottom: 20,
                backgroundColor: liPostResult.success ? "rgba(10,102,194,0.12)" : "var(--red-bg)",
                border: `1px solid ${liPostResult.success ? "rgba(10,102,194,0.3)" : "var(--red-border)"}`,
                color: liPostResult.success ? "#4a9fd4" : "var(--red)", fontSize: 14, fontWeight: 500,
              }}>
                {liPostResult.success ? <IconLinkedin /> : <IconX size={14} />}
                {liPostResult.message}
              </div>
            )}
            {!needsReconnect && !liPostResult && (
              <p style={{ color: "var(--text-2)", fontSize: 14, marginBottom: 20 }}>Copy and use wherever you publish.</p>
            )}
            <div style={{
              backgroundColor: "var(--surface)", border: "1px solid var(--green-border)",
              borderRadius: 16, padding: "28px 28px 20px", marginBottom: 20,
              textAlign: "left", position: "relative", overflow: "hidden",
            }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: "linear-gradient(90deg, var(--green) 0%, transparent 70%)" }} />
              <p style={{ fontSize: 15, lineHeight: 1.78, color: "var(--text-1)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{post}</p>
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
              <button onClick={handleCopy} style={{
                display: "flex", alignItems: "center", gap: 8, padding: "12px 24px", borderRadius: 10,
                backgroundColor: copied ? "var(--green-bg)" : "var(--accent)",
                border: copied ? "1px solid var(--green-border)" : "none",
                color: copied ? "var(--green)" : "#fff", fontWeight: 600, fontSize: 14, cursor: "pointer",
                boxShadow: copied ? "none" : "0 0 20px rgba(139,120,255,0.35)",
              }}>
                {copied ? <><IconCheck size={14} /> Copied!</> : <><IconCopy /> Copy to clipboard</>}
              </button>
              <button onClick={handleReset} style={{
                display: "flex", alignItems: "center", gap: 8, padding: "12px 24px", borderRadius: 10,
                backgroundColor: "var(--surface)", border: "1px solid var(--border)",
                color: "var(--text-2)", fontSize: 14, fontWeight: 500, cursor: "pointer",
              }}
                onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--border-hover)")}
                onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--border)")}
              ><IconRefresh /> Generate another</button>
            </div>

            {/* Next topic suggestions */}
            <div style={{ marginTop: 26, textAlign: "left" }}>
              <div style={{
                fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-4)",
                textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10,
              }}>
                Next topics (based on this post)
              </div>

              {loadingNextTopics && (
                <div style={{ color: "var(--text-4)", fontSize: 13 }}>Loading suggestions…</div>
              )}

              {!loadingNextTopics && nextTopics.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {nextTopics.slice(0, 8).map((t, i) => (
                    <button key={`${t}-${i}`} onClick={() => handleStart(t)} style={{
                      padding: "6px 14px", borderRadius: 99,
                      backgroundColor: "var(--surface-2)",
                      border: "1px solid var(--border)",
                      color: "var(--text-2)",
                      fontSize: 12.5, cursor: "pointer",
                    }}>
                      {t}
                    </button>
                  ))}
                </div>
              )}

              {!loadingNextTopics && nextTopics.length === 0 && (
                <div style={{ color: "var(--text-4)", fontSize: 13 }}>
                  No suggestions yet. Generate another topic to get recommendations.
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      <style jsx global>{`
        @keyframes spin    { to { transform: rotate(360deg); } }
        @keyframes pulse   { 0%,100%{opacity:1}50%{opacity:.35} }
        @keyframes blink   { 0%,100%{opacity:1}50%{opacity:0} }
        @keyframes slideIn { from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:translateX(0)} }
        @keyframes shimmer { 0%{background-position:-600px 0}100%{background-position:600px 0} }
        @keyframes fadeUp  { from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:translateY(0)} }
      `}</style>
    </div>
  );
}