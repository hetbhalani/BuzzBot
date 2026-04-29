import sys
from datetime import datetime

sys.path.append("/app")
from workflow import master_workflow

from airflow import DAG
from airflow.operators.python import PythonOperator

def run_workflow():
    master_workflow.invoke({"today": datetime.now().strftime("%Y-%m-%d")})

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
