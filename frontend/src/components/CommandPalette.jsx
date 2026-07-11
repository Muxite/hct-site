import { useEffect, useMemo, useRef, useState } from "react";
import { searchCommands } from "../lib/variants.js";

const KIND_TAG = { paper: "paper", project: "project", person: "person" };

// ⌘K / Ctrl-K jump-to. A single flat index of every paper, project, and
// person; type to filter, arrows to move, Enter to open. Kept theme-agnostic —
// it inherits the active variant's CSS variables so it looks native in each.
export default function CommandPalette({ index }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);

  // Global hotkey: ⌘K / Ctrl-K toggles; "/" opens when not already typing.
  useEffect(() => {
    const onKey = (e) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "/" && !isTyping(e.target) && !open) {
        e.preventDefault();
        setOpen(true);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      // focus after the overlay paints
      const id = requestAnimationFrame(() => inputRef.current?.focus());
      return () => cancelAnimationFrame(id);
    }
  }, [open]);

  const results = useMemo(() => searchCommands(index, query, 9), [index, query]);

  useEffect(() => setActive(0), [query]);

  if (!open) {
    return (
      <button
        type="button"
        className="vlab-kbd-hint"
        onClick={() => setOpen(true)}
        aria-label="Open command palette"
      >
        <kbd>⌘K</kbd> Jump to anything
      </button>
    );
  }

  const go = (item) => {
    if (!item) return;
    setOpen(false);
    window.location.hash = item.href.replace(/^#/, "");
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(results[active]);
    }
  };

  return (
    <div className="vlab-cmd" role="dialog" aria-modal="true" aria-label="Jump to anything">
      <button className="vlab-cmd__scrim" aria-label="Close" onClick={() => setOpen(false)} />
      <div className="vlab-cmd__box">
        <div className="vlab-cmd__field">
          <span className="vlab-cmd__prompt">›</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search papers, projects, people…"
            aria-label="Search"
            autoComplete="off"
            spellCheck="false"
          />
          <kbd>esc</kbd>
        </div>
        <ul className="vlab-cmd__list">
          {results.length === 0 && <li className="vlab-cmd__empty">No matches. Try a name, title, or year.</li>}
          {results.map((it, i) => (
            <li key={`${it.kind}-${it.href}-${i}`}>
              <button
                className={`vlab-cmd__item${i === active ? " is-active" : ""}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => go(it)}
              >
                <span className={`vlab-cmd__kind vlab-cmd__kind--${it.kind}`}>{KIND_TAG[it.kind]}</span>
                <span className="vlab-cmd__title">{it.title}</span>
                {it.sub && <span className="vlab-cmd__sub">{it.sub}</span>}
              </button>
            </li>
          ))}
        </ul>
        <div className="vlab-cmd__foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}

function isTyping(el) {
  const tag = (el?.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || el?.isContentEditable;
}
