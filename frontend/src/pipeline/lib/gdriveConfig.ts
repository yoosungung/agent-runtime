/** Extract Drive folder ID from URL or return trimmed raw ID. */
export function parseGDriveFolderId(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";

  const foldersMatch = trimmed.match(/\/folders\/([a-zA-Z0-9_-]+)/);
  if (foldersMatch) return foldersMatch[1];

  const idParamMatch = trimmed.match(/[?&]id=([a-zA-Z0-9_-]+)/);
  if (idParamMatch) return idParamMatch[1];

  return trimmed;
}
