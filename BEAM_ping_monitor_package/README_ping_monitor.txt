BEAM Ping Monitor Package
==========================

This package adds a 10-minute ping check on the supervisor to track
which nodes are alive or dead.

Files:
  - ping_nodes_10min.py
  - beam-ping-monitor.service
  - beam-ping-monitor.timer
  - README_ping_monitor.txt

Assumptions:
  - Your node status JSON is at: /home/pi/Node_status.json
    and looks like:
      {
        "node1": { "ip": "192.168.1.1", "node_state": "dead", "transfer_fail": true },
        ...
      }

Installation steps (on supervisor):

1) Copy all files to /home/pi:
     cp ping_nodes_10min.py beam-ping-monitor.* README_ping_monitor.txt /home/pi/

2) Make the script executable:
     chmod +x /home/pi/ping_nodes_10min.py

3) Copy the systemd units into place:
     cd /home/pi
     sudo cp beam-ping-monitor.service /etc/systemd/system/
     sudo cp beam-ping-monitor.timer  /etc/systemd/system/

4) Reload systemd so it sees the new units:
     sudo systemctl daemon-reload

5) Enable and start the timer:
     sudo systemctl enable --now beam-ping-monitor.timer

6) Check status:
     systemctl status beam-ping-monitor.timer
     systemctl status beam-ping-monitor.service  # shows last run

Logs are written to:
     /home/pi/queue_data_request.log

Node_status.json will have node_state updated between "alive" and "dead"
as nodes are pinged every 10 minutes.
