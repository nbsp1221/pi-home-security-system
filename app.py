import adafruit_dht
import base64
import board
import io
import os
import paho.mqtt.client as mqtt
import pymysql
import subprocess
import threading
import time
import RPi.GPIO as GPIO
from dotenv import load_dotenv
from flask import Flask, Response, render_template, request, send_file
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder, MJPEGEncoder
from picamera2.outputs import FileOutput

load_dotenv()

#==================================================
# Database configuration
#==================================================

MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')
MYSQL_USER = os.getenv('MYSQL_USER')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_HOST = os.getenv('MYSQL_HOST')
MYSQL_PORT = int(os.getenv('MYSQL_PORT'))

connection = pymysql.connect(
    host=MYSQL_HOST,
    port=MYSQL_PORT,
    user=MYSQL_USER,
    password=MYSQL_PASSWORD,
    database=MYSQL_DATABASE,
    charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor
)
cursor = connection.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS temperature_humidity_records (
        id INT AUTO_INCREMENT PRIMARY KEY,
        temperature FLOAT NOT NULL,
        humidity FLOAT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS flame_detection_records (
        id INT AUTO_INCREMENT PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS gas_detection_records (
        id INT AUTO_INCREMENT PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS motion_detection_records (
        id INT AUTO_INCREMENT PRIMARY KEY,
        filename VARCHAR(255) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

#==================================================
# Database functions
#==================================================

def get_temperature_humidity_records(limit=None):
    if limit is None:
        cursor.execute('SELECT * FROM temperature_humidity_records ORDER BY created_at DESC')
    else:
        cursor.execute('SELECT * FROM temperature_humidity_records ORDER BY created_at DESC LIMIT %s', (limit,))
    records = cursor.fetchall()
    records = sorted(records, key=lambda x: x['created_at'])
    return records

def get_flame_detection_records(limit=None):
    if limit is None:
        cursor.execute('SELECT * FROM flame_detection_records ORDER BY created_at DESC')
    else:
        cursor.execute('SELECT * FROM flame_detection_records ORDER BY created_at DESC LIMIT %s', (limit,))
    return cursor.fetchall()

def get_gas_detection_records(limit=None):
    if limit is None:
        cursor.execute('SELECT * FROM gas_detection_records ORDER BY created_at DESC')
    else:
        cursor.execute('SELECT * FROM gas_detection_records ORDER BY created_at DESC LIMIT %s', (limit,))
    return cursor.fetchall()

def get_motion_detection_records(limit=None):
    if limit is None:
        cursor.execute('SELECT * FROM motion_detection_records ORDER BY created_at DESC')
    else:
        cursor.execute('SELECT * FROM motion_detection_records ORDER BY created_at DESC LIMIT %s', (limit,))
    return cursor.fetchall()

#==================================================
# Sensors configuration
#==================================================

TEMPERATURE_HUMIDITY_SENSOR_PIN = board.D2
FLAME_SENSOR_PIN = 3
GAS_SENSOR_PIN = 4
ULTRASONIC_DISTANCE_SENSOR_TRIGGER_PIN = 14
ULTRASONIC_DISTANCE_SENSOR_ECHO_PIN = 15
RELAY_PIN = 17

dht11 = adafruit_dht.DHT11(TEMPERATURE_HUMIDITY_SENSOR_PIN)
GPIO.setmode(GPIO.BCM)
GPIO.setup(FLAME_SENSOR_PIN, GPIO.IN)
GPIO.setup(GAS_SENSOR_PIN, GPIO.IN)
GPIO.setup(ULTRASONIC_DISTANCE_SENSOR_TRIGGER_PIN, GPIO.OUT)
GPIO.setup(ULTRASONIC_DISTANCE_SENSOR_ECHO_PIN, GPIO.IN)
GPIO.setup(RELAY_PIN, GPIO.OUT)

#==================================================
# Camera configuration
#==================================================

camera = Picamera2()
camera.configure(camera.create_video_configuration())
h264_encoder = H264Encoder(10000000)
mjpeg_encoder = MJPEGEncoder()

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = threading.Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

streaming_output = StreamingOutput()

#==================================================
# MQTT configuration
#==================================================

MQTT_HOST = os.getenv('MQTT_HOST')
MQTT_PORT = int(os.getenv('MQTT_PORT'))
MQTT_FLAME_DETECTION_TOPIC = 'flame_detection'
MQTT_GAS_DETECTION_TOPIC = 'gas_detection'
MQTT_MOTION_DETECTION_TOPIC = 'motion_detection'
MQTT_RELAY_TOPIC = 'relay'

def mqtt_on_connect(client, userdata, flags, rc):
    print(f'Connected to MQTT broker with result code {rc}')
    client.subscribe(MQTT_RELAY_TOPIC)

def mqtt_on_message(client, userdata, message):
    topic = message.topic
    payload = message.payload.decode()
    print(f'Message received on topic {topic}: {payload}')
    if topic == MQTT_RELAY_TOPIC:
        if payload == 'on':
            GPIO.output(RELAY_PIN, True)
        elif payload == 'off':
            GPIO.output(RELAY_PIN, False)

def mqtt_on_disconnect(client, userdata, rc):
    print(f'Disconnected from MQTT broker with result code {rc}')

mqtt_client = mqtt.Client()
mqtt_client.on_connect = mqtt_on_connect
mqtt_client.on_message = mqtt_on_message
mqtt_client.on_disconnect = mqtt_on_disconnect
mqtt_client.connect(MQTT_HOST, MQTT_PORT)
mqtt_client.loop_start()

#==================================================
# Sensor threading
#==================================================

def temperature_humidity_sensor_threading():
    while True:
        time.sleep(5)
        try:
            temperature = dht11.temperature
            humidity = dht11.humidity
            if temperature is None or humidity is None:
                continue
            print(f'Temperature: {temperature}°C, Humidity: {humidity}%')
            cursor.execute('INSERT INTO temperature_humidity_records (temperature, humidity) VALUES (%s, %s)', (temperature, humidity))
            connection.commit()
        except Exception as e:
            print(e)

def flame_sensor_threading():
    while True:
        time.sleep(1)
        try:
            no_flame = GPIO.input(FLAME_SENSOR_PIN)
            if no_flame:
                continue
            print('Flame detected!')
            mqtt_client.publish(MQTT_FLAME_DETECTION_TOPIC, 'Flame detected!')
            cursor.execute('INSERT INTO flame_detection_records () VALUES ()')
            connection.commit()
        except Exception as e:
            print(e)

def gas_sensor_threading():
    while True:
        time.sleep(1)
        try:
            no_gas = GPIO.input(GAS_SENSOR_PIN)
            if no_gas:
                continue
            print('Gas detected!')
            mqtt_client.publish(MQTT_GAS_DETECTION_TOPIC, 'Gas detected!')
            cursor.execute('INSERT INTO gas_detection_records () VALUES ()')
            connection.commit()
        except Exception as e:
            print(e)

def ultrasonic_distance_sensor_threading():
    while True:
        time.sleep(1)
        try:
            GPIO.output(ULTRASONIC_DISTANCE_SENSOR_TRIGGER_PIN, True)
            time.sleep(0.00001)
            GPIO.output(ULTRASONIC_DISTANCE_SENSOR_TRIGGER_PIN, False)
            while GPIO.input(ULTRASONIC_DISTANCE_SENSOR_ECHO_PIN) == 0:
                pulse_start_time = time.time()
            while GPIO.input(ULTRASONIC_DISTANCE_SENSOR_ECHO_PIN) == 1:
                pulse_end_time = time.time()
            pulse_duration = pulse_end_time - pulse_start_time
            distance = pulse_duration * 17150
            distance = round(distance, 2)
            if distance > 30:
                continue
            print('Motion detected!')
            mqtt_client.publish(MQTT_MOTION_DETECTION_TOPIC, 'Motion detected!')
            timestamp = int(time.time())
            h264_filename = f'motion_detection_{timestamp}.h264'
            h264_filepath = os.path.join('static', h264_filename)
            mp4_filename = f'motion_detection_{timestamp}.mp4'
            mp4_filepath = os.path.join('static', mp4_filename)
            camera.stop_recording()
            camera.start_recording(h264_encoder, FileOutput(h264_filepath))
            time.sleep(5)
            camera.stop_recording()
            camera.start_recording(mjpeg_encoder, FileOutput(streaming_output))
            subprocess.call(['ffmpeg', '-i', h264_filepath, '-c:v', 'copy', mp4_filepath])
            os.remove(h264_filepath)
            cursor.execute('INSERT INTO motion_detection_records (filename) VALUES (%s)', (mp4_filename,))
            connection.commit()
        except Exception as e:
            print(e)

#==================================================
# Web server configuration
#==================================================

WEB_SERVER_USER = os.getenv('WEB_SERVER_USER')
WEB_SERVER_PASSWORD = os.getenv('WEB_SERVER_PASSWORD')
WEB_SERVER_PORT = int(os.getenv('WEB_SERVER_PORT'))

app = Flask(__name__)

def is_authenticated(auth):
    if not auth:
        return False
    token = auth.split()[1]
    given_user, given_pass = base64.b64decode(token).decode('utf-8').split(':')
    return given_user == WEB_SERVER_USER and given_pass == WEB_SERVER_PASSWORD

@app.route('/')
def index():
    auth = request.headers.get('Authorization')
    if not is_authenticated(auth):
        return Response('Authentication failed', 401, {'WWW-Authenticate': 'Basic realm="Authentication required"'})
    temperature_humidity_records = get_temperature_humidity_records(100)
    print(temperature_humidity_records)
    flame_records = get_flame_detection_records(10)
    gas_records = get_gas_detection_records(10)
    motion_records = get_motion_detection_records(10)
    return render_template(
        'index.html',
        temperature_humidity_records=temperature_humidity_records,
        flame_records=flame_records,
        gas_records=gas_records,
        motion_records=motion_records
    )

@app.route('/stream.mjpeg')
def stream():
    auth = request.headers.get('Authorization')
    if not is_authenticated(auth):
        return Response('Authentication failed', 401, {'WWW-Authenticate': 'Basic realm="Authentication required"'})
    def generate():
        while True:
            with streaming_output.condition:
                streaming_output.condition.wait()
                frame = streaming_output.frame
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame)).encode() + b'\r\n'
                   b'\r\n' + frame + b'\r\n')
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_file(f'static/{filename}')

#==================================================
# Main program
#==================================================

def run_thread(target):
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()

if __name__ == '__main__':
    try:
        run_thread(temperature_humidity_sensor_threading)
        run_thread(flame_sensor_threading)
        run_thread(gas_sensor_threading)
        run_thread(ultrasonic_distance_sensor_threading)
        camera.start_recording(mjpeg_encoder, FileOutput(streaming_output))
        app.run(host='0.0.0.0', port=8000, threaded=True)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(e)
    finally:
        camera.stop_recording()
        connection.close()
