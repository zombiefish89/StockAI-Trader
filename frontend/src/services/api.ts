import axios from "axios";
import type { StockAIReport } from "../types/report";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export async function analyzeOne(ticker: string, timeframe = "1d"): Promise<StockAIReport> {
  const { data } = await axios.post<StockAIReport>(`${API_BASE}/analyze`, {
    ticker,
    timeframe,
  });
  return data;
}
