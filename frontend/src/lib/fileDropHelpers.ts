/** Parse accept string (e.g. ".pdf,.hwp") into normalized lowercase extensions. */
export function parseAcceptExtensions(accept: string): string[] {
  if (!accept || accept === "*") return [];
  return accept.split(",").map((part) => {
    const trimmed = part.trim().toLowerCase().replace("*", "");
    if (!trimmed) return "";
    return trimmed.startsWith(".") ? trimmed : `.${trimmed}`;
  }).filter(Boolean);
}

export function fileMatchesAccept(fileName: string, accept: string): boolean {
  const exts = parseAcceptExtensions(accept);
  if (!exts.length) return true;
  const lower = fileName.toLowerCase();
  return exts.some((ext) => lower.endsWith(ext));
}

export function validateFileSize(file: File, maxMb: number): string | null {
  if (file.size > maxMb * 1024 * 1024) {
    return `File must be under ${maxMb} MB (got ${(file.size / 1024 / 1024).toFixed(1)} MB)`;
  }
  return null;
}

async function readAllDirectoryEntries(
  reader: FileSystemDirectoryReader,
): Promise<FileSystemEntry[]> {
  const entries: FileSystemEntry[] = [];
  let batch: FileSystemEntry[];
  do {
    batch = await new Promise((resolve, reject) => {
      reader.readEntries(resolve, reject);
    });
    entries.push(...batch);
  } while (batch.length > 0);
  return entries;
}

async function collectFilesFromEntry(entry: FileSystemEntry): Promise<File[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => {
      (entry as FileSystemFileEntry).file(resolve, reject);
    });
    return [file];
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const children = await readAllDirectoryEntries(reader);
    const nested = await Promise.all(children.map(collectFilesFromEntry));
    return nested.flat();
  }
  return [];
}

/** Expand dropped folders via File System Access entry API (Chrome/Safari/Edge). */
export async function collectDroppedFiles(
  dataTransfer: DataTransfer,
  allowDirectories: boolean,
): Promise<File[]> {
  if (allowDirectories && dataTransfer.items?.length) {
    const collected: File[] = [];
    for (const item of Array.from(dataTransfer.items)) {
      if (item.kind !== "file") continue;
      const entry = item.webkitGetAsEntry?.() ?? null;
      if (entry) {
        collected.push(...(await collectFilesFromEntry(entry)));
        continue;
      }
      const file = item.getAsFile();
      if (file) collected.push(file);
    }
    if (collected.length > 0) return collected;
  }
  return Array.from(dataTransfer.files);
}

export function filterAcceptedFiles(
  files: File[],
  accept: string,
  maxMb: number,
): { accepted: File[]; rejected: SkippedFile[] } {
  const accepted: File[] = [];
  const rejected: SkippedFile[] = [];
  for (const file of files) {
    const displayName = fileDisplayName(file);
    if (!fileMatchesAccept(file.name, accept)) {
      rejected.push({
        displayName,
        reason: `extension not allowed (allowed: ${accept})`,
      });
      continue;
    }
    const sizeErr = validateFileSize(file, maxMb);
    if (sizeErr) {
      rejected.push({ displayName, reason: sizeErr });
      continue;
    }
    accepted.push(file);
  }
  return { accepted, rejected };
}

export function fileDisplayName(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  return rel?.trim() || file.name;
}

export interface SkippedFile {
  displayName: string;
  reason: string;
}
