import asyncio
from asyncio.log import logger
import json
from aiohttp import web
import jwt
from decouple import config
from tortoise import Tortoise

from db_config import TORTOISE_CONFIG
from models import TestCase, ExecutionTestCase, ContestRegistration, Submission, UserStats, Problem, Language

SECRET_KEY = config("SECRET_KEY")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as e:
        logger.warning(f"Token xatosi: {str(e)}")
        return None


# ─── REAL-TIME MANAGER (TRAFIK TEJOVCHI KESH BILAN) ───
class ConnectionManager:
    def __init__(self):
        self.active_connections = {}
        self.rooms = {"global_leaderboard": set(), "contests_list": set()}
        self.global_leaderboard_cache = []

    async def update_global_cache(self):
        """Ma'lumotlar bazasiga og'irlik tushirmaslik uchun keshni yangilash"""
        top_stats = await UserStats.filter(user__is_active=True)\
                                   .order_by("-xp")\
                                   .limit(100)\
                                   .prefetch_related("user")
        
        new_cache = []
        for rank, stat in enumerate(top_stats, start=1):
            user = stat.user
            if user.username:
                display_name = user.username
            else:
                display_name = f"{user.full_name or 'User'}#{user.telegram_id}"
                
            new_cache.append({
                "rank": rank,
                "username": display_name,
                "ball": stat.xp,
                "solved": stat.total_solved,
                "total_problems": 512,
                "contests": getattr(user, 'total_contests', 0),
                "streak": stat.current_streak
            })
        self.global_leaderboard_cache = new_cache

    async def register(self, ws, user_data: dict, room: str) -> bool:
        telegram_id = user_data.get("telegram_id")
        opened_tabs = sum(1 for c in self.active_connections.values() if c["telegram_id"] == telegram_id)
        if opened_tabs >= 3:
            return False

        self.active_connections[ws] = {
            "telegram_id": telegram_id,
            "username": user_data.get("username"),
            "room": room
        }
        if room not in self.rooms:
            self.rooms[room] = set()
        self.rooms[room].add(ws)
        await self.broadcast_online_count(room)
        return True
    
    async def unregister(self, ws):
        if ws in self.active_connections:
            room = self.active_connections[ws]["room"]
            self.active_connections.pop(ws, None)
            if room in self.rooms and ws in self.rooms[room]:
                self.rooms[room].remove(ws)
                if not self.rooms[room] and room not in ["global_leaderboard", "contests_list"]:
                    self.rooms.pop(room, None)
                else:
                    await self.broadcast_online_count(room)

    async def broadcast_to_room(self, room: str, message: dict):
        if room in self.rooms:
            disconnected_ws = []
            payload = json.dumps(message)
            for ws in self.rooms[room]:
                try:
                    await ws.send_str(payload)
                except Exception:
                    disconnected_ws.append(ws)
            for ws in disconnected_ws:
                await self.unregister(ws)

    async def broadcast_online_count(self, room: str):
        count = len(self.rooms.get(room, set()))
        await self.broadcast_to_room(room, {"t": "online_count", "count": count})


manager = ConnectionManager()


# ─── BAZADAN MUSOBAQA REYTINGINI OLISH ───
async def get_contest_leaderboard(contest_id: int) -> dict:
    registrations = await ContestRegistration.filter(
        contest_id=contest_id, is_active=True
    ).order_by("rank", "-total_score").limit(50).prefetch_related("user")
    
    leaderboard = []
    for reg in registrations:
        leaderboard.append({
            "rank": reg.rank,
            "score": reg.total_score,
            "username": reg.user.username or f"User#{reg.user.telegram_id}",
        })
    return {"t": "update_contest_leader", "data": {"contest_id": contest_id, "leaderboard": leaderboard}}


# ─── WEBSOCKET HANDLER ───
async def ws_handler(request: web.Request):
    token = request.query.get('token')
    room = request.query.get('room', 'global_leaderboard')
    user_data = decode_token(token) if token else None
    
    if not user_data:
        return web.Response(status=401, text="Yaroqsiz token")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    success = await manager.register(ws, user_data, room)
    if not success:
        await ws.close(code=4003, message=b"Too many open tabs")
        return ws

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    # 📥 Kelgan matnni JSON ko'rinishida pars qilamiz
                    data = json.loads(msg.data)
                    event = data.get("t")  # Siz so'ragan event turi ('t' kaliti orqali)
                    payload = data.get("data", {}) # Qo'shimcha argumentlar (masalan, code, problem_id va h.k.)
                    
                    # 1. PING-PONG logikasi
                    if event == "ping":
                        await ws.send_json({"t": "pong"})
                    
                    # 2. update_leader EVENTI (Foydalanuvchi sahifaga kirganda birinchi marta so'raydi)
                    elif event == "update_leader":
                        if not manager.global_leaderboard_cache:
                            await manager.update_global_cache()
                        
                        await ws.send_json({
                            "t": "update_leader",
                            "data": manager.global_leaderboard_cache
                        })
                    
                    # 3. update_contest_leader EVENTI (Musobaqa reytingini olish)
                    elif event == "update_contest_leader":
                        contest_id = payload.get("contest_id")
                        if contest_id:
                            contest_lb = await get_contest_leaderboard(int(contest_id))
                            await ws.send_json(contest_lb)
                        else:
                            await ws.send_json({"t": "error", "data": {"message": "contest_id majburiy"}})

                    # 4. run EVENTI (Kodni shunchaki test kiritib tekshirib ko'rish)
                    elif event == "run":
                        problem_id = payload.get("problem_id")
                        code = payload.get("code")
                        language_id = payload.get("language_id")
                        input_data = payload.get("input_data") # Foydalanuvchi o'zi qo'lda kiritgan test inputi

                        # TODO: Bu yerda siz yozadigan Go/Python tahlilchisiga (sandbox/isolate) chaqiruv bo'ladi
                        # Hozircha vaqtincha mock response:
                        await ws.send_json({
                            "t": "run",
                            "data": {
                                "status": "success",
                                "output": "Siz yuborgan kod muvaffaqiyatli run bo'ldi (Mock)",
                                "time_used": 45,
                                "memory_used": 12
                            }
                        })

                    elif event == "submit":
                        problem_id = payload.get("problem_id")
                        code = payload.get("code")
                        language_id = payload.get("language_id")
                        contest_id = payload.get("contest_id", None)  # Musobaqa bo'lmasa None

                        if not problem_id or not code or not language_id:
                            await ws.send_json({"t": "error", "data": {"message": "Malumotlar to'liq emas"}})
                            continue

                        # ─── BAZADAN KERAKLI MA'LUMOTLARNI YUKLASH ───
                        try:
                            problem = await Problem.get_or_none(id=problem_id)
                            language = await Language.get_or_none(id=language_id)
                            
                            if not problem or not language:
                                await ws.send_json({"t": "error", "data": {"message": "Masala yoki til topilmadi"}})
                                continue

                            # Top va Bottom kod shablonlarini olish
                            exec_code = await ExecutionTestCase.get_or_none(problem_id=problem_id, language_id=language_id)
                            
                            # To'liq bajariladigan kod konstruksiyasi (\n to'g'rilandi)
                            top_part = exec_code.top_code if exec_code and exec_code.top_code else ""
                            bottom_part = exec_code.bottom_code if exec_code and exec_code.bottom_code else ""
                            source_code = f"{top_part}\n{code}\n{bottom_part}"

                            # ⚡ TUZATILDI: Barcha test caselarni filter orqali list ko'rinishida olish
                            test_cases = await TestCase.filter(problem_id=problem_id)
                            if test_cases:
                                pass
                            else:
                                pass

                        except Exception as e:
                            logger.error(f"Bazadan ma'lumot olishda xato: {str(e)}")
                            await ws.send_json({"t": "error", "data": {"message": "Tizim xatosi yuz berdi"}})
                            continue

                        # ─── NAVBATGA QO'SHILGANLIGI HAQIDA REPSONSE ───
                        await ws.send_json({
                            "t": "submit",
                            "data": {
                                "status": "checking",
                                "message": "Kodingiz navbatga qo'shildi va test qilinmoqda..."
                            }
                        })
                        
                except json.JSONDecodeError:
                    await ws.send_json({"t": "error", "data": {"message": "Xabar formati JSON bo'lishi shart"}})
    finally:    
        await manager.unregister(ws)
    return ws


# ─── 🚀 BACKEND SIGNAL: REYTINGDA YANGI O'ZGARISH BULGANDA GLOBAL TARQATISH ───
async def notify_user_score_changed(telegram_id: int):
    """
    Global reytingda biron bir o'zgarish bo'lganda (masalan, kimdir masala yechsa)
    xonadagi hamma foydalanuvchiga 'update_leader' eventi bilan yangi ma'lumotlarni yuboradi.
    """
    await manager.update_global_cache()
    
    # Siz aytgandek yangi o'zgarish bo'lganda global update_leader response shakli:
    await manager.broadcast_to_room("global_leaderboard", {
        "t": "update_leader",
        "data": manager.global_leaderboard_cache
    })


async def init_orm(app: web.Application):
    await Tortoise.init(config=TORTOISE_CONFIG)
    await manager.update_global_cache()
    print("🚀 Tortoise-ORM muvaffaqiyatli ishga tushdi va kesh tayyorlandi.")


async def close_orm(app: web.Application):
    await Tortoise.close_connections()
    print("🛑 Tortoise-ORM ulanishlari xavfsiz yopildi.")


def create_app():
    app = web.Application()
    app.router.add_get('/ws', ws_handler)
    app.on_startup.append(init_orm)
    app.on_cleanup.append(close_orm)
    return app


if __name__ == '__main__':
    app = create_app()
    web.run_app(app, host='127.0.0.1', port=8080)