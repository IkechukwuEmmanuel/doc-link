export interface Pad {
  id: string;
  slug: string;
  owner_id: string | null;
  visibility: string;
  content: string;
  is_anonymous: boolean;
  last_opened_at: string;
  created_at: string;
  updated_at: string;
}

export interface NotFound {
  creatable: boolean;
}

export async function createPad(slug?: string): Promise<Pad> {
  const resp = await fetch("/api/pads", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(slug ? { slug } : {}),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(
      typeof err.detail === "string" ? err.detail : "Could not create pad."
    );
  }
  return resp.json();
}

export type GetPadResult =
  | { kind: "found"; pad: Pad }
  | { kind: "missing"; creatable: boolean };

export async function getPad(slug: string): Promise<GetPadResult> {
  const resp = await fetch(`/api/pads/${encodeURIComponent(slug)}`);
  if (resp.status === 404) {
    const body = await resp.json().catch(() => ({}));
    return { kind: "missing", creatable: Boolean(body?.detail?.creatable) };
  }
  if (!resp.ok) throw new Error("Failed to load pad.");
  return { kind: "found", pad: await resp.json() };
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
