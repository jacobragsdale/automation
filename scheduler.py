import logging
import sys
import subprocess
import os
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ProcessPoolExecutor
from apscheduler.triggers.cron import CronTrigger

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('scheduler.log')
    ]
)
logger = logging.getLogger('lights_scheduler')

def run_script(script_path):
    """Run a Python script as a subprocess."""
    try:
        # Get the absolute path to the script
        abs_path = os.path.abspath(script_path)
        logger.info(f"Running script: {abs_path}")
        
        # Run the script using the same Python interpreter
        result = subprocess.run(
            [sys.executable, abs_path],
            capture_output=True,
            text=True,
            check=True
        )
        
        logger.info(f"Script output: {result.stdout}")
        if result.stderr:
            logger.warning(f"Script error output: {result.stderr}")
            
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running script {script_path}: {e}")
        logger.error(f"Script error output: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error running script {script_path}: {e}")
        return False

def run_morning_lights():
    """Run the morning lights script."""
    logger.info("Executing morning lights routine")
    run_script("morning_lights.py")

def run_night_lights():
    """Run the night lights script."""
    logger.info("Executing night lights routine")
    run_script("night_lights.py")

def main():
    """Set up and start the scheduler."""
    try:
        logger.info("Starting lights scheduler")
        
        # Configure job stores and executors
        jobstores = {
            'default': SQLAlchemyJobStore(url='sqlite:///jobs.sqlite')
        }
        
        executors = {
            'default': {'type': 'threadpool', 'max_workers': 5},
            'processpool': ProcessPoolExecutor(max_workers=2)
        }
        
        job_defaults = {
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 30
        }
        
        # Create the scheduler
        scheduler = BlockingScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults
        )
        
        # Add jobs
        # Morning lights: 6:30 AM on weekdays (Monday=0, Sunday=6)
        scheduler.add_job(
            run_morning_lights,
            CronTrigger(hour=6, minute=30, day_of_week='0-4'),
            id='morning_lights',
            replace_existing=True,
            name='Morning Lights Routine'
        )
        
        # Night lights: 8:00 PM every day
        scheduler.add_job(
            run_night_lights,
            CronTrigger(hour=20, minute=0),
            id='night_lights',
            replace_existing=True,
            name='Night Lights Routine'
        )
        
        # Log the next run times
        morning_job = scheduler.get_job('morning_lights')
        night_job = scheduler.get_job('night_lights')
        
        logger.info(f"Morning lights next run: {morning_job.next_run_time}")
        logger.info(f"Night lights next run: {night_job.next_run_time}")
        
        # Start the scheduler
        logger.info("Scheduler started, press Ctrl+C to exit")
        scheduler.start()
        
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.error(f"Error in scheduler: {e}")
        raise

if __name__ == "__main__":
    main()