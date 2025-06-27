#!/usr/bin/env bash
set -e

# 1) Mask all systemd sleep/hibernate targets
for t in sleep.target suspend.target hibernate.target hybrid-sleep.target; do
  systemctl --now mask "$t"
done

# 2) Tell logind to ignore lid switches & idle actions
conf=/etc/systemd/logind.conf
grep -q "^HandleLidSwitch=ignore"    $conf || sed -i \
  -e 's|#HandleLidSwitch=.*|HandleLidSwitch=ignore|' \
  -e 's|#HandleLidSwitchDocked=.*|HandleLidSwitchDocked=ignore|' \
  -e 's|#IdleAction=.*|IdleAction=ignore|' \
  $conf

# Restart logind to pick up changes
systemctl restart systemd-logind

# 4) Turn off backlight(s)
# 4a) Screen backlight via sysfs
for d in /sys/class/backlight/*; do
  if [ -w "$d/brightness" ]; then
    echo 0 > "$d/brightness"
  fi
done

# 4b) Keyboard backlight (e.g. smc::kbd_backlight)
for d in /sys/class/leds/*kbd*; do
  if [ -w "$d/brightness" ]; then
    echo 0 > "$d/brightness"
  fi
done

# 5) Install required Python packages
echo "Installing required Python packages..."
pip install python-kasa apscheduler sqlalchemy

# 6) Set up the scheduler service
echo "Setting up the scheduler service..."
# Get the current username
CURRENT_USER=$(whoami)

# Update the service file with the current username
sed -i "s/<your_username>/$CURRENT_USER/" lights-scheduler.service

# Copy the service file to systemd directory
cp lights-scheduler.service /etc/systemd/system/

# Reload systemd to recognize the new service
systemctl daemon-reload

# Enable and start the service
systemctl enable lights-scheduler.service
systemctl start lights-scheduler.service

echo "Scheduler service started. Check status with: systemctl status lights-scheduler.service"
echo "Setup Complete"
