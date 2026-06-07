import json
import asyncio
from asyncio.log import logger
import aiohttp
from typing import Optional, List, Dict, Any

from app.models import Problem

PISTON_BASE_URL = 'http://localhost:2000/api/v2'
TIMEOUT_SECONDS = 30

# Tillarga mos dinamik koeffitsiyentlar (Multiplier)
# Standart muammo limitlarini har bir tilning xususiyatiga ko'ra foizga/barobarga oshiradi
LANGUAGE_LIMIT_MULTIPLIERS = {
    "python": {"time": 3.0, "memory": 2.0},      # Python biroz sekinroq va RAM talab qiladi
    "javascript": {"time": 2.0, "memory": 1.5},  # NodeJS muhiti uchun
    "java": {"time": 2.0, "memory": 3.0},        # Java JVM sababli ko'p RAM so'raydi
    "cpp": {"time": 1.0, "memory": 1.0},         # C++ o'zgarishsiz standart limitda qoladi
    "c": {"time": 1.0, "memory": 1.0},
}

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

client = PistonClient()

async def run_code(
    language: str,
    source_code: str,
    test_cases: List[Dict[str, str]],  # [{"input": "2 3", "expected": "5"}]
    time_limit_ms: int = 2000,
    memory_limit_mb: int = 256
) -> Dict[str, Any]:
    
    lang_name = language.lower().strip()
    
    # 1. PistonClient sessiyasini va til versiyasini ochib olamiz
    async with client as p_client:
        version = await p_client.get_version_for_lang(lang_name)
        
        # Har bitta test keysni parallel yurgizadigan ichki funksiya
        async def single_test(case_id: int, case_dict: Dict[str, str]):
            input_txt = case_dict.get("input", "")
            expected_txt = case_dict.get("expected", "").strip()
            
            # Siz chaqirgan execute metodi
            res = await p_client.execute(
                language=lang_name,
                version=version,
                code=source_code,
                stdin=input_txt,
                time_limit_ms=time_limit_ms,
                memory_limit_mb=memory_limit_mb
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

            # Rasmiy ikki harfli status kodlari bo'yicha filtrlar
            if piston_status == "TO":
                return {"case_id": case_id, "status": "Time Limit Exceeded (TLE)"}
            if piston_status == "OL":
                return {"case_id": case_id, "status": "Output Limit Exceeded (OLE)"}
            if piston_status == "RE" or exit_code != 0:
                if signal == "SIGSEGV" or "memory" in stderr.lower():
                    return {"case_id": case_id, "status": "Memory Limit Exceeded (MLE)"}
                return {"case_id": case_id, "status": "Runtime Error (RE)", "details": stderr}

            # Chiqish ma'lumotini kutilgan javob bilan solishtirish
            if stdout == expected_txt:
                return {"case_id": case_id, "status": "Passed"}
            return {"case_id": case_id, "status": "Wrong Answer (WA)", "got": stdout, "expected": expected_txt}

        # 🚀 SIZNING KODINGIZNING DAVOMI:
        # Test keyslarni aylanib chiqib, asinxron vazifalar (tasks) ro'yxatini tuzamiz
        tasks = []
        for idx, case in enumerate(test_cases, start=1):
            # Har bitta testni task ko'rinishida qo'shib chiqamiz
            task = single_test(idx, case)
            tasks.append(task)
            
        # Barcha testlarni parallel ravishda fonda Piston-ga otamiz (Maksimal tezlik ⚡)
        pipeline_results = await asyncio.gather(*tasks)

    # Yakuniy Accepted yoki Failed holatlarini hisoblash
    passed_count = sum(1 for r in pipeline_results if r["status"] == "Passed")
    is_all_passed = passed_count == len(test_cases)
    
    # LeetCode uslubida eng birinchi xato qilgan test holatini olish
    failed_case = next((r for r in pipeline_results if r["status"] != "Passed"), None)
    final_status = "Accepted" if is_all_passed else (failed_case["status"] if failed_case else "Rejected")

    return {
        "status": final_status,
        "passed_tests": f"{passed_count}/{len(test_cases)}",
        "results": pipeline_results
    }


import asyncio
from typing import List, Dict, Any
import aiohttp

# PistonClient va LANGUAGE_LIMIT_MULTIPLIERS tepada mavjud deb hisoblaymiz
client = PistonClient()

async def run_code(
    language: str,
    source_code: str,
    test_cases: List[Dict[str, str]],  # [{"input": "2 3", "expected": "5"}]
    time_limit_ms: int = 2000,
    memory_limit_mb: int = 256
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
                stdin=input_txt,
                time_limit_ms=time_limit_ms,
                memory_limit_mb=memory_limit_mb
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

            # Rasmiy ikki harfli status kodlari bo'yicha filtrlar
            if piston_status == "TO":
                return {"case_id": case_id, "status": "Time Limit Exceeded (TLE)"}
            if piston_status == "OL":
                return {"case_id": case_id, "status": "Output Limit Exceeded (OLE)"}
            if piston_status == "RE" or exit_code != 0:
                if signal == "SIGSEGV" or "memory" in stderr.lower():
                    return {"case_id": case_id, "status": "Memory Limit Exceeded (MLE)"}
                return {"case_id": case_id, "status": "Runtime Error (RE)", "details": stderr}

            # Chiqish ma'lumotini kutilgan javob bilan solishtirish
            if stdout == expected_txt:
                return {"case_id": case_id, "status": "Passed"}
            return {"case_id": case_id, "status": "Wrong Answer (WA)", "got": stdout, "expected": expected_txt}

        # ─── 2. SIZNING KODINGIZNING DAVOMI (PARALLEL TASKLAR) ───
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


# ─── ⚡ MINI TEST SSENARIYSI (QO'SHIB KO'RISH UCHUN) ───
async def test_main():
    code_to_test = "import sys\ninput_data = sys.stdin.read().split()\nif input_data: print(int(input_data[0]) + int(input_data[1]))"
    
    cases = [
        {"input": "2 3", "expected": "5"},
        {"input": "10 20", "expected": "30"}
    ]

    print("🚀 Piston API orqali parallel testlar yurgizilmoqda...")
    report = await run_code(language="python", source_code=code_to_test, test_cases=cases)
    
    print(f"📊 Yakuniy Status: {report['status']}")
    print(f"✅ O'tgan testlar: {report['passed_tests']}")

if __name__ == "__main__":
    asyncio.run(test_main())
