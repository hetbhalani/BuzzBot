import boto3
import datetime
import json
import os
from botocore.exceptions import ClientError
from pipelines.tavily_search_tool import tavily_search

BUCKET_NAME = os.environ.get("BUCKET_NAME")

s3 = boto3.client("s3")

def date_to_key(date: datetime.date):
    try:
        return f"data/{date.year}/{date.month:02d}/{date.day:02d}.json"
    except Exception as e:
        print(e)
        return ""

def s3_post(state):
    try:
        today = datetime.date.today()
        key = date_to_key(today)

        data = state.get("top_news", [])

        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(data),
            ContentType="application/json"
        )

        print(f"stored {len(data)} articles to S3")

        return {
            "articles_stored": len(data)
        }
    except Exception as e:
        print(e)
        return {
            "articles_stored": 0
        }


def s3_get():
    try:
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
    except Exception as e:
        print(e)
        return []