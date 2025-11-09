from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - optional dependency
    from pymongo import MongoClient  # type: ignore
    from pymongo.collection import Collection  # type: ignore
    from pymongo.errors import PyMongoError  # type: ignore
except ImportError:  # pragma: no cover
    MongoClient = None  # type: ignore
    Collection = None  # type: ignore
    PyMongoError = Exception  # type: ignore

from backend.app.schemas import AnalysisHistoryQuery, AnalysisHistoryRecord, StockAIReport

logger = logging.getLogger(__name__)


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class AnalysisHistoryStore:
    def __init__(self) -> None:
        self.enabled = _parse_bool(os.getenv("ANALYSIS_HISTORY_ENABLED"), default=False)
        self.mongo_uri = os.getenv("ANALYSIS_HISTORY_MONGO_URI", os.getenv("MONGO_URI", "mongodb://localhost:27017"))
        self.mongo_db = os.getenv("ANALYSIS_HISTORY_MONGO_DB", os.getenv("MONGO_DB", "stockai_history"))
        self.collection_name = os.getenv("ANALYSIS_HISTORY_COLLECTION", "analysis_history")
        self._collection: Optional[Collection] = None
        if not self.enabled:
            logger.info("Analysis history persistence disabled.")

    def _get_collection(self) -> Optional[Collection]:
        if not self.enabled or MongoClient is None:
            return None
        if self._collection is not None:
            return self._collection
        try:
            client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=2000)  # type: ignore[arg-type]
            client.admin.command("ping")
            collection = client[self.mongo_db][self.collection_name]
            collection.create_index([("ticker", 1), ("created_at", -1)])
            collection.create_index("created_at")
            self._collection = collection
        except Exception as exc:  # pragma: no cover - connection failure
            logger.warning("MongoDB not available for history store: %s", exc)
            self._collection = None
        return self._collection

    async def save(self, report: StockAIReport, context: Dict[str, Any]) -> None:
        collection = self._get_collection()
        if collection is None:
            return
        document = self._build_document(report, context)

        def _insert() -> None:
            try:
                collection.insert_one(document)
            except PyMongoError as exc:  # pragma: no cover
                logger.debug("Failed to insert history record: %s", exc)

        await asyncio.to_thread(_insert)

    def _build_document(self, report: StockAIReport, context: Dict[str, Any]) -> Dict[str, Any]:
        safe_context = json.loads(json.dumps(context, default=str)) if context else {}
        payload = report.model_dump(mode="json")
        return {
            "ticker": report.ticker,
            "timeframe": report.timeframe,
            "asOf": payload.get("asOf"),
            "report": payload,
            "context": safe_context,
            "created_at": datetime.now(timezone.utc),
        }

    async def query(self, params: AnalysisHistoryQuery) -> List[AnalysisHistoryRecord]:
        collection = self._get_collection()
        if collection is None:
            return []
        query: Dict[str, Any] = {}
        if params.ticker:
            query["ticker"] = params.ticker.upper()
        if params.timeframe:
            query["timeframe"] = params.timeframe

        def _fetch() -> List[Dict[str, Any]]:
            cursor = (
                collection.find(query)
                .sort("created_at", -1)
                .skip(params.skip)
                .limit(params.limit)
            )
            results: List[Dict[str, Any]] = []
            for doc in cursor:
                doc["_id"] = str(doc.get("_id"))
                results.append(doc)
            return results

        try:
            docs = await asyncio.to_thread(_fetch)
        except PyMongoError as exc:  # pragma: no cover
            logger.debug("Mongo history query failed: %s", exc)
            return []
        return [AnalysisHistoryRecord(**doc) for doc in docs]


history_store = AnalysisHistoryStore()
