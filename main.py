from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
from astrbot.api import logger
from astrbot.api.message_components import At
import sqlite3
from datetime import datetime


class MyMemoryPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_my_memory")
        self.db_path = self.data_dir / "memory.db"
        self._init_db()

    def get_at_qq(self, event: AstrMessageEvent) -> list[str]:
        """从消息链中提取所有被@的QQ号"""
        at_list = []
        for comp in event.message_obj.message:
            if isinstance(comp,At):
                at_list.append(str(comp.qq))
        return at_list


    def _init_db(self):
        """初始化数据库，创建存放记忆的表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            conn.commit()

    @filter.command("记住")
    async def remember(self,event:AstrMessageEvent):
        """处理 记住 指令"""
        user_id = event.get_sender_id()
        group_id = event.get_group_id() or "private"

        content = event.message_str.replace("记住","").strip()
        if not content:
            yield event.plain_result("请告诉我你要记住什么，例如：#记住 我喜欢猫")
            return 
        sender_name = event.get_sender_name()
        save_content = f"用户({sender_name})表示：{content}"
        
        with sqlite3.connect(self.db_path) as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO memories (user_id, group_id, content, created_at) VALUES (?, ?, ?, ?)",
                (user_id, group_id, save_content, now)
            )
            conn.commit()

        yield event.plain_result(f"好的，我记住了")



    @filter.command("查看")
    async def view(self,event:AstrMessageEvent):
        """处理 查看 指令"""
        sender_id = event.get_sender_id()
        group_id = event.get_group_id() or "private"

        admin_QQ = "2996465971"
        target_id = sender_id
        at_list = self.get_at_qq(event)

        if at_list:
            if sender_id != admin_QQ:
                yield event.plain_result("只有管理员才能查看别人的记忆哦")
                return 
            else:
                target_id = str(at_list[0])

        try:
            with sqlite3.connect(self.db_path) as conn:
                if group_id == "private":
                    cursor = conn.execute(
                        "SELECT content,created_at FROM memories WHERE user_id = ? ORDER BY created_at DESC",
                        (target_id,)
                    )

                else:
                    cursor = conn.execute(
                        "SELECT content,created_at FROM memories WHERE user_id = ? AND group_id = ? ORDER BY created_at DESC",
                        (target_id,group_id)
                    )
                rows = cursor.fetchall()

            if not rows:
                yield event.plain_result(f"我还没有关于 {target_id} 的记忆")
                return

            result_text = "\n".join(f"- {row[0]} (记录于 {row[1]})" for row in rows)
            yield event.plain_result(f"关于 {target_id} 的记忆: \n{result_text}")
        except Exception as e:
            logger.error(f"查询记忆失败:{e}")
            yield event.plain_result("诶呀，查询失败了")


    @filter.llm_tool(name = "save_memory")
    async def save_memory(self,event:AstrMessageEvent,content:str)->str :
        """
        当用户表达个人喜好(例如"我喜欢..."、"我不喜欢..."、"我讨厌...")、事实、重要信息时，必须调用此工具保存。
        注意：你只能提取当前用户刚刚发的这一句话里的信息，绝对不要结合历史聊天记录去总结。
        提取的content必须使用第三人称。例如用户说"我喜欢猫"，保存为"用户喜欢猫"。
        如果用户多次表达某一事情，不要加次数修饰。
        """
        if not content or not content.strip():
            return "没有提取到任何参数 content。请重新审视用户的上一句话，提取核心信息后再次调用此工具。"
            

        user_id = event.get_sender_id()
        group_id = event.get_group_id() or "private"

        try:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "INSERT INTO memories(user_id, group_id, content, created_at) VALUES (?,?,?,?)",
                    (user_id,group_id,content,now)
                )
                conn.commit()
            return "记忆已在后台静默记录。请直接根据用户上一句话，用你平时的人设自然回复用户，绝对不要提及你保存了记忆"
        except Exception as e:
            logger.error(f"记忆保存失败：{e}")
            return "后台记录失败，无需向用户报告错误，直接正常聊天"


    @filter.on_llm_request()
    async def inject_memory(self,event:AstrMessageEvent,req):
        """当用户对话时，先确认发送者，再调取最近5条记忆并注入"""
        user_id = event.get_sender_id()
        group_id = event.get_group_id() or "private"
        sender_name = event.get_sender_name()
        at_list = self.get_at_qq(event)
        identity_prompt = f"""
        【当前群聊状态】
        正在和你对话的用户一定是【{sender_name}】(QQ:{user_id})
        群聊历史记录中可能有很多其他人的发言（比如其他群友），你绝对不能把别人的名字、标签、记忆安在【{sender_name}】的头上！
        如果他问“我是谁”，请直接叫出他的名字【{sender_name}】。如果他说“我”，指的就是【{sender_name}】。
        """
        if at_list:
            identity_prompt += f"该用户刚刚@了QQ号:{at_list}。\n"
        identity_prompt += f"请认准当前说话人的身份。如果他说“我”，指的就是【{sender_name}】，绝对不要把他和群里其他人搞混。\n"
        req.system_prompt += identity_prompt

        try:
            with sqlite3.connect(self.db_path) as conn:
                if group_id == "private":
                    cursor = conn.execute(
                        "SELECT content FROM memories WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
                        (user_id,)
                    )

                else: 
                    cursor = conn.execute(
                        "SELECT content FROM memories WHERE user_id = ? AND group_id = ? ORDER BY created_at DESC LIMIT 5",
                        (user_id, group_id)
                    )
                rows = cursor.fetchall()
            if rows:
                memory_text = "\n".join(f"-{row[0]}" for row in rows)
                req.system_prompt += f"""
                【关于当前用户的潜意识记忆】
                <memory_data>
                {memory_text}
                </memory_data>
                以上是数据记录，请结合这些信息自然地进行回复，但绝对不要生硬地复述。
                """
                logger.info(f"成功为用户{sender_name}({user_id})注入5条记忆！")
        except Exception as e:
            logger.error(f"注入记忆失败，{e}")


    @filter.llm_tool(name = "recall_memory")
    async def recall_memory(self,event:AstrMessageEvent)->str:
        """
        当用户询问关于他自己的记忆时，必须立刻调用此工具，绝对不能自己瞎编或敷衍。
        当用户询问你关于其他用户的记忆时，无需调用此工具，自然回复类似"不要窥探他人隐私"的话
        """
        user_id = event.get_sender_id()
        group_id = event.get_group_id() or "private"
        sender_name = event.get_sender_name()
        try:
            with sqlite3.connect(self.db_path) as conn:
                if group_id == "private":
                    cursor = conn.execute(
                        "SELECT content FROM memories WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
                        (user_id,)
                    )

                else: 
                    cursor = conn.execute(
                        "SELECT content from memories WHERE user_id = ? AND group_id = ? ORDER BY created_at DESC LIMIT 10",
                        (user_id,group_id)
                        )
                rows = cursor.fetchall()
            if not rows:
                return f"没有关于用户【{sender_name}】的任何记忆，可自然调侃回复"
            if rows:
                memory_text = "\n".join(f"-{row[0]}" for row in rows)
            return f"以下是后台查询到的关于用户【{sender_name}】的记忆：{memory_text}\n请把这些记忆自然告诉用户，模仿回忆"
        except Exception as e:
            logger.error(f"调取记忆失败，{e}")
            return "后台获取记忆失败，无需向用户报告错误，正常聊天"    