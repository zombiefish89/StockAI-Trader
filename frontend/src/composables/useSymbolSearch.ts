import { ref } from "vue";
import type { SymbolSearchResult } from "../types/symbols";
import { searchSymbols } from "../services/api";

export interface SymbolSuggestion extends SymbolSearchResult {
  value: string;
}

interface UseSymbolSearchOptions {
  limit?: number;
  markets?: string[];
}

export function useSymbolSearch(options?: UseSymbolSearchOptions) {
  const loading = ref(false);

  async function fetchSuggestions(queryString: string, cb: (items: SymbolSuggestion[]) => void) {
    const query = queryString.trim();
    if (!query) {
      cb([]);
      return;
    }

    loading.value = true;
    try {
      const response = await searchSymbols(query, {
        limit: options?.limit,
        markets: options?.markets,
      });
      const items = response.items.map((item) => ({
        ...item,
        value: item.ticker,
      }));
      cb(items);
    } catch (err) {
      console.warn("symbol search failed", err);
      cb([]);
    } finally {
      loading.value = false;
    }
  }

  return {
    fetchSuggestions,
    loading,
  };
}
