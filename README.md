# Home Automation Scheduler

This project automates the scheduling of smart light routines using APScheduler with SQLite for persistence.

## Features

- Automatically runs morning lights routine at 6:30 AM on weekdays
- Automatically runs night lights routine at 8:00 PM every day
- Persistent scheduling using SQLite database
- Detailed logging to both console and log file

## Installation

1. Make sure you have Python 3.13 or higher installed
2. Install the required dependencies:

```bash
pip install -e .
# or
pip install python-kasa apscheduler sqlalchemy
```

## Usage

To start the scheduler:

```bash
python scheduler.py
```

The scheduler will run continuously in the foreground. To run it in the background, you can use:

```bash
nohup python scheduler.py > scheduler_output.log 2>&1 &
```

### Running as a systemd service (Linux)

A systemd service file is provided to run the scheduler as a system service on Linux:

1. Edit the `lights-scheduler.service` file and replace `<your_username>` with your actual username
2. Copy the service file to the systemd directory:
   ```bash
   sudo cp lights-scheduler.service /etc/systemd/system/
   ```
3. Reload systemd to recognize the new service:
   ```bash
   sudo systemctl daemon-reload
   ```
4. Enable the service to start on boot:
   ```bash
   sudo systemctl enable lights-scheduler.service
   ```
5. Start the service:
   ```bash
   sudo systemctl start lights-scheduler.service
   ```
6. Check the status:
   ```bash
   sudo systemctl status lights-scheduler.service
   ```

## Configuration

The scheduler is configured to:
- Run `morning_lights.py` at 6:30 AM Monday through Friday
- Run `night_lights.py` at 8:00 PM every day

If you need to modify the schedule, edit the `scheduler.py` file and adjust the CronTrigger parameters.

## Logs

Logs are written to:
- Console (stdout)
- `scheduler.log` file in the same directory

## Files

- `scheduler.py`: Main scheduler script
- `morning_lights.py`: Script to set morning lighting scene
- `night_lights.py`: Script to set evening lighting scene
- `jobs.sqlite`: SQLite database for job persistence (created automatically)
