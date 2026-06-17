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
