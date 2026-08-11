import { useEffect, useId, useMemo, useRef, useState } from "react";

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
}: Props) {
  const id = useId().replaceAll(":", "");
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
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
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, []);
  useEffect(() => setActive(0), [query, open]);

  const choose = (option: AtlasSelectorOption) => {
    onChange(option.value, option);
    setQuery("");
    setOpen(false);
    input.current?.focus();
  };
  const display = open ? query : selected?.label || value;
  return (
    <div className="atlas-selector" ref={root}>
      <label htmlFor={id}>{label}</label>
      <div className="atlas-selector__control">
        <input
          id={id}
          ref={input}
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
            aria-label={`Clear ${label}`}
            onClick={() => onChange("")}
          >
            ×
          </button>
        ) : null}
      </div>
      {open ? (
        <div
          id={`${id}-listbox`}
          className="atlas-selector__menu"
          role="listbox"
          aria-label={`${label} options`}
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
        </div>
      ) : null}
      {error ? <small className="atlas-selector__error">{error}</small> : null}
    </div>
  );
}
