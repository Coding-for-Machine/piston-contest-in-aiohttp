import json
import asyncio
from asyncio.log import logger
import aiohttp
from typing import Optional, List, Dict, Any

PISTON_BASE_URL = 'http://localhost:2000/api/v2'
TIMEOUT_SECONDS = 30

class PistonClient:
    """
    Piston API (v2) rasmiy spetsifikatsiyasi asosida ishlovchi professional Client Wrapper.
    """
    _version_cache: Dict[str, str] = {}

    def __init__(self, base_url: str = PISTON_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _ensure_session(self):
        if not self.session or self.session.closed:
            raise RuntimeError("Klass 'async with' kontekst menejeri ichida chaqirilishi shart!")

    async def get_version_for_lang(self, lang_name: str) -> str:
        self._ensure_session()
        lang_key = lang_name.lower().strip()
        
        if lang_key in self._version_cache:
            return self._version_cache[lang_key]
            
        url = f"{self.base_url}/runtimes"
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    runtimes = await response.json()
                    for runtime in runtimes:
                        if runtime.get("language") == lang_key:
                            version = runtime.get("version", "*")
                            self._version_cache[lang_key] = version
                            return version
        except Exception as e:
            logger.error(f"Runtimes olishda xatolik: {e}")
        return "*"

    async def execute(
        self, 
        language: str, 
        version: str, 
        code: str, 
        stdin: str = "", 
        args: List[str] = None,
        time_limit_ms: int = 2000,
        memory_limit_mb: int = 256
    ) -> Dict[str, Any]:
        """
        Dinamik koeffitsiyentlar va rasmiy xavfsizlik limitlari bilan kodni Piston API orqali ishga tushiradi.
        """
        self._ensure_session()
        url = f"{self.base_url}/execute"
        lang_key = language.lower().strip()
        
        # Tillar bo'yicha limitlarni hisoblash
        multipliers = LANGUAGE_LIMIT_MULTIPLIERS.get(lang_key, {"time": 1.0, "memory": 1.0})
        final_time_limit_ms = int(time_limit_ms * multipliers["time"])
        final_memory_limit_bytes = int(memory_limit_mb * multipliers["memory"] * 1024 * 1024)

        # ⚙️ Kompilyatsiya va xavfsizlik cheklovlari
        MAX_COMPILE_TIMEOUT_MS = 10000  # Kompilyatsiya uchun max 10 soniya
        MAX_COMPILE_MEMORY_BYTES = 512 * 1024 * 1024  # Kompilyator uchun max 512 MB

        # 📋 PISTON API (v2) RASMIY HUJJATIDAGI TO'LIQ PAYLOAD
        payload = {
            "language": lang_key,
            "version": version,
            "files": [{"content": code}],
            "stdin": stdin,
            "args": args or [],
            
            # Kompilyatsiya bosqichi cheklovlari
            "compile_timeout": MAX_COMPILE_TIMEOUT_MS,
            "compile_cpu_time": MAX_COMPILE_TIMEOUT_MS,
            "compile_memory_limit": MAX_COMPILE_MEMORY_BYTES,
            
            # Ishga tushirish (Run) bosqichi cheklovlari
            "run_timeout": final_time_limit_ms,
            "run_cpu_time": final_time_limit_ms,
            "run_memory_limit": final_memory_limit_bytes
        }

        try:
            async with self.session.post(url, json=payload) as response:
                if response.status not in [200, 201]:
                    error_text = await response.text()
                    raise Exception(f"API Error {response.status}: {error_text}")
                return await response.json()
        except Exception as e:
            logger.error(f"Kodni bajarishda xatolik yuz berdi: {e}")
            # Xatolik yuz berganda xavfsiz va mos struktura qaytaramiz
            return {"run": {"stdout": "", "stderr": str(e), "code": -1, "status": "XX"}}
