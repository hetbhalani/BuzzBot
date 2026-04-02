from langchain.tools import tool
from dotenv import load_dotenv
from langchain_tavily import TavilySearch
import datetime
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

queries = [
    "new AI model release",
    "new AI research paper breakthrough",
    "OpenAI, Anthropic, Google DeepMind, Twitter news",
    "AI startup funding regulation",
    "new AI breakthrough"
]

def make_client(days_back: int) -> TavilySearch:
    return TavilySearch(
        max_results=5,
        topic="news",
        days=days_back,
    )


@tool
def tavily_search(query: str = "", days_back: int = 1) -> list[dict]:
    """Search for recent news articles of AI."""
    
    client = make_client(days_back)

    if query:
        results = client.invoke(query)
        return results
    
    #daily pipeline
    with ThreadPoolExecutor() as executor:
        batches = list(executor.map(client.invoke, queries))
        
    # print("++++++++++++++")
    # print(batches)
    
    return batches     