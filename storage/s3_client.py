import boto3
import datetime
import json
import os
from botocore.exceptions import ClientError
from pipelines.tavily_search_tool import tavily_search
from bot.telegram_bot import select_articles_via_telegram

BUCKET_NAME = os.environ.get("BUCKET_NAME")

s3 = boto3.client("s3")

def date_to_key(date: datetime.date):
    return f"data/{date.year}/{date.month:02d}/{date.day:02d}.json"

def s3_post():
    today = datetime.date.today()
    key = date_to_key(today)


    data = tavily_search.invoke({"query": "", "days_back": 1})
    selected_articles = select_articles_via_telegram(data)

    # print("=======================")
    # print(data)    
    # print(type(data))

    data = selected_articles
    
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=json.dumps(data),
        ContentType="application/json"
    )
    
    return {
        "s3_key": key,
        "articles_stored": len(data),
        "top_titles": [a.get("title", "Untitled") for a in data[:3]],
    }


def s3_get():
    all_articles = []
    today = datetime.date.today()
    
    
    for i in range(7):
        date = today - datetime.timedelta(days=i)
        key = date_to_key(date)
        
        try:
            response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
            content = response["Body"].read().decode("utf-8")
            day_articles = json.loads(content)
            all_articles.extend(day_articles)
            
        except ClientError as e:
            print(e)
    
    return all_articles