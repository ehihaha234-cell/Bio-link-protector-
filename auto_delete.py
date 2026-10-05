from telegram.error import TelegramError
from database import db
from config import DEFAULT_DELETE_SECONDS, MAX_DELETE_SECONDS

async def schedule_delete(context, message):
    seconds = await db.get_delete_seconds(message.chat_id, DEFAULT_DELETE_SECONDS)
    if seconds <= 0:
        return
    seconds = min(seconds, MAX_DELETE_SECONDS)
    context.job_queue.run_once(
        _delete_job,
        when=seconds,
        data={"chat_id": message.chat_id, "message_id": message.message_id},
        name=f"delete:{message.chat_id}:{message.message_id}",
    )

async def _delete_job(context):
    data = context.job.data
    try:
        await context.bot.delete_message(data["chat_id"], data["message_id"])
    except TelegramError:
        pass
