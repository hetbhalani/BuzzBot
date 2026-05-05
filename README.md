<div align="center">
  <img src="imgs/banner.png" alt="BuzzBot Banner" width="100%" />

# 🤖 BuzzBot

**Production-Grade AI Newsletter Pipeline**

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)
![LangGraph](https://img.shields.io/badge/LangGraph-Agentic-FF6B35)
![Airflow](https://img.shields.io/badge/Apache_Airflow-Scheduler-017CEE)
![AWS](https://img.shields.io/badge/AWS-EC2_·_S3_·_IAM-FF9900)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED)
![Redis](https://img.shields.io/badge/Redis-Checkpointer-DC382D)

Automated News Curation • LLM Post Drafting • Telegram Approval • LinkedIn Auto-Post • Full Observability

</div>

---

## Overview

BuzzBot is a fully automated AI-powered news-to-LinkedIn pipeline. Every day it fetches AI news via Tavily, processes it through a LangGraph agent graph, and stores ranked articles on AWS S3. Every week it aggregates the best stories, drafts a polished LinkedIn post using Groq LLaMA 3.3 70B, and sends it to your phone via Telegram with interactive approval buttons. You tap **Post**, **Edit**, or **Reprompt** — and BuzzBot handles publishing.

The entire system is containerized with Docker, scheduled with Airflow, deployed on EC2 via GitHub Actions CI/CD, and fully observable through LangSmith and Langfuse.

## How It Works

**Daily Pipeline** — Airflow triggers a LangGraph subgraph that runs 5 parallel Tavily searches, deduplicates articles by URL, and sends an interactive selection list to Telegram. You pick the articles you want to keep, and they're stored on S3 as `news/YYYY-MM-DD/articles.json`. The workflow pauses via `interrupt()` with Redis checkpoint persistence — zero compute while you decide.

**Weekly Pipeline (Tuesday)** — A second subgraph reads the full week from S3, deduplicates across days, LLM-ranks articles by novelty/impact/relevance, and drafts a LinkedIn post. The draft is sent to Telegram with three options:

| Button | What Happens |
|---|---|
| 🚀 **Post** | Publishes to LinkedIn immediately via API |
| ✏️ **Edit** | You rewrite the text, confirm, then it posts |
| 🔄 **Reprompt** | Type instructions → tool-calling agent re-searches Tavily if needed → new draft |

A master graph uses `route_by_day()` to decide which subgraph runs — one DAG, one cron, clean conditional routing.

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **AI Pipeline** | LangGraph | Stateful graph with `interrupt()`, conditional routing, subgraph composition |
| **LLM** | Groq (LLaMA 3.3 70B) | Fast inference for post drafting, editing, and article ranking |
| **Search** | Tavily Search API | Real-time AI news fetching across 5 concurrent queries |
| **Orchestration** | Apache Airflow | DAG scheduling with cron (`30 8 * * *`), retries, monitoring |
| **State** | Redis Stack + RedisSaver | Persistent graph checkpointing — workflow survives restarts |
| **Storage** | AWS S3 | Date-partitioned JSON data lake for daily articles |
| **Compute** | AWS EC2 (m7i-flex.large) | Hosts all services via Docker Compose |
| **Auth** | AWS IAM | Least-privilege roles for S3 access, no hardcoded keys |
| **Approval** | Telegram Bot API | Interactive inline buttons, ConversationHandler for multi-step flows |
| **Publishing** | LinkedIn API | Auto-posts approved content to your profile with retry logic |
| **Prompt Mgmt** | Langfuse | Version-controlled prompts, A/B comparison, run replay |
| **Observability** | LangSmith | Full LLM traces — inputs, outputs, latency, token usage |
| **CI/CD** | GitHub Actions | Push to `main` → SSH deploy → `docker compose up --build` |
| **Containers** | Docker + Docker Compose | 3 services: `redis`, `bot`, `airflow` |

---

## Project Structure

```text
BuzzBot/
├── workflow.py                      # Master graph — daily + weekly subgraphs
├── dags/
│   └── daily_dag.py                 # Airflow DAG → invokes master_workflow
├── pipelines/
│   ├── tavily_search_tool.py        # Parallel Tavily search + dedup
│   ├── news_ranker.py               # LLM-based article ranking
│   ├── draft_post.py                # LinkedIn post generation prompt
│   ├── edit_draft_post_w_prompt.py  # Tool-calling agent for reprompt flow
│   └── post_the_post.py            # LinkedIn API posting
├── bot/
│   └── telegram_bot.py             # Persistent bot + approval ConversationHandler
├── storage/
│   └── s3_client.py                # boto3 S3 read/write wrapper
├── Dockerfile                       # Python 3.11-slim
├── docker-compose.yml               # redis + bot + airflow services
├── .github/workflows/
│   └── deploy.yml                   # CI/CD — SSH → git pull → rebuild
└── requirements.txt
```

---

## What Makes This Different

This isn't a notebook or a chatbot — it's a **scheduled, containerized, cloud-deployed, LLM-observed, human-in-the-loop pipeline** with CI/CD and persistent state.

- **`interrupt()` + Redis** — workflow pauses mid-graph, resumes hours later from the exact checkpoint
- **Tool-calling reprompt agent** — the Reprompt option dynamically searches Tavily for missing context
- **Full observability stack** — every LLM call traced in LangSmith, every prompt versioned in Langfuse
- **One-command deploy** — `git push` triggers GitHub Actions → EC2 rebuilds all containers automatically

---

<div align="center">

**Built to learn. Designed to ship.**

</div>
