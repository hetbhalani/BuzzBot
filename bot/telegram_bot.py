import os
import asyncio
import html
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from pipelines.edit_draft_post_w_prompt import edit_draft_post_w_prompt

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

import json
import redis as redis_lib
from langgraph.types import Command

def save_active_session(mode: str, thread_id: str):
    r = redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
    r.set("buzzbot:active_session", json.dumps({"mode": mode, "thread_id": thread_id}))

def send_selection_prompt(articles: list[dict], mode: str = "daily"):
    required_count = 5 if mode == "weekly" else 0
    
    def build_prompt_text():
        article_lines = []
        for i, article in enumerate(articles):
            title = article.get("title")
            final_title = title[:title.rfind("-")].strip() if title and "-" in title else title
            url = article.get("url", "")
            safe_title = html.escape(final_title)
            safe_url = html.escape(url, quote=True)
            if safe_url:
                article_lines.append(f'{i + 1}. {safe_title} - <a href="{safe_url}">Read here</a>\n')
            else:
                article_lines.append(f"{i + 1}. {safe_title}\n")
        
        if mode == "weekly":
            header = ["🏆 Weekly Top 10 Review", "", f"Please select exactly {required_count} articles to feature in the newsletter."]
        else:
            header = ["📰 Daily AI News Curator", "", "Review the stories below and tap to select the ones you want to keep."]
        
        return "\n".join(header + ["", f"📚 Total stories: {len(articles)}\n", *article_lines])

    def build_keyboard(selected_set):
        buttons = []
        for i, article in enumerate(articles):
            title = article.get("title")
            final_title = title[:title.rfind("-")].strip() if title and "-" in title else title
            preview = (final_title[:28].rstrip() + "...") if len(final_title) > 31 else final_title
            label = f"{i + 1}. {preview}  ✅" if i in selected_set else f"{i + 1}. {preview}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"toggle:{i}")])
        buttons.append([
            InlineKeyboardButton("✅ Select All", callback_data="select_all"),
            InlineKeyboardButton("🧹 Clear", callback_data="clear_all"),
        ])
        buttons.append([InlineKeyboardButton("🚀 Save & Finish", callback_data="done")])
        return InlineKeyboardMarkup(buttons)

    async def _send():
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=CHAT_ID,
            text=build_prompt_text(),
            reply_markup=build_keyboard(set()),
            parse_mode="HTML",
        )
        print(f"[Telegram] {mode} selection prompt sent")

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_send())
    loop.close()

def start_persistent_bot():
    async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        r = redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        session_data = r.get("buzzbot:active_session")
        if not session_data:
            await query.edit_message_text("No active session found.")
            return
            
        session = json.loads(session_data)
        mode = session["mode"]
        thread_id = session["thread_id"]
        config = {"configurable": {"thread_id": thread_id}}

        from workflow import master_workflow
        
        state_snapshot = master_workflow.get_state(config)
        if mode == "daily":
            articles = state_snapshot.values.get("raw_news", [])
        else:
            articles = state_snapshot.values.get("top_news", [])

        # Build keyboard inside closure to access current articles
        def build_keyboard(selected_set):
            buttons = []
            for i, article in enumerate(articles):
                title = article.get("title")
                final_title = title[:title.rfind("-")].strip() if title and "-" in title else title
                preview = (final_title[:28].rstrip() + "...") if len(final_title) > 31 else final_title
                label = f"{i + 1}. {preview}  ✅" if i in selected_set else f"{i + 1}. {preview}"
                buttons.append([InlineKeyboardButton(label, callback_data=f"toggle:{i}")])
            buttons.append([
                InlineKeyboardButton("✅ Select All", callback_data="select_all"),
                InlineKeyboardButton("🧹 Clear", callback_data="clear_all"),
            ])
            buttons.append([InlineKeyboardButton("🚀 Save & Finish", callback_data="done")])
            return InlineKeyboardMarkup(buttons)

        selected = context.user_data.get("selected", set())

        if query.data == "done":
            chosen = [articles[i] for i in sorted(selected)]
            context.user_data["selected"] = set() 
            
            await query.edit_message_text(f"✅ Saved {len(chosen)} articles. Resuming workflow...")
            if mode == "weekly":
                context.application.stop_running()
                
            master_workflow.invoke(Command(resume=chosen), config=config)
            return

        if query.data == "select_all":
            selected.update(range(len(articles)))
        elif query.data == "clear_all":
            selected.clear()
        elif query.data.startswith("toggle:"):
            idx = int(query.data.split(":")[1])
            if idx in selected:
                selected.remove(idx)
            else:
                selected.add(idx)

        context.user_data["selected"] = selected
        await query.edit_message_reply_markup(reply_markup=build_keyboard(selected))

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(handle_button))
    print("[PersistentBot] Polling for interactions...")
    app.run_polling()



WAITING_FOR_PROMPT = 1  # bot is waiting for the user to type a prompt
WAITING_FOR_EDIT = 2    # bot is waiting for the user to send back the edited post
WAITING_FOR_EDIT_CONFIRM = 3  # bot is waiting for the user to confirm the edit

# Review the draft post and decide the next move
def review_post_via_telegram(state: dict) -> dict:

    draft = state["draft_post"]
    result: dict = {}     

    def build_review_text() -> str:
        return (
            "📝 <b>Review Your Draft LinkedIn Post</b>\n\n"
            f"{html.escape(draft)}\n\n"
            "Choose an action below:"
        )

    def build_review_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Reprompt LLM", callback_data="prompt_llm"),
                InlineKeyboardButton("✏️ Edit Post",    callback_data="edit_post"),
            ],
            [
                InlineKeyboardButton("🚀 Post", callback_data="post"),
            ],
        ])

    async def send_draft(app: Application):
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=build_review_text(),
            reply_markup=build_review_keyboard(),
            parse_mode="HTML",
        )
        print("Draft sent to telegram")

    async def handle_action_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()

        if query.data == "prompt_llm":
            await query.edit_message_reply_markup(reply_markup=None) # remove buttons
            await query.message.reply_text(
                "✍️ Please type your prompt / instructions for the LLM and send it as a message:"
            )
            # move to the next state
            return WAITING_FOR_PROMPT

        if query.data == "edit_post":
            await query.edit_message_reply_markup(reply_markup=None)

            await query.message.reply_text(
                "✏️ <b>Here is your draft post.</b> Long-press to copy it, make your edits, and send it back as a message:",
                parse_mode="HTML",
            )
            await query.message.reply_text(draft)
            return WAITING_FOR_EDIT

        if query.data == "post":
            await query.edit_message_text("✅ Post approved! Proceeding to publish...")
            result["approve_status"] = "post"
            context.application.stop_running()
            return ConversationHandler.END

    async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_prompt = update.message.text.strip()

        await update.message.reply_text(
            f"⚙️ Got it! Sending your prompt to the LLM...\n\n"
            f"<i>Prompt: {html.escape(user_prompt)}</i>",
            parse_mode="HTML",
        )

        # call the editing pipeline
        edited = edit_draft_post_w_prompt(
            instruction=user_prompt,
            draft_post=draft,
        )

        result["approve_status"] = "prompt_llm"
        result["user_prompt"]     = user_prompt
        result["edited_response"] = edited

        # show the edited post back to the user
        await update.message.reply_text(
            f"✅ <b>Edited Post:</b>\n\n{html.escape(edited)}",
            parse_mode="HTML",
        )

        context.application.stop_running()
        return ConversationHandler.END

    async def receive_edited_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        final_post = update.message.text.strip()

        context.user_data["pending_edited_post"] = final_post

        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm",   callback_data="confirm_edit"),
                InlineKeyboardButton("🔁 Re-edit",  callback_data="redo_edit"),
            ]
        ])

        await update.message.reply_text(
            f"📋 <b>Here is your edited post</b>\n\n{html.escape(final_post)}",
            reply_markup=confirm_keyboard,
            parse_mode="HTML",
        )
        return WAITING_FOR_EDIT_CONFIRM

    async def handle_edit_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()

        if query.data == "confirm_edit":
            final_post = context.user_data.get("pending_edited_post", "")
            result["approve_status"] = "edit_post"
            result["edited_response"] = final_post

            await query.edit_message_text(
                f"✅ <b>Saved! Here is your final post:</b>\n\n{html.escape(final_post)}",
                parse_mode="HTML",
            )
            context.application.stop_running()
            return ConversationHandler.END

        if query.data == "redo_edit":
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "✍️ No problem! Please send back the updated version of the post:"
            )
            return WAITING_FOR_EDIT


    conv_handler = ConversationHandler(
        # The conversation starts when a button is pressed
        entry_points=[CallbackQueryHandler(handle_action_button)],
        states={
            # Waiting for the user to type an LLM instruction
            WAITING_FOR_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt)
            ],
            # Waiting for the user to paste their manually edited post
            WAITING_FOR_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edited_post)
            ],
            # Waiting for the user to confirm or re-edit
            WAITING_FOR_EDIT_CONFIRM: [
                CallbackQueryHandler(handle_edit_confirmation)
            ],
        },
        fallbacks=[],
    )

    # start running the bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(send_draft)
        .build()
    )
    app.add_handler(conv_handler)

    print("Bot running...")
    app.run_polling()

    # merge result back into the original state and return
    return {**state, **result}
