import axios from "axios";
import type { StockAIReport } from "../types/report";
import type { SymbolSearchResponse } from "../types/symbols";
import type { AnalysisHistoryRecord } from "../types/history";
import { API_BASE } from "../config/api";

export async function analyzeOne(ticker: string, timeframe = "1d"): Promise<StockAIReport> {
  const { data } = await axios.post<StockAIReport>(`${API_BASE}/analyze`, {
    ticker,
    timeframe,
  });
  return data;
}

interface SymbolSearchParams {
  limit?: number;
  markets?: string[];
}

export async function searchSymbols(
  query: string,
  params?: SymbolSearchParams,
): Promise<SymbolSearchResponse> {
  const searchParams: Record<string, string | number> = {
    q: query,
    limit: params?.limit ?? 10,
  };
  if (params?.markets?.length) {
    searchParams.markets = params.markets.join(",");
  }
  const { data } = await axios.get<SymbolSearchResponse>(`${API_BASE}/symbols/search`, {
    params: searchParams,
  });
  return data;
}

interface HistoryQueryParams {
  ticker?: string;
  timeframe?: string;
  limit?: number;
  offset?: number;
}

export async function fetchAnalysisHistory(
  params: HistoryQueryParams,
): Promise<AnalysisHistoryRecord[]> {
  const query: Record<string, string | number> = {
    limit: params.limit ?? 20,
    offset: params.offset ?? 0,
  };
  if (params.ticker) {
    query.ticker = params.ticker;
  }
  if (params.timeframe) {
    query.timeframe = params.timeframe;
  }
  const { data } = await axios.get<AnalysisHistoryRecord[]>(`${API_BASE}/history/analysis`, {
    params: query,
  });
  return data;
}
