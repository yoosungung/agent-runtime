import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

const STORAGE_KEY = "knowledge:selectedProjectId";

type KnowledgeProjectContextValue = {
  selectedProjectId: string | null;
  setSelectedProjectId: (id: string | null) => void;
};

const KnowledgeProjectContext = createContext<KnowledgeProjectContextValue | null>(
  null,
);

function readStoredProjectId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function KnowledgeProjectProvider({ children }: { children: ReactNode }) {
  const [selectedProjectId, setSelectedProjectIdState] = useState<string | null>(
    readStoredProjectId,
  );

  const setSelectedProjectId = useCallback((id: string | null) => {
    setSelectedProjectIdState(id);
    try {
      if (id) {
        localStorage.setItem(STORAGE_KEY, id);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo(
    () => ({ selectedProjectId, setSelectedProjectId }),
    [selectedProjectId, setSelectedProjectId],
  );

  return (
    <KnowledgeProjectContext.Provider value={value}>
      {children}
    </KnowledgeProjectContext.Provider>
  );
}

export function useKnowledgeProjectContext() {
  const ctx = useContext(KnowledgeProjectContext);
  if (!ctx) {
    throw new Error("useKnowledgeProjectContext requires KnowledgeProjectProvider");
  }
  return ctx;
}
