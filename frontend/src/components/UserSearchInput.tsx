import { useEffect, useId, useRef, useState } from "react";
import { useUsersList } from "../hooks/useUsers";

interface UserOption {
  id: number;
  username: string;
}

interface Props {
  onSelect: (user: UserOption) => void;
  placeholder?: string;
  excludeUserIds?: number[];
}

export function UserSearchInput({
  onSelect,
  placeholder = "Search users...",
  excludeUserIds = [],
}: Props) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const inputId = useId();
  const excluded = new Set(excludeUserIds);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const { data, isFetching } = useUsersList(
    {
      username: debouncedQuery || undefined,
      limit: 20,
      offset: 0,
    },
    { enabled: focused },
  );

  const results = (data?.items ?? []).filter((user) => !excluded.has(user.id));
  const open = focused;
  const showList = open && (isFetching || results.length > 0 || debouncedQuery.length > 0);

  useEffect(() => {
    setActiveIndex(-1);
  }, [debouncedQuery, results.length]);

  useEffect(() => {
    function handleClick(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setFocused(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function handleSelect(user: UserOption) {
    onSelect(user);
    setQuery("");
    setDebouncedQuery("");
    setFocused(false);
    setActiveIndex(-1);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!showList || results.length === 0) {
      if (event.key === "Escape") setFocused(false);
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((prev) => (prev + 1) % results.length);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((prev) => (prev <= 0 ? results.length - 1 : prev - 1));
      return;
    }
    if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      const selected = results[activeIndex];
      if (selected) handleSelect(selected);
      return;
    }
    if (event.key === "Escape") {
      setFocused(false);
    }
  }

  return (
    <div ref={containerRef} className="relative min-w-[16rem] flex-1 max-w-md">
      <input
        id={inputId}
        type="search"
        role="combobox"
        aria-label={placeholder}
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          activeIndex >= 0 ? `${listId}-option-${activeIndex}` : undefined
        }
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        data-1p-ignore="true"
        data-lpignore="true"
        data-form-type="other"
        name={`user-search-${inputId}`}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onFocus={() => setFocused(true)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
      />
      {showList && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 w-full bg-white border border-gray-200 rounded shadow-lg max-h-48 overflow-y-auto"
        >
          {isFetching && results.length === 0 && (
            <p className="px-3 py-2 text-sm text-gray-500">검색 중…</p>
          )}
          {!isFetching && results.length === 0 && (
            <p className="px-3 py-2 text-sm text-gray-500">일치하는 사용자 없음</p>
          )}
          {results.map((user, index) => (
            <button
              key={user.id}
              id={`${listId}-option-${index}`}
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => handleSelect(user)}
              className={`w-full text-left px-3 py-2 text-sm ${
                index === activeIndex ? "bg-blue-50 text-blue-800" : "hover:bg-gray-100"
              }`}
            >
              {user.username}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
