import requests
import os
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.environ["LINKEDIN_ACCESS_TOKEN"]
PERSON_URN = os.environ["LINKEDIN_PERSON_URN"]

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0",
    "LinkedIn-Version": "202604", 
}

def post_the_post(final_post: str):
    post_body = {
        "author": PERSON_URN,
        "commentary": final_post,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        },
        "lifecycleState": "PUBLISHED",
    }

    response = requests.post(
        "https://api.linkedin.com/rest/posts",
        headers=headers,
        json=post_body
    )

    if response.status_code == 201:
        post_id = response.headers.get("x-restli-id")
        return {"success": True, "post_id": post_id, "error": None}
    else:
        return {"success": False, "post_id": None, "error": response.text}

post_the_post("Testing")