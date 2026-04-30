import sys
from datetime import datetime

sys.path.append("/app")
from workflow import master_workflow

from airflow import DAG
from airflow.operators.python import PythonOperator

def run_workflow():
    today_str = datetime.now().strftime("%Y-%m-%d")
    thread_id = f"buzzbot_{today_str}"
    
    config = {"configurable": {"thread_id": thread_id}}
    
    master_workflow.invoke({"today": today_str}, config=config)

with DAG(
    dag_id='buzzbot',
    schedule_interval='30 8 * * *',
    start_date=datetime(2024, 1, 1),
    catchup=False
) as dag:

    PythonOperator(
        task_id='trigger_master_langgraph',
        python_callable=run_workflow,
    )
