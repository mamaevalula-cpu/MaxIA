"""1C ERP integration agent."""
import os, logging, json
from typing import Any, Optional
log = logging.getLogger(__name__)

# Standalone base — never inherits abstract BaseAgent to avoid instantiation errors
class _OneCBase:
    name = "OneCAgent"
    description = ""
    status = "idle"
    def __init__(self): pass
    def can_handle(self, text: str) -> bool:
        kw = ("1c","1с","документ","баланс","накладная","счёт","erp","проводка")
        return any(k in text.lower() for k in kw)
    def process(self, text, source="internal"): return self._route(text)
    def info(self):
        return {"name": self.name, "description": self.description, "status": self.status}
    def _route(self, text): return ""

class OneCAgent(_OneCBase):
    """Agent for interacting with 1C:Enterprise via REST API."""

    def __init__(self):
        super().__init__()
        self.name = "OneCAgent"
        self.description = "Интеграция с 1С:Предприятие — документы, баланс, запросы"
        self._url = os.getenv("1C_URL", "").rstrip("/")
        self._login = os.getenv("1C_LOGIN", "")
        self._password = os.getenv("1C_PASSWORD", "")
        self._base = os.getenv("1C_BASE", "")
        self._session = None
        log.info("OneCAgent init: url=%s", self._url or "(not configured)")

    @property
    def connected(self) -> bool:
        return bool(self._url and self._login)

    def _get_session(self):
        if self._session:
            return self._session
        try:
            import requests
            s = requests.Session()
            s.auth = (self._login, self._password)
            s.headers["Accept"] = "application/json"
            self._session = s
            return s
        except ImportError:
            return None

    def get_status(self) -> dict:
        if not self.connected:
            return {"connected": False, "url": self._url or "not configured", "error": "Not configured"}
        try:
            s = self._get_session()
            if not s:
                return {"connected": False, "error": "requests not available"}
            r = s.get(f"{self._url}/odata/standard.odata/", timeout=5)
            return {"connected": r.status_code < 400, "url": self._url, "status_code": r.status_code}
        except Exception as e:
            return {"connected": False, "url": self._url, "error": str(e)}

    def get_documents(self, doc_type: str = "ПриходнаяНакладная", limit: int = 20) -> list:
        if not self.connected:
            return []
        try:
            s = self._get_session()
            url = f"{self._url}/odata/standard.odata/Document_{doc_type}?$top={limit}&$format=json"
            r = s.get(url, timeout=10)
            data = r.json()
            items = data.get("value", data if isinstance(data, list) else [])
            return [{"type": doc_type, "number": i.get("Number",""), "date": i.get("Date",""), "sum": i.get("DocumentAmount", i.get("Sum", 0))} for i in items]
        except Exception as e:
            log.warning("get_documents error: %s", e)
            return []

    def get_balance(self) -> dict:
        if not self.connected:
            return {}
        try:
            s = self._get_session()
            url = f"{self._url}/odata/standard.odata/AccumulationRegister_Взаиморасчеты/Balance?$format=json"
            r = s.get(url, timeout=10)
            return r.json()
        except Exception as e:
            log.warning("get_balance error: %s", e)
            return {"error": str(e)}

    def query(self, query_text: str) -> str:
        """Execute an OData or raw query."""
        if not self.connected:
            return "1C не настроена"
        try:
            s = self._get_session()
            # Try as OData filter on Catalog_Номенклатура
            url = f"{self._url}/odata/standard.odata/Catalog_Номенклатура?$filter=contains(Description,'{query_text}')&$top=10&$format=json"
            r = s.get(url, timeout=10)
            data = r.json()
            items = data.get("value", [])
            if not items:
                return "Ничего не найдено"
            return json.dumps(items[:5], ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Ошибка запроса: {e}"

    def process(self, text: str, **kwargs) -> str:
        text_lower = text.lower()
        if not self.connected:
            return "1С не настроена. Укажите 1C_URL, 1C_LOGIN, 1C_PASSWORD в .env"
        if "документ" in text_lower or "document" in text_lower:
            docs = self.get_documents()
            return f"Найдено {len(docs)} документов:\n" + "\n".join(f"- {d['type']} №{d['number']} от {d['date']}" for d in docs[:5])
        if "баланс" in text_lower or "balance" in text_lower:
            b = self.get_balance()
            return f"Баланс 1С:\n{json.dumps(b, ensure_ascii=False, indent=2)[:500]}"
        if "статус" in text_lower or "status" in text_lower:
            s = self.get_status()
            return f"Статус 1С: {'✅ Подключено' if s['connected'] else '❌ Отключено'} — {s.get('url','')}"
        return self.query(text)
