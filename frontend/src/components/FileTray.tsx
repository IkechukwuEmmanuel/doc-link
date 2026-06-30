import { useCallback, useEffect, useRef, useState } from "react";

import {
  PadFile,
  deleteFile,
  fileUrl,
  listFiles,
  uploadFile,
} from "../api";

interface Props {
  slug: string;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FileTray({ slug }: Props) {
  const [files, setFiles] = useState<PadFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listFiles(slug).then(setFiles).catch(() => {});
  }, [slug]);

  const upload = useCallback(
    async (fileList: FileList | null) => {
      if (!fileList || fileList.length === 0) return;
      setError("");
      setBusy(true);
      try {
        for (const f of Array.from(fileList)) {
          const created = await uploadFile(slug, f);
          setFiles((prev) => [...prev, created]);
        }
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [slug]
  );

  async function remove(id: string) {
    try {
      await deleteFile(slug, id);
      setFiles((prev) => prev.filter((f) => f.id !== id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="file-tray">
      <div
        className={`file-dropzone${dragging ? " is-dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          upload(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Attach files"
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            upload(e.target.files);
            e.target.value = "";
          }}
        />
        <span className="file-dropzone-label">
          {busy ? "Uploading…" : "Tap to add files, or drop them here"}
        </span>
      </div>

      {error && (
        <p className="file-error" role="alert">
          {error}
        </p>
      )}

      {files.length > 0 && (
        <ul className="file-chips">
          {files.map((f) => (
            <li key={f.id} className={`file-chip file-chip--${f.scan_status}`}>
              {f.scan_status === "clean" ? (
                <a
                  className="file-chip-name"
                  href={fileUrl(slug, f.id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {f.filename}
                </a>
              ) : (
                <span className="file-chip-name" title={statusHint(f.scan_status)}>
                  {f.filename}
                </span>
              )}
              <span className="file-chip-meta">
                {f.scan_status === "pending" && "scanning…"}
                {f.scan_status === "failed" && "unavailable"}
                {f.scan_status === "clean" && formatSize(f.size_bytes)}
              </span>
              <button
                type="button"
                className="file-chip-remove"
                onClick={() => remove(f.id)}
                aria-label={`Remove ${f.filename}`}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function statusHint(status: string): string {
  if (status === "pending") return "Still being scanned for malware.";
  if (status === "failed") return "Failed the malware scan and cannot be downloaded.";
  return "";
}
