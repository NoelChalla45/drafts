BEAM Node Package
=================

This package contains the minimal files each node needs under the simplified system:

CONTENTS:
---------
1) config.json  
   - Your full sensor + system configuration.
   - Node DOES NOT send heartbeat or do any supervisor communication.
   - The supervisor handles all detection using ping.

2) node_auto_start_example.service  
   - A template systemd service for auto-starting your sensor collector script.
   - You may rename ExecStart to whatever your sensor script is.

INSTALLATION:
-------------
1) Place config.json into:
       /home/pi/config.json

2) If you have a sensor logger script (for example /home/pi/sensor_logger.py),
   modify ExecStart in node_auto_start_example.service:
       ExecStart=/usr/bin/env python3 /home/pi/sensor_logger.py

3) Install the auto-start service:
       sudo cp node_auto_start_example.service /etc/systemd/system/
       sudo systemctl daemon-reload
       sudo systemctl enable --now node_auto_start_example.service

Nothing else is required on the node.
All sync + retry + catch-up logic lives on the supervisor.
