import datetime
import os
from typing import Optional, TypedDict
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt, Command
from langgraph.checkpoint.redis import RedisSaver
from bot.telegram_bot import review_post_via_telegram, send_selection_prompt, save_active_session
from pipelines.tavily_search_tool import tavily_search
from storage.s3_client import s3_post, s3_get
from pipelines.news_ranker import news_ranker
from pipelines.draft_post import draft_post
from pipelines.post_the_post import post_the_post


class MasterState(TypedDict, total=False):
    today: str
    raw_news: list[dict]
    number_of_news: Optional[int]
    top_news: list[dict]
    errors: list[str]
    all_news: list[dict]
    final_news: list[dict]
    draft_post: Optional[str]
    post_word_count: Optional[int]
    approve_status: Optional[str]
    user_prompt: Optional[str]
    edited_response: Optional[str]
    final_post: Optional[str]
    post_status: Optional[dict]
    retry_count: int


def daily_tavily_search(state: MasterState):
    try:
        raw_news = tavily_search.invoke({"query": "", "days_back": 1})
        return {
            "raw_news": raw_news,
        }
    except Exception as e:
        print(e)
        return {"errors": [str(e)]}

def daily_send_prompt(state: MasterState, config: RunnableConfig):
    thread_id = config["configurable"]["thread_id"]
    save_active_session("daily", thread_id)
    send_selection_prompt(state.get("raw_news", []), mode="daily")
    return {}

def daily_wait_for_selection(state: MasterState):
    selected = interrupt("waiting_for_daily_selection")
    return {"top_news": selected}
    
def daily_s3_post(state: MasterState):
    try:
        result = s3_post(state)
        return {"number_of_news": result.get("articles_stored", 0)}
    except Exception as e:
        print(e)
        return {"errors": [str(e)]}

def weekly_s3_get(state: MasterState):
    all_news = s3_get()
    
    return{"all_news": all_news}

def deduplicate_news(state: MasterState):
    seen_urls = set()
    unique=[]
    
    for news in state.get("all_news", []):
        url = news.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(news)
            
    return {"all_news": unique}


def rank_articals(state: MasterState):
    top_10 = news_ranker(state)

    return {"top_news": top_10}

def weekly_send_prompt(state: MasterState, config: RunnableConfig):
    thread_id = config["configurable"]["thread_id"]
    save_active_session("weekly", thread_id)
    send_selection_prompt(state.get("top_news", []), mode="weekly")
    return {}

def weekly_wait_for_selection(state: MasterState):
    selected = interrupt("waiting_for_weekly_selection")
    return {"final_news": selected}

def make_linkedin_post(state: MasterState):
    draft = draft_post(state)

    return {"draft_post": draft}

def review_post(state: MasterState):
    updated_state = review_post_via_telegram(state)

    approve_status = updated_state.get("approve_status")

    if approve_status == "post":
        final_post = updated_state.get("draft_post") # original draft as it is
    else:
        final_post = updated_state.get("edited_response", updated_state.get("draft_post"))  # LLM or manual edit

    return {**updated_state, "final_post": final_post}

def post_to_linkedin(state: MasterState):
    result = post_the_post(state.get("final_post", ""))
    current_retry = state.get("retry_count", 0)
    return {"post_status": result, "retry_count": current_retry + 1}

def retry_linkedin_post(state: MasterState):
    status = state.get("post_status", {})
    if status.get("success") == True:
        return "END"
    elif state.get("retry_count", 0) >= 3:
        return "END"
    else:
        return "post_to_linkedin"      

# Daily graph
dailyGraph = StateGraph(MasterState)

dailyGraph.add_node('daily_send_prompt', daily_send_prompt)
dailyGraph.add_node('daily_wait_for_selection', daily_wait_for_selection)
dailyGraph.add_node('daily_s3_post', daily_s3_post)

dailyGraph.add_edge(START, 'daily_tavily_search')
dailyGraph.add_edge('daily_tavily_search', 'daily_send_prompt')
dailyGraph.add_edge('daily_send_prompt', 'daily_wait_for_selection')
dailyGraph.add_edge('daily_wait_for_selection', 'daily_s3_post')
dailyGraph.add_edge('daily_s3_post', END)

daily_workflow = dailyGraph.compile()

# Weekly workflow
weeklyGraph = StateGraph(MasterState)

weeklyGraph.add_node('weekly_s3_get', weekly_s3_get)
weeklyGraph.add_node('deduplicate_news', deduplicate_news)
weeklyGraph.add_node('rank_articals', rank_articals)
weeklyGraph.add_node('weekly_send_prompt', weekly_send_prompt)
weeklyGraph.add_node('weekly_wait_for_selection', weekly_wait_for_selection)
weeklyGraph.add_node('make_linkedin_post', make_linkedin_post)
weeklyGraph.add_node('review_post', review_post)
weeklyGraph.add_node('post_to_linkedin', post_to_linkedin)


weeklyGraph.add_edge(START, 'weekly_s3_get')
weeklyGraph.add_edge('weekly_s3_get','deduplicate_news')
weeklyGraph.add_edge('deduplicate_news', 'rank_articals')
weeklyGraph.add_edge('rank_articals', 'weekly_send_prompt')
weeklyGraph.add_edge('weekly_send_prompt', 'weekly_wait_for_selection')
weeklyGraph.add_edge('weekly_wait_for_selection', 'make_linkedin_post')
weeklyGraph.add_edge('make_linkedin_post','review_post')
weeklyGraph.add_edge('review_post', 'post_to_linkedin')
weeklyGraph.add_conditional_edges('post_to_linkedin', retry_linkedin_post,{
    "END": END,
    "post_to_linkedin": "post_to_linkedin"
})

weekly_workflow = weeklyGraph.compile()

def route_by_day(state: MasterState):
    today_str = state.get("today")
    if not today_str:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
    date_obj = datetime.datetime.strptime(today_str, "%Y-%m-%d")
    if date_obj.weekday() == 1: # tuesday
        return "weekly"
    else:
        return "daily"

# Master Graph
master_graph = StateGraph(MasterState)

master_graph.add_node('daily_subgraph', daily_workflow)
master_graph.add_node("weekly_subgraph", weekly_workflow)

master_graph.add_conditional_edges(START, route_by_day, {
    "daily": "daily_subgraph",
    "weekly": "weekly_subgraph"
})

master_graph.add_edge("daily_subgraph", END)
master_graph.add_edge("weekly_subgraph", END)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_checkpointer_ctx = RedisSaver.from_conn_string(REDIS_URL)
checkpointer = _checkpointer_ctx.__enter__()
checkpointer.setup()

master_workflow = master_graph.compile(checkpointer=checkpointer)

if __name__ == "__main__":
    pass