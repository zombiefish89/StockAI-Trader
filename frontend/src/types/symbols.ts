export interface SymbolSearchResult {
  ticker: string;
  displayName: string;
  nameCn?: string | null;
  nameEn?: string | null;
  market?: string | null;
  exchange?: string | null;
  aliases: string[];
  score?: number | null;
}

export interface SymbolSearchResponse {
  query: string;
  limit: number;
  source: "mongo" | "snapshot" | "empty";
  items: SymbolSearchResult[];
}
