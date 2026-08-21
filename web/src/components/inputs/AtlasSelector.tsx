import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

export type AtlasSelectorOption = {
  value: string;
  label: string;
  context?: string | null;
};

type Props = {
  label: string;
  value: string;
  options: AtlasSelectorOption[];
  onChange: (value: string, option?: AtlasSelectorOption) => void;
  placeholder?: string;
  disabled?: boolean;
  error?: string;
  searchQuery?: string;
  onSearchQueryChange?: (query: string) => void;
};

/**
 * A small, keyboard-accessible Atlas listbox.  Native datalists are rendered
 * by each browser and cannot provide the product's dark selector treatment or
 * reliably distinguish a duplicated machine number by Plant.
 */
export function AtlasSelector({
  label,
  value,
  options,
  onChange,
  placeholder,
  disabled,
  error,
  searchQuery,
  onSearchQueryChange,
}: Props) {
  const id = useId().replaceAll(":", "");
  const root = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [internalQuery, setInternalQuery] = useState("");
  const [active, setActive] = useState(0);
  const [overlay, setOverlay] = useState<{
    left: number;
    width: number;
    top?: number;
    bottom?: number;
    maxHeight: number;
  }>();
  const query = searchQuery ?? internalQuery;
  const setQuery = (next: string) => {
    setInternalQuery(next);
    onSearchQueryChange?.(next);
  };
  const selected = options.find((option) => option.value === value);
  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return options;
    return options.filter((option) =>
      [option.value, option.label, option.context || ""].some((candidate) =>
        candidate.toLocaleLowerCase().includes(needle),
      ),
    );
  }, [options, query]);

  useEffect(() => {
    const outside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!root.current?.contains(target) && !menu.current?.contains(target))
        setOpen(false);
    };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, []);
  useEffect(() => setActive(0), [query, open]);

  useLayoutEffect(() => {
    if (!open) return;
    const position = () => {
      const rect = root.current?.getBoundingClientRect();
      if (!rect) return;
      const viewportPadding = 8;
      const availableBelow = window.innerHeight - rect.bottom - viewportPadding;
      const availableAbove = rect.top - viewportPadding;
      const above = availableAbove > availableBelow;
      const maxHeight = Math.min(
        250,
        Math.max(0, (above ? availableAbove : availableBelow) - 5),
      );
      const width = Math.min(
        rect.width,
        window.innerWidth - viewportPadding * 2,
      );
      setOverlay({
        left: Math.max(
          viewportPadding,
          Math.min(rect.left, window.innerWidth - width - viewportPadding),
        ),
        width,
        ...(above
          ? { bottom: window.innerHeight - rect.top + 5 }
          : { top: rect.bottom + 5 }),
        maxHeight,
      });
    };
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [open]);

  const choose = (option: AtlasSelectorOption) => {
    onChange(option.value, option);
    setQuery("");
    setOpen(false);
  };
  const clear = () => {
    onChange("");
    setQuery("");
    setOpen(false);
  };
  const display = open ? query : selected?.label || value;
  return (
    <div className="atlas-selector" ref={root}>
      <label htmlFor={id}>{label}</label>
      <div className="atlas-selector__control">
        <input
          id={id}
          value={display}
          placeholder={placeholder || `Search ${label.toLocaleLowerCase()}`}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={`${id}-listbox`}
          aria-activedescendant={
            open && visible[active] ? `${id}-option-${active}` : undefined
          }
          disabled={disabled}
          onFocus={() => {
            setQuery("");
            setOpen(true);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              setQuery("");
              setOpen(false);
            } else if (event.key === "ArrowDown") {
              event.preventDefault();
              setOpen(true);
              setActive((index) =>
                Math.min(index + 1, Math.max(visible.length - 1, 0)),
              );
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setOpen(true);
              setActive((index) => Math.max(index - 1, 0));
            } else if (event.key === "Enter" && open && visible[active]) {
              event.preventDefault();
              choose(visible[active]);
            }
          }}
        />
        {value ? (
          <button
            type="button"
            className="atlas-selector__clear"
            aria-label={`Clear ${label} selection`}
            onMouseDown={(event) => event.preventDefault()}
            onClick={clear}
          >
            ×
          </button>
        ) : null}
      </div>
      {open && overlay
        ? createPortal(
            <div
              id={`${id}-listbox`}
              ref={menu}
              className="atlas-selector__menu atlas-selector__menu--portal"
              role="listbox"
              aria-label={`${label} options`}
              style={overlay}
            >
              {visible.length ? (
                visible.map((option, index) => (
                  <button
                    id={`${id}-option-${index}`}
                    key={option.value}
                    type="button"
                    role="option"
                    aria-selected={option.value === value}
                    data-active={index === active || undefined}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => choose(option)}
                  >
                    <strong>{option.label}</strong>
                    {option.context ? <small>{option.context}</small> : null}
                  </button>
                ))
              ) : (
                <p>No matching options.</p>
              )}
            </div>,
            document.getElementById("atlas-selector-overlay-root") ||
              document.body,
          )
        : null}
      {error ? <small className="atlas-selector__error">{error}</small> : null}
    </div>
  );
}
