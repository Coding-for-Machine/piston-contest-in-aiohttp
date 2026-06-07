import aiohttp
import asyncio
from typing import Optional, List, Dict, Any

# Standart sozlamalar
PISTON_BASE_URL = 'http://localhost:2000/api/v2'
TIMEOUT_SECONDS = 30

class PistonClient:
    """
    Piston API (v2) bilan asinxron ishlash uchun Client Wrapper.
    """
    def __init__(self, base_url: str = PISTON_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        # aiohttp da timeout maxsus obyekt orqali beriladi
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _ensure_session(self):
        """Sessiya mavjudligini tekshirish ichki metodi"""
        if not self.session or self.session.closed:
            raise RuntimeError("Klass 'async with' kontekst menejeri ichida chaqirilishi shart!")

    async def get_runtimes(self) -> List[Dict[str, Any]]:
        """
        Piston-da mavjud barcha tillar va kompilyatorlar ro'yxatini qaytaradi.
        """
        self._ensure_session()
        url = f"{self.base_url}/runtimes"
        
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"API xatoligi: {response.status}")
                return await response.json()
        except Exception as e:
            print(f"Runtimes olishda xatolik: {e}")
            return []

    async def execute(
        self, 
        language: str, 
        version: str, 
        code: str, 
        stdin: str = "", 
        args: List[str] = None
    ) -> Dict[str, Any]:
        """
        Berilgan kodni Piston API orqali ishga tushiradi va natijani qaytaradi.
        
        :param language: Dasturlash tili (masalan: 'python', 'javascript', 'cpp')
        :param version: Til versiyasi (get_runtimes() dan olingan aniq versiya yoki '*')
        :param code: Ijro etilishi kerak bo'lgan manba kodi (source code)
        :param stdin: Kodga yuboriladigan standart kirish ma'lumotlari
        :param args: Buyruqlar satri argumentlari (CLI arguments)
        """
        self._ensure_session()
        url = f"{self.base_url}/execute"
        
        # Piston API talab qiladigan JSON tana tuzilishi (Payload)
        payload = {
            "language": language,
            "version": version,
            "files": [
                {
                    "content": code
                }
            ],
            "stdin": stdin,
            "args": args or []
        }

        try:
            async with self.session.post(url, json=payload) as response:
                if response.status not in [200, 201]:
                    error_text = await response.text()
                    raise Exception(f"Kod bajarilmadi (Status: {response.status}): {error_text}")
                return await response.json()
        except Exception as e:
            print(f"Kodni bajarishda xatolik yuz berdi: {e}")
            return {"run": {"stdout": "", "stderr": str(e), "code": -1, "signal": None}}


import asyncio
from piston import PistonClient # Boyagi faylingizdan klassni import qilamiz

# 1. Leetcode uslubidagi masala sharti: Ikki sonni qo'shish (A + B)
# Foydalanuvchi yozgan algoritm kodi
user_code = """
import sys

def solve():
    # Standart kirishdan barcha qatorlarni o'qiymiz
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    a = int(input_data[0])
    b = int(input_data[1])
    
    # Natijani chop etamiz
    print(a + b)

if __name__ == "__main__":
    solve()
"""

# 2. Leetcode test-keyslari (Input va kutilayotgan Output juftliklari)
test_cases = [
    {"input": "2 3", "expected": "5"},
    {"input": "10 -5", "expected": "5"},
    {"input": "0 0", "expected": "0"},
    {"input": "100 200", "expected": "300"},
    {"input": "99 1", "expected": "100"}
]

async def run_single_test(client, version, case_id, input_data, expected_output):
    """Bitta test-keysni Piston-ga yuborish va tekshirish funksiyasi"""
    result = await client.execute(
        language="python",
        version=version,
        code=user_code,
        stdin=input_data
    )
    
    run_info = result.get("run", {})
    stdout = run_info.get("stdout", "").strip()
    stderr = run_info.get("stderr", "").strip()
    exit_code = run_info.get("code")
    
    # Leetcode mantiqiy tekshiruvi (Validation)
    if exit_code != 0:
        return {"case": case_id, "status": "Runtime Error (RE)", "details": stderr}
    
    if stdout == expected_output:
        return {"case": case_id, "status": "Accepted (AC)", "input": input_data, "output": stdout}
    else:
        return {
            "case": case_id, 
            "status": "Wrong Answer (WA)", 
            "input": input_data, 
            "expected": expected_output, 
            "got": stdout
        }

async def main():
    async with PistonClient() as client:
        # Avval serverdagi Python versiyasini aniqlaymiz
        runtimes = await client.get_runtimes()
        python_version = "3.12.0" # Default sifatida sizda bor versiya
        for runtime in runtimes:
            if runtime.get("language") == "python":
                python_version = runtime.get("version")
                break
                
        print(f"Siz yuborgan kod {len(test_cases)} ta test yordamida tekshirilmoqda...\n")
        
        # Asinxron Task-lar ro'yxatini shakllantiramiz
        tasks = []
        for idx, case in enumerate(test_cases, 1):
            task = run_single_test(
                client, 
                python_version, 
                idx, 
                case["input"], 
                case["expected"]
            )
            tasks.append(task)
            
        # Barcha testlarni parallel ravishda Piston-ga yuboramiz (Tezlik uchun)
        results = await asyncio.gather(*tasks)
        
        # Natijalarni yakuniy hisoblash va konsolga chiqarish
        passed_tests = 0
        for res in results:
            status = res["status"]
            print(f"Test #{res['case']}: {status}")
            if status == "Accepted (AC)":
                passed_tests += 1
            elif status == "Wrong Answer (WA)":
                print(f"   -> Input: {res['input']} | Kutilgan: {res['expected']} | Olingan: {res['got']}")
            elif status == "Runtime Error (RE)":
                print(f"   -> Xatolik xabari: {res['details']}")
                
        print(f"\nNatija: {passed_tests}/{len(test_cases)} testdan o'tdi.")
        if passed_tests == len(test_cases):
            print("Status: SUCCESS (Hamma testlar muvaffaqiyatli!)")
        else:
            print("Status: FAILED")

if __name__ == "__main__":
    asyncio.run(main())

