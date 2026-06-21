# Binary Clock — Raspberry Pi Setup Guide

## Initial Setup (done once)

### Panel Setup
The order of the panels doesn't matter, so long as you update the arrays in the Panel Mappings section at the beginning of the Python file. The panels in Column B are for the hour (12 hour mode only), C and D for minutes, E and F for seconds, A and G for AM/PM.

When the weather is displayed it uses column B and C for Humidity, D for the UV index, E and F for Temperature (°C)

![Panel Map](Panel_Map.png)

### Python File Setup
Update the following values (Required): 
```
Govee Device Settings
Panel Mappings
```

Udate the following values (Optional):
```
Color Definitions
Brightness Settings
Power Schedule
Weather Display Settings
```

## Environment Setup

### 1. Update the package catalog and upgrade system packages
```ini
sudo apt update && sudo apt upgrade -y
```

### 2. Create a virtual Python environment.
### This creates a sandboxed Python workspace in a folder called `clock_env` in your home directory.
```ini
python3 -m venv ~/clock_env
```

### 3. Activate the virtual environment
```ini
source ~/clock_env/bin/activate
```

### 4. Install the requests library
```ini
pip install requests
```

### 5. Copy the script from your computer to the Pi
```ini
scp binary_clock.py <username>@<device_IP>:~/binary_clock.py
```

### 6. Create a service file (so clock auto-starts after device reboot)
```ini
sudo nano /etc/systemd/system/binary_clock.service
```

### Paste the following into the editor (update your username)

```ini
[Unit]
Description=Binary Clock
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/home/<username>/clock_env/bin/python3 -u /home/<username>/binary_clock.py
WorkingDirectory=/home/<username>
Restart=always
RestartSec=5
User=<username>

[Install]
WantedBy=multi-user.target
```
### Press `Ctrl+X`, then `Y`, then `Enter` to save and exit

### 7. Register and start the service
```ini
sudo systemctl daemon-reload
sudo systemctl enable binary_clock
sudo systemctl start binary_clock
```

## Ongoing Operations

### Check if the service is running
```ini
sudo systemctl status binary_clock
```

### View standard output
```ini
sudo journalctl -u binary_clock -f
```

### Stop the service
```ini
sudo systemctl stop binary_clock
```

### Restart the service
```ini
sudo systemctl restart binary_clock
```