import datetime
from typing import Optional, TypedDict
from langgraph.graph import END, START, StateGraph
from bot.telegram_bot import select_articles_via_telegram, review_post_via_telegram
from pipelines.tavily_search_tool import tavily_search
from storage.s3_client import s3_post, s3_get
from pipelines.news_ranker import news_ranker
from pipelines.draft_post import draft_post
from pipelines.post_the_post import post_the_post


class State(TypedDict):
    today: str

class DailyPipelineState(TypedDict):
    raw_news: list[dict]
    number_of_news: Optional[int]
    top_news: list[dict]
    errors: list[str]


class WeeklyPipelineState(TypedDict):
    today: str
    all_news: list[dict]
    top_news: list[dict]
    final_news: list[dict]
    draft_post: Optional[str]
    post_word_count: Optional[int]
    approve_status: Optional[str]
    user_prompt: Optional[str]
    edited_response: Optional[str]
    final_post: Optional[str]
    post_status: Optional[dict]


def chose_the_graph(state: State):
    pass

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

def weekly_s3_get(state: WeeklyPipelineState):
    all_news = s3_get()
    
    return{"all_news": all_news}

def deduplicate_news(state: WeeklyPipelineState):
    seen_urls = set()
    unique=[]
    
    for news in state["all_news"]:
        url = news.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(news)
            
    return {"all_news": unique}


def rank_articals(state: WeeklyPipelineState):
    top_10 = news_ranker(state)

    return {"top_news": top_10}

def final_selection(state: WeeklyPipelineState):
    final_news = select_articles_via_telegram(articles=state["top_news"], mode="weekly")

    return {"final_news": final_news}

def make_linkedin_post(state: WeeklyPipelineState):
    draft = draft_post(state)

    return {"draft_post": draft}

def review_post(state: WeeklyPipelineState):
    updated_state = review_post_via_telegram(state)

    approve_status = updated_state.get("approve_status")

    if approve_status == "post":
        final_post = updated_state["draft_post"] # original draft as it is
    else:
        final_post = updated_state.get("edited_response", updated_state["draft_post"])  # LLM or manual edit

    return {**updated_state, "final_post": final_post}

def post_to_linkedin(state: WeeklyPipelineState):
    result = post_the_post(state["final_post"])
    return {"post_status": result}

# Main Workflow
graph = StateGraph(State)


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

# Weekly workflow
weeklyGraph = StateGraph(WeeklyPipelineState)

weeklyGraph.add_node('weekly_s3_get', weekly_s3_get)
weeklyGraph.add_node('deduplicate_news', deduplicate_news)
weeklyGraph.add_node('rank_articals', rank_articals)
weeklyGraph.add_node('final_selection',final_selection)
weeklyGraph.add_node('make_linkedin_post', make_linkedin_post)
weeklyGraph.add_node('review_post', review_post)
weeklyGraph.add_node('post_to_linkedin', post_to_linkedin)


weeklyGraph.add_edge(START, 'weekly_s3_get')
weeklyGraph.add_edge('weeklyGraph.add_edge','deduplicate_news')
weeklyGraph.add_edge('deduplicate_news', 'rank_articals')
weeklyGraph.add_edge('rank_articals', 'final_selection')
weeklyGraph.add_edge('final_selection', 'make_linkedin_post')
weeklyGraph.add_edge('make_linkedin_post','review_post')
weeklyGraph.add_edge('review_post', 'post_to_linkedin')
weeklyGraph.add_edge('post_to_linkedin', END)

if __name__ == "__main__":
    result = daily_workflow.invoke({})