BEAM Supervisor Setup
======================

Files in this package:
- supervisor_config.json          (place in /home/pi)
- supervisor_state.json           (place in /home/pi)
- transfer_with_retry.py          (place in /home/pi, chmod +x)
- supervisor_ping_check.py        (place in /home/pi, chmod +x)
- beam-daily-sync.service         (copy to /etc/systemd/system)
- beam-daily-sync.timer           (copy to /etc/systemd/system)
- beam-health-check.service       (copy to /etc/systemd/system)
- beam-health-check.timer         (copy to /etc/systemd/system)

Basic install steps on the supervisor Pi (as user pi):

1) Copy the JSON + .py files to /home/pi:
   - supervisor_config.json
   - supervisor_state.json
   - transfer_with_retry.py
   - supervisor_ping_check.py

   Then:
   chmod +x /home/pi/transfer_with_retry.py
   chmod +x /home/pi/supervisor_ping_check.py

2) Create data + log directories if they don't exist:
   mkdir -p /home/pi/supervisor_data

3) Copy the systemd units:
   sudo cp beam-daily-sync.service /etc/systemd/system/
   sudo cp beam-daily-sync.timer  /etc/systemd/system/
   sudo cp beam-health-check.service /etc/systemd/system/
   sudo cp beam-health-check.timer  /etc/systemd/system/

4) Reload systemd so it sees the new units:
   sudo systemctl daemon-reload

5) Enable and start the timers:
   sudo systemctl enable --now beam-daily-sync.timer
   sudo systemctl enable --now beam-health-check.timer

You can check status with:
   systemctl status beam-daily-sync.timer
   systemctl status beam-health-check.timer

Log file:
   /home/pi/queue_data_request.log
