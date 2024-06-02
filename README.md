# Raspberry Pi Home Security System

## Software Requirements

- Raspberry Pi OS
- Mosquitto MQTT Broker

## Installation

### Step 1: Install packages

```bash
sudo apt update
sudo apt install ffmpeg mosquitto mosquitto-clients
```

### Step 2: Configure Mosquitto

Modify the Mosquitto configuration file to allow connections from any IP address and enable anonymous access.

```bash
sudo nano /etc/mosquitto/mosquitto.conf
```

Add the following lines to the configuration file:

```conf
bind_address 0.0.0.0
allow_anonymous true
```

Save the file and restart the Mosquitto service:

```bash
sudo systemctl restart mosquitto
```
