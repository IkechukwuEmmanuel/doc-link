export type Visibility = "public_edit" | "public_view" | "private";
export type CollaboratorRole = "viewer" | "editor";
export type PinFormat = "numeric" | "alphanumeric";

export interface Pad {
  id: string;
  slug: string;
  name: string | null;
  owner_id: string | null;
  visibility: Visibility;
  is_archived: boolean;
  content: string;
  is_anonymous: boolean;
  last_opened_at: string;
  created_at: string;
  updated_at: string;
  can_edit: boolean;
  pin_protected: boolean;
  pin_format: PinFormat | null;
  // True when the pad is PIN-gated and this requester hasn't unlocked it yet;
  // when set, `content` is withheld (empty) and the locked screen is shown.
  locked: boolean;
}

export interface PadListItem {
  id: string;
  slug: string;
  name: string | null;
  visibility: Visibility;
  is_archived: boolean;
  pin_protected: boolean;
  last_opened_at: string;
  created_at: string;
  updated_at: string;
  file_count: number;
  size_bytes: number;
}

export interface Collaborator {
  user_id: string;
  email: string;
  display_name: string | null;
  role: CollaboratorRole;
  invited_at: string;
  accepted_at: string | null;
}

export interface NotFound {
  creatable: boolean;
}

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

async function detailError(resp: Response, fallback: string): Promise<never> {
  const err = await resp.json().catch(() => ({}));
  throw new Error(typeof err.detail === "string" ? err.detail : fallback);
}

/** Create a pad. When `fetcher` is the authed fetch, the pad is owned at
 *  creation time (no separate claim) — used by the dashboard "New Pad" action. */
export async function createPad(
  slug?: string,
  fetcher: Fetcher = fetch
): Promise<Pad> {
  const resp = await fetcher("/api/pads", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(slug ? { slug } : {}),
  });
  if (!resp.ok) await detailError(resp, "Could not create pad.");
  return resp.json();
}

export type GetPadResult =
  | { kind: "found"; pad: Pad }
  | { kind: "missing"; creatable: boolean }
  | { kind: "forbidden" };

export async function getPad(
  slug: string,
  fetcher: Fetcher = fetch
): Promise<GetPadResult> {
  const resp = await fetcher(`/api/pads/${encodeURIComponent(slug)}`);
  if (resp.status === 404) {
    const body = await resp.json().catch(() => ({}));
    return { kind: "missing", creatable: Boolean(body?.detail?.creatable) };
  }
  if (resp.status === 403) return { kind: "forbidden" };
  if (!resp.ok) throw new Error("Failed to load pad.");
  return { kind: "found", pad: await resp.json() };
}

// --- Dashboard / management (authenticated) --------------------------------
export async function listMyPads(
  fetcher: Fetcher,
  opts: { archived?: boolean; q?: string } = {}
): Promise<PadListItem[]> {
  const params = new URLSearchParams();
  if (opts.archived) params.set("archived", "true");
  if (opts.q) params.set("q", opts.q);
  const qs = params.toString();
  const resp = await fetcher(`/api/pads${qs ? `?${qs}` : ""}`);
  if (!resp.ok) throw new Error("Failed to load your pads.");
  return resp.json();
}

export async function patchPad(
  fetcher: Fetcher,
  slug: string,
  patch: {
    name?: string | null;
    visibility?: Visibility;
    is_archived?: boolean;
    pin_protected?: boolean;
    pin?: string;
    pin_format?: PinFormat;
  }
): Promise<Pad> {
  const resp = await fetcher(`/api/pads/${encodeURIComponent(slug)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!resp.ok) await detailError(resp, "Could not update pad.");
  return resp.json();
}

export type UnlockResult =
  | { kind: "ok"; pad: Pad }
  | { kind: "incorrect"; message: string }
  | { kind: "rate_limited"; message: string; retryAfter: number };

/** Submit a PIN to unlock a PIN-protected pad. Distinguishes an incorrect PIN
 *  (401) from a rate-limited lockout (429) so the UI can render each clearly.
 *  The server sets the unlock cookie on success; credentials must be included. */
export async function unlockPad(
  slug: string,
  pin: string,
  fetcher: Fetcher = fetch
): Promise<UnlockResult> {
  const resp = await fetcher(`/api/pads/${encodeURIComponent(slug)}/unlock`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ pin }),
  });
  if (resp.ok) return { kind: "ok", pad: await resp.json() };
  const err = await resp.json().catch(() => ({}));
  const message = typeof err.detail === "string" ? err.detail : "Incorrect PIN.";
  if (resp.status === 429) {
    const retryAfter = Number(resp.headers.get("retry-after")) || 0;
    return { kind: "rate_limited", message, retryAfter };
  }
  return { kind: "incorrect", message };
}

export async function deletePad(fetcher: Fetcher, slug: string): Promise<void> {
  const resp = await fetcher(`/api/pads/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
  if (!resp.ok && resp.status !== 204) await detailError(resp, "Could not delete pad.");
}

export async function listCollaborators(
  fetcher: Fetcher,
  slug: string
): Promise<Collaborator[]> {
  const resp = await fetcher(`/api/pads/${encodeURIComponent(slug)}/collaborators`);
  if (!resp.ok) throw new Error("Failed to load collaborators.");
  return resp.json();
}

export async function addCollaborator(
  fetcher: Fetcher,
  slug: string,
  email: string,
  role: CollaboratorRole
): Promise<Collaborator> {
  const resp = await fetcher(
    `/api/pads/${encodeURIComponent(slug)}/collaborators`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, role }),
    }
  );
  if (!resp.ok) await detailError(resp, "Could not add collaborator.");
  return resp.json();
}

export async function removeCollaborator(
  fetcher: Fetcher,
  slug: string,
  userId: string
): Promise<void> {
  const resp = await fetcher(
    `/api/pads/${encodeURIComponent(slug)}/collaborators/${userId}`,
    { method: "DELETE" }
  );
  if (!resp.ok && resp.status !== 204)
    await detailError(resp, "Could not remove collaborator.");
}

// --- Account recovery (public) ---------------------------------------------
export async function requestPasswordReset(email: string): Promise<void> {
  await fetch("/api/auth/password-reset/request", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export async function confirmPasswordReset(
  token: string,
  newPassword: string
): Promise<void> {
  const resp = await fetch("/api/auth/password-reset/confirm", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (!resp.ok) await detailError(resp, "Could not reset password.");
}

export async function confirmEmailVerification(token: string): Promise<void> {
  const resp = await fetch("/api/auth/verify-email/confirm", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!resp.ok) await detailError(resp, "Could not verify email.");
}

export async function savePad(slug: string, content: string): Promise<void> {
  const resp = await fetch(`/api/pads/${encodeURIComponent(slug)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!resp.ok) throw new Error("Failed to save.");
}

export type ScanStatus = "pending" | "clean" | "failed";

export interface PadFile {
  id: string;
  pad_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  scan_status: ScanStatus;
  created_at: string;
}

export function fileUrl(slug: string, id: string): string {
  return `/api/pads/${encodeURIComponent(slug)}/files/${id}`;
}

export async function listFiles(slug: string): Promise<PadFile[]> {
  const resp = await fetch(`/api/pads/${encodeURIComponent(slug)}/files`);
  if (!resp.ok) throw new Error("Failed to load files.");
  return resp.json();
}

export async function uploadFile(slug: string, file: File): Promise<PadFile> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`/api/pads/${encodeURIComponent(slug)}/files`, {
    method: "POST",
    body: form,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(
      typeof err.detail === "string" ? err.detail : "Upload failed."
    );
  }
  return resp.json();
}

export async function deleteFile(slug: string, id: string): Promise<void> {
  const resp = await fetch(`/api/pads/${encodeURIComponent(slug)}/files/${id}`, {
    method: "DELETE",
  });
  if (!resp.ok && resp.status !== 204) throw new Error("Failed to delete file.");
}
