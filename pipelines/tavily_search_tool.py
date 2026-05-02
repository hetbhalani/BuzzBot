from langchain.tools import tool
from dotenv import load_dotenv
from langchain_tavily import TavilySearch
import datetime
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

queries = [
    "new AI breakthrough",
    "OpenAI, Anthropic, Google DeepMind, Twitter news",
    "new AI model release",
    "new AI research paper breakthrough",
    "AI startup funding regulation"
]

def make_client(days_back: int) -> TavilySearch:
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days_back)

    end_date_str = end_date.strftime("%Y-%m-%d")
    start_date_str = start_date.strftime("%Y-%m-%d")

    return TavilySearch(
        max_results=2,
        topic="news",
        start_date=start_date_str,
        end_date=end_date_str
    )
    
def dedup(results) -> list[dict]:
    try:
        seen_urls = set()
        articles = []

        if results and isinstance(results[0], dict):
            results = [results]

        for batch in results:
            items = []
            if isinstance(batch, list):
                for i in batch:
                    if isinstance(i, dict) and "results" in i:
                        items.extend(i["results"])
                    else:
                        items.append(i)
            elif isinstance(batch, dict) and "results" in batch:
                items = batch["results"]
            else:
                items = batch

            for article in items:
                if isinstance(article, dict):
                    url = article.get("url")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        articles.append(article)

        return articles
    except Exception as e:
        print(e)
        return []

@tool
def tavily_search(query: str = "", days_back: int = 1) -> list[dict]:
    """Search for recent news articles of AI."""

    days_back = int(days_back)
    client = make_client(days_back)

    if query:
        results = client.invoke(query)
        return dedup(results)

    with ThreadPoolExecutor() as executor:
        batches = list(executor.map(client.invoke, queries))

    return dedup(batches)