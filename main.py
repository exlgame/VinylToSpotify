import tkinter as tk
from tkinter import messagebox
import sounddevice as sd
import numpy as np
import soundfile as sf
import requests
import hmac
import hashlib
import base64
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import json
import threading
import queue

# Configuration ACRCloud
access_key = ""
access_secret = ""

# Configuration Spotify
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id="",
                                               client_secret="",
                                               redirect_uri="",
                                               scope="user-read-playback-state,user-modify-playback-state",
                                               cache_path=".cache"))

# Liste des périphériques audio disponibles
def list_audio_devices():
    devices = sd.query_devices()
    devices_list = []
    for idx, device in enumerate(devices):
        if device['max_input_channels'] > 0:  # Filtrer pour garder uniquement les périphériques avec des canaux d'entrée
            devices_list.append((idx, device['name'], device['max_input_channels']))
    # Filtrer les périphériques avec des noms en double
    seen = set()
    unique_devices = [(idx, name, ch) for idx, name, ch in devices_list if name not in seen and not seen.add(name)]
    return unique_devices

def update_device_list():
    devices = list_audio_devices()
    device_names = ["None"] + [device[1] for device in devices]
    # Réinitialiser le menu déroulant
    device_menu['menu'].delete(0, 'end')
    for name in device_names:
        device_menu['menu'].add_command(label=name, command=tk._setit(device_var, name))

def get_device_index(device_name):
    devices = list_audio_devices()
    for idx, name, _ in devices:
        if name == device_name:
            return idx
    return None

# Capture de l'audio
def record_audio(duration=7, fs=44100, device_index=None):
    if device_index is None:
        print("No device selected.")
        return None

    devices = sd.query_devices()
    if device_index >= len(devices):
        print("Invalid device index.")
        return None

    device_info = devices[device_index]
    num_channels = device_info['max_input_channels']

    if num_channels < 1:
        print("Selected device does not support input channels.")
        return None

    # Use a default value of 1 channel if the device does not support 2 channels
    channels = min(num_channels, 2)

    print(f"Recording with {channels} channel(s)...")
    try:
        audio = sd.rec(int(duration * fs), samplerate=fs, channels=channels, dtype='float64', device=device_index, blocking=True)
        sd.wait()
        print("Recording complete.")
        return audio
    except Exception as e:
        print(f"Error during recording: {e}")
        return None

# Sauvegarde de l'audio au format WAV
def save_audio(audio, samplerate=44100, filename="output.wav"):
    if audio is None:
        print("No audio to save!")
        return None
    sf.write(filename, audio, samplerate)
    print(f"Audio saved as {filename}.")
    return filename

# Envoi de l'audio à ACRCloud pour identification
def identify_music(filename):
    http_method = "POST"
    http_uri = "/v1/identify"
    data_type = "audio"
    signature_version = "1"
    timestamp = str(time.time())

    # Préparer la signature
    string_to_sign = http_method + "\n" + http_uri + "\n" + access_key + "\n" + data_type + "\n" + signature_version + "\n" + timestamp
    sign = base64.b64encode(hmac.new(access_secret.encode('utf-8'), string_to_sign.encode('utf-8'), digestmod=hashlib.sha1).digest()).decode('utf-8')

    # Ouvrir le fichier et lire les données
    with open(filename, 'rb') as f:
        file_data = f.read()
        file_size = len(file_data)

    # Envoyer la requête POST avec les données
    with open(filename, 'rb') as f:
        files = {'sample': f}
        data = {
            "access_key": access_key,
            "data_type": data_type,
            "signature_version": signature_version,
            "signature": sign,
            "sample_bytes": str(file_size),
            "timestamp": timestamp
        }

        response = requests.post("https://identify-eu-west-1.acrcloud.com/v1/identify", files=files, data=data)
        print(response.status_code, response.text)  # Debug
        return response.json()

# Recherche sur Spotify et lecture
def play_on_spotify(track_name, artist_name):
    results = sp.search(q=f"{track_name} {artist_name}", type='track', limit=1)
    if results['tracks']['items']:
        track_id = results['tracks']['items'][0]['id']
        sp.start_playback(uris=[f"spotify:track:{track_id}"])
        print(f"Playing {track_name} by {artist_name} on Spotify.")
    else:
        print("Track not found on Spotify.")

# Fonction pour comparer deux chansons
def compare_tracks(track1, track2):
    """Compare two track dictionaries based on title and artist."""
    if not track1 or not track2:
        return False
    return (track1['metadata']['music'][0]['title'] == track2['metadata']['music'][0]['title'] and
            track1['metadata']['music'][0]['artists'][0]['name'] == track2['metadata']['music'][0]['artists'][0]['name'])

# Fonction pour le traitement de l'identification
def process_identification():
    global last_track_info

    if not recording:
        return

    audio = record_audio(device_index=device_index)
    filename = save_audio(audio)
    if filename:
        track_info = identify_music(filename)
        if track_info and 'status' in track_info and track_info['status']['msg'] == 'Success':
            if not compare_tracks(track_info, last_track_info):
                music = track_info['metadata']['music'][0]
                track_name = music['title']
                artist_name = music['artists'][0]['name']
                play_on_spotify(track_name, artist_name)
                last_track_info = track_info  # Met à jour la dernière piste jouée
            else:
                print("Same track already playing, skipping...")
        else:
            print("Music identification failed or no result found.")
    else:
        print("No audio file was created.")

# Fonction pour l'exécution périodique de l'identification
def periodic_identification():
    process_identification()
    if recording:
        root.after(5000, periodic_identification)  # Continuer à relancer toutes les 10 secondes

# Fonction pour démarrer l'enregistrement
def start_recording():
    global recording, device_index
    device_name = device_var.get()
    if device_name == "None":
        messagebox.showwarning("Selection Error", "Please select a microphone.")
        return
    
    device_index = get_device_index(device_name)
    if device_index is not None:
        recording = True
        # Utiliser un thread pour l'enregistrement et l'identification
        threading.Thread(target=periodic_identification, daemon=True).start()
    else:
        messagebox.showerror("Selection Error", "Selected device not found.")

def on_start_button_click():
    if not recording:
        start_recording()

def on_stop_button_click():
    global recording
    recording = False
    print("Recording stopped.")

# Création de la fenêtre principale
root = tk.Tk()
root.title("Music Identifier")

device_var = tk.StringVar(value="None")
device_index = None
recording = False
last_track_info = None  # Variable pour suivre les informations de la dernière piste jouée

# Interface
tk.Label(root, text="Select Microphone:").pack(pady=10)
device_menu = tk.OptionMenu(root, device_var, "None")
device_menu.pack(pady=10)

tk.Button(root, text="Start Recording", command=on_start_button_click).pack(pady=10)
tk.Button(root, text="Stop Recording", command=on_stop_button_click).pack(pady=10)

# Mettre à jour la liste des périphériques
update_device_list()

root.mainloop()