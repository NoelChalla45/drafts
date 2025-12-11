BEAM Daily Data Request Package
================================

This package installs a systemd service + timer that runs your:
    /home/pi/queue_shipped_data.py
once every 24 hours (default: 03:00 AM).

FILES INCLUDED:
  - beam-daily-request.service
  - beam-daily-request.timer
  - README_daily_request.txt

INSTALLATION:

1) Copy all files into /home/pi
   cp beam-daily-request.* /home/pi/

2) Install into systemd:
   sudo cp beam-daily-request.service /etc/systemd/system/
   sudo cp beam-daily-request.timer  /etc/systemd/system/

3) Reload and enable timer:
   sudo systemctl daemon-reload
   sudo systemctl enable --now beam-daily-request.timer

4) Check schedule:
   systemctl list-timers beam-daily-request.timer

5) Test a run:
   sudo systemctl start beam-daily-request.service

The service will run your queue_shipped_data.py with full retry logic.
