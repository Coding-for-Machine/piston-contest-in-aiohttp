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
    ) -> Dict[str, Any]:
        """
        Kodni Piston API standart (default) xavfsizlik limitlari bilan ishga tushiradi.
        """
        self._ensure_session()
        url = f"{self.base_url}/execute"
        
        # 📋 Piston o'zining default xavfsiz vaqt cheklovlarini fonda qo'llaydi
        payload = {
            "language": language.lower().strip(),
            "version": version,
            "files": [{"content": code}],
            "stdin": stdin,
            "args": args or []
        }

        try:
            async with self.session.post(url, json=payload) as response:
                if response.status not in [200, 201]:
                    error_text = await response.text()
                    raise Exception(f"API Error {response.status}: {error_text}")
                return await response.json()
        except Exception as e:
            logger.error(f"Kodni bajarishda xatolik yuz berdi: {e}")
            return {"run": {"stdout": "", "stderr": str(e), "code": -1, "status": "XX"}}


client = PistonClient()

async def run_code(
    language: str,
    source_code: str,
    test_cases: List[Dict[str, str]]
) -> Dict[str, Any]:
    
    lang_name = language.lower().strip()
    
    # ─── 1. SESSIDANI OCHISH VA VERSIYANI ANIQLASH ───
    async with client as p_client:
        version = await p_client.get_version_for_lang(lang_name)
        
        # Bitta test keysni parallel yurgizadigan ichki funksiya
        async def single_test(case_id: int, case_dict: Dict[str, str]):
            input_txt = case_dict.get("input", "")
            expected_txt = case_dict.get("expected", "").strip()
            
            res = await p_client.execute(
                language=lang_name,
                version=version,
                code=source_code,
                stdin=input_txt
            )
            
            # Kompilyatsiya xatosini tekshirish
            compile_info = res.get("compile", {})
            if compile_info and compile_info.get("code", 0) != 0:
                return {"case_id": case_id, "status": "Compilation Error (CE)", "details": compile_info.get("output", "").strip()}

            # Ishga tushirish (run) natijalari
            run_info = res.get("run", {})
            stdout = run_info.get("stdout", "").strip()
            stderr = run_info.get("stderr", "").strip()
            exit_code = run_info.get("code")
            piston_status = run_info.get("status")  # TO, RE, OL, EL
            signal = run_info.get("signal")

            # Piston qaytargan statuslar bo'yicha filtrlar
            if piston_status == "TO":
                return {"case_id": case_id, "status": "Time Limit Exceeded (TLE)"}
            if piston_status == "OL":
                return {"case_id": case_id, "status": "Output Limit Exceeded (OLE)"}
            if piston_status == "RE" or exit_code != 0:
                if signal == "SIGSEGV" or "memory" in stderr.lower():
                    return {"case_id": case_id, "status": "Memory Limit Exceeded (MLE)"}
                return {"case_id": case_id, "status": "Runtime Error (RE)", "details": stderr}

            # Natijani kutilgan javob bilan solishtirish
            if stdout == expected_txt:
                return {"case_id": case_id, "status": "Passed"}
            return {"case_id": case_id, "status": "Wrong Answer (WA)", "got": stdout, "expected": expected_txt}

        # ─── 2. PARALLEL TASKLARNI ISHGA TUSHIRISH ───
        tasks = []
        for idx, case in enumerate(test_cases, start=1):
            task = single_test(idx, case)
            tasks.append(task)
            
        pipeline_results = await asyncio.gather(*tasks)

    # ─── 3. YAKUNIY REYTING VA STATUSNI HISOBLASH ───
    passed_count = sum(1 for r in pipeline_results if r["status"] == "Passed")
    is_all_passed = passed_count == len(test_cases)
    
    failed_case = next((r for r in pipeline_results if r["status"] != "Passed"), None)
    final_status = "Accepted" if is_all_passed else (failed_case["status"] if failed_case else "Rejected")

    return {
        "status": final_status,
        "passed_tests": f"{passed_count}/{len(test_cases)}",
        "results": pipeline_results
    }