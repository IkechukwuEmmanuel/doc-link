import { useCallback, useRef, useState } from "react";

interface Props {
  value: string;
  /** Visible label (e.g. the slug). If omitted, only the icon shows. */
  label?: string;
  ariaLabel: string;
}

/** Copy-to-clipboard pattern (design spec 3): icon→checkmark + success flash,
    no toast. Reused anywhere something is copyable. */
export default function CopyButton({ value, label, ariaLabel }: Props) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const copy = useCallback(async () => {
    const doFallback = (text: string) => {
      try {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        const sel = document.getSelection();
        const range = document.createRange();
        range.selectNodeContents(ta);
        sel?.removeAllRanges();
        sel?.addRange(range);
        const ok = document.execCommand("copy");
        sel?.removeAllRanges();
        document.body.removeChild(ta);
        return ok;
      } catch {
        return false;
      }
    };

    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const ok = doFallback(value);
        if (!ok) return;
      }
    } catch {
      // If the async clipboard API failed, try the fallback.
      if (!doFallback(value)) return;
    }
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  }, [value]);

  return (
    <button
      type="button"
      className={`copy-btn${copied ? " is-copied" : ""}`}
      onClick={copy}
      aria-label={ariaLabel}
    >
      {label && <span className="copy-label">{label}</span>}
      <span className="copy-icon" aria-hidden="true">
        {copied ? <CheckIcon /> : <ClipboardIcon />}
      </span>
    </button>
  );
}

function ClipboardIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}
