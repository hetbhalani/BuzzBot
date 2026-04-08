import datetime
from typing import Optional, TypedDict
from langgraph.graph import END, START, StateGraph
from bot.telegram_bot import select_articles_via_telegram
from pipelines.tavily_search_tool import tavily_search
from storage.s3_client import s3_post


class DailyPipelineState(TypedDict):
    raw_news: list[dict]
    number_of_news: Optional[int]
    top_news: list[dict]
    errors: list[str]


class WeeklyPipelineState(TypedDict):
    today: str
    all_news: list[dict]
    top_news: list[dict]
    draft_post: Optional[str]
    post_word_count: Optional[int]
    approve_status: Optional[str]
    user_prompt: Optional[str]
    edited_response: Optional[str]


def daily_tavily_search(state: DailyPipelineState):
    try:
        raw_news = tavily_search.invoke({"query": "", "days_back": 1})
        return {
            "raw_news": raw_news,
        }
    except Exception as e:
        print(e)
        return {"errors": [str(e)]}

def daily_telegram_bot(state: DailyPipelineState):
    try:
        selected_articles = select_articles_via_telegram(state["raw_news"])
        return {"top_news": selected_articles}
    except Exception as e:
        print(e)
        return {"errors": [str(e)]}
    
def daily_s3_post(state: DailyPipelineState):
    try:
        result = s3_post(state)
        return {"number_of_news": result["articles_stored"]}
    except Exception as e:
        print(e)
        return {"errors": [str(e)]}

# Daily grpaph
dailyGraph = StateGraph(DailyPipelineState)

dailyGraph.add_node('daily_tavily_search', daily_tavily_search)
dailyGraph.add_node('daily_telegram_bot', daily_telegram_bot)
dailyGraph.add_node('daily_s3_post', daily_s3_post)

dailyGraph.add_edge(START, 'daily_tavily_search')
dailyGraph.add_edge('daily_tavily_search', 'daily_telegram_bot')
dailyGraph.add_edge('daily_telegram_bot', 'daily_s3_post')
dailyGraph.add_edge('daily_s3_post', END)

daily_workflow = dailyGraph.compile()


if __name__ == "__main__":
    result = daily_workflow.invoke({})