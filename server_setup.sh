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

echo "Setup Complete"
