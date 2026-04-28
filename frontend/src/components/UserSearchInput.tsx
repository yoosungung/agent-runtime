import { useState, useEffect, useRef } from "react";
import { apiJson, type PageResponse } from "../lib/api";

interface UserOption {
  id: number;
  username: string;
}

interface Props {
  onSelect: (user: { id: number; username: string }) => void;
  placeholder?: string;
}

export function UserSearchInput({ onSelect, placeholder = "Search users..." }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<UserOption[]>([]);
  const [open, setOpen] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (query.length < 1) {
      setResults([]);
      setOpen(false);
      return;
    }
    timerRef.current = setTimeout(async () => {
      try {
        const data = await apiJson<PageResponse<UserOption>>(
          `/api/users?username=${encodeURIComponent(query)}&limit=10`,
        );
        setResults(data.items);
        setOpen(true);
      } catch {
        setResults([]);
      }
    }, 300);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [query]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function handleSelect(user: UserOption) {
    onSelect(user);
    setQuery("");
    setOpen(false);
    setResults([]);
  }

  return (
    <div ref={containerRef} className="relative">
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={placeholder}
        className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
      />
      {open && results.length > 0 && (
        <div className="absolute z-10 mt-1 w-full bg-white border border-gray-200 rounded shadow-lg max-h-48 overflow-y-auto">
          {results.map((u) => (
            <button
              key={u.id}
              onClick={() => handleSelect(u)}
              className="w-full text-left px-3 py-2 text-sm hover:bg-gray-100"
            >
              {u.username}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
