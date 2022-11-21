import asyncio
import contextlib
import datetime
import json
import math
import multiprocessing
import os
import time
import tkinter as tk
import tkinter.font as tk_font
import urllib.error
import urllib.parse
import urllib.request
from tkinter import ttk

import requests
import sv_ttk
import win32api
import win32con
from PIL import Image, ImageTk
from dotenv import load_dotenv
from screeninfo import get_monitors
from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager


def get_lyrics(song):
    print(f"Searching song: {song}")
    try:
        body = find_lyrics(song)
    except KeyError:  # Unknown cause. API returns invalid?
        body = None
    if body is None:
        print("Failed to find song")
        return None
    song.update_info(body)
    print("Song found")

    print(f"Searching lyrics: {song}")
    lyrics = get_unsynced_lyrics(song, body)
    if lyrics is None:
        print("Failed to find lyrics")

    synced_lyrics = get_synced_lyrics(song, body)
    if synced_lyrics is None:
        print("Failed to find synced lyrics")

    return {
        "synced_lyrics": synced_lyrics,
        "lyrics": lyrics,
        "song_info": song.get_info()
    }


def find_lyrics(song):
    global lyric_fetch_attempt, schedule_retry_lyric_fetch_time

    duration = song.duration / 1000 if song.duration else ""
    params = {
        "q_album": song.album,
        "q_artist": song.artist,
        "q_artists": song.artist,
        "q_track": song.title,
        "track_spotify_id": song.uri,
        "q_duration": duration,
        "f_subtitle_length": math.floor(duration) if duration else "",
        "usertoken": musixmatch_token,
    }

    req = urllib.request.Request(musixmatch_base_url + urllib.parse.urlencode(params, quote_via=urllib.parse.quote), headers=musixmatch_headers)
    try:
        response = urllib.request.urlopen(req).read()
    except (urllib.error.HTTPError, urllib.error.URLError, ConnectionResetError) as e:
        print(repr(e))
        return

    r = json.loads(response.decode())
    if r["message"]["header"]["status_code"] != 200 and r["message"]["header"].get("hint") == "renew":
        print("Invalid token")
        return
    body = r["message"]["body"]["macro_calls"]

    if body["matcher.track.get"]["message"]["header"]["status_code"] != 200:
        if body["matcher.track.get"]["message"]["header"]["status_code"] == 404:
            print("Song not found.")
        elif body["matcher.track.get"]["message"]["header"]["status_code"] == 401:
            print("Timed out. Change the token or wait a few minutes before trying again.")
            create_notification(f"Timed out. Retrying in {lyric_fail_reattempt_time} seconds...", "#f95353")
            schedule_retry_lyric_fetch_time = time.time() + lyric_fail_reattempt_time
            if lyric_fetch_attempt is None:
                lyric_fetch_attempt = 2  # Next fetch attempt number
            else:
                lyric_fetch_attempt += 1
            root.after(3000, clear_notification)
        else:
            print(f"Requested error: {body['matcher.track.get']['message']['header']}")
            create_notification(f"{body['matcher.track.get']['message']['header']}", "#f95353")
            lyric_fetch_attempt = None
            root.after(3000, clear_notification)
        return

    elif isinstance(body["track.lyrics.get"]["message"].get("body"), dict):
        if body["track.lyrics.get"]["message"]["body"]["lyrics"]["restricted"]:
            print("Restricted lyrics.")
            create_notification("Lyrics are restricted.", "#f95353")
            lyric_fetch_attempt = None
            root.after(3000, clear_notification)
            return

    lyric_fetch_attempt = None
    return body


def get_unsynced_lyrics(song, body):
    if song.is_instrumental:
        lines = ["Instrumental"]
    elif song.has_unsynced:
        lyrics_body = body["track.lyrics.get"]["message"].get("body")
        if lyrics_body is None:
            return None
        if lyrics := lyrics_body["lyrics"]["lyrics_body"]:
            lines = list(filter(None, lyrics.split("\n")))
        else:
            return None
    else:
        return None
    return lines


def get_synced_lyrics(song, body):
    if song.is_instrumental:
        synced_lyrics = [[0, song.get_info()["duration"]], "Instrumental"]
    elif song.has_synced:
        subtitle_body = body["track.subtitles.get"]["message"].get("body")
        if subtitle_body is None:
            return None
        subtitle = subtitle_body["subtitle_list"][0]["subtitle"]
        if not subtitle:
            return None
        old_lyric_lines = subtitle["subtitle_body"].split("\n")

        # Remove double instrumental sections
        previous_line_lyrics = None
        lyric_lines = []
        for line in old_lyric_lines:
            if line.split("]")[1].strip() == "" and previous_line_lyrics == "":
                pass
            else:
                lyric_lines.append(line.strip())
                previous_line_lyrics = line.split("]")[1].strip()

        def timestamp_to_epoch(timestamp):  # 00:00.00 str
            epoch = 0
            epoch += int(timestamp.split(":")[0]) * 60000
            epoch += int(timestamp.split(":")[1].split(".")[0]) * 1000
            epoch += int(timestamp.split(".")[1]) * 10
            return epoch

        synced_lyrics = []
        # Add blank line from 0 to first line
        first_line_epoch = timestamp_to_epoch(lyric_lines[0].split("] ")[0].replace("[", "").strip())
        if first_line_epoch != 0:  # If first line does not start at 0
            synced_lyrics.append([[0, first_line_epoch], ""])

        # Append all lines
        for index, line in enumerate(lyric_lines):
            # Lyric Start Epoch
            lyric_start = timestamp_to_epoch(line.split("]")[0].replace("[", ""))

            # Lyric End Epoch
            if index + 1 == len(lyric_lines):  # If iterating over last item in list
                lyric_end = song.get_info()["duration"]
            else:
                lyric_end = timestamp_to_epoch(lyric_lines[index + 1].split("]")[0].replace("[", ""))

            # Lyrics Line String
            if line.split("]")[1] == "":  # Current line is empty / is an instrumental section
                lyric = ""  # or "♪"
            else:
                lyric = line.split("] ")[1]

            synced_lyrics.append([[lyric_start, lyric_end], lyric])

        # Add blank line to end if not already existent
        if synced_lyrics[-1][1] != "":
            print(synced_lyrics[-1][0][1])
            synced_lyrics.append([[synced_lyrics[-1][0][1], song.get_info()["duration"]], ""])
    else:
        return None
    return synced_lyrics


def spotifyapi_get_playing(access_token):
    response = None
    try:
        response = requests.get("https://api.spotify.com/v1/me/player/currently-playing",
                                headers={
                                    "Accept": "application/json",
                                    "Content-Type": "application/json",
                                    "Authorization": f"Bearer {access_token}"
                                })
        return response.json()
    except requests.exceptions.ConnectionError:
        print("\033[91m[ERROR] Connection Failed - Check internet connection\033[0m")
        return None
    except json.decoder.JSONDecodeError:
        print(response)
        print("\033[91m[ERROR] Spotify not open - Cannot retrieve playing data\033[0m")
        return None


def spotifyapi_get_playback_state(access_token):
    response = None
    try:
        response = requests.get("https://api.spotify.com/v1/me/player",
                                headers={
                                    "Accept": "application/json",
                                    "Content-Type": "application/json",
                                    "Authorization": f"Bearer {access_token}"
                                })
        return response.json()
    except requests.exceptions.ConnectionError:
        print("\033[91m[ERROR] Connection Failed - Check internet connection\033[0m")
        return None
    except json.decoder.JSONDecodeError:
        print(response)
        print("\033[91m[ERROR] Spotify not open - Cannot retrieve playback state\033[0m")
        return None


def spotifyapi_refresh_token():
    try:
        print("Refreshing spotify token...")
        query = "https://accounts.spotify.com/api/token"
        response = requests.post(query, data={"grant_type": "refresh_token", "refresh_token": spotify_refresh_token}, headers={"Authorization": f"Basic {spotify_base64_token}"})

        print("Posted request with response:")
        print(f"\033[90mCode {response.status_code}: {response.reason}\033[0m")
        with contextlib.suppress(json.decoder.JSONDecodeError):
            print(f"\033[90m{response.json()}\033[0m")
        print("Spotify token refreshed")

        return response.json()["access_token"]
    except requests.exceptions.ConnectionError:
        print("\033[91m[ERROR] Connection Failed - Check internet connection\033[0m")
        print("Retrying in 10 seconds...")
        time.sleep(1000)
        spotifyapi_refresh_token()


async def get_media_info():
    sessions = await MediaManager.request_async()

    if current_session := sessions.get_current_session():
        print(current_session.source_app_user_model_id)
        if current_session.source_app_user_model_id in ["Chrome", "Spotify.exe"]:
            info = await current_session.try_get_media_properties_async()

            info_dict = {song_attr: info.__getattribute__(song_attr) for song_attr in dir(info) if song_attr[0] != '_'}  # song_attr[0] != '_' ignores system attributes
            info_dict["genres"] = list(info_dict["genres"])  # Convert winsdk vector to list

            print(info_dict)
            return info_dict
    return None


class Song(object):
    def __init__(self, artist, title, album="", uri=""):
        self.artist = artist
        self.title = title
        self.album = album
        self.uri = uri
        self.duration = 0
        self.has_synced = False
        self.has_unsynced = False
        self.is_instrumental = False
        self.lyrics = None
        self.subtitles = None
        self.coverart_url = None

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"

    def get_info(self):
        return {
            "coverart_url": self.coverart_url,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration": self.duration,
            "has_synced": self.has_synced,
            "has_unsynced": self.has_unsynced,
            "is_instrumental": self.is_instrumental
        }

    def update_info(self, body):
        meta = body["matcher.track.get"]["message"]["body"]
        if not meta:
            return
        coverart_sizes = ["100x100", "350x350", "500x500", "800x800"]
        coverart_urls = list(filter(None, [meta["track"][f"album_coverart_{size}"] for size in coverart_sizes]))
        self.coverart_url = coverart_urls[-1] if coverart_urls else None
        self.title = meta["track"]["track_name"]
        self.artist = meta["track"]["artist_name"]
        self.album = meta["track"]["album_name"]
        self.duration = meta["track"]["track_length"] * 1000
        self.has_synced = meta["track"]["has_subtitles"]
        self.has_unsynced = meta["track"]["has_lyrics"]  # or meta["track"]["has_lyrics_crowd"]
        self.is_instrumental = meta["track"]["instrumental"]


def round_rectangle_points(x1, y1, x2, y2, radius=25):  # Generating points for a rounded rectangle
    return [x1 + radius, y1,
            x1 + radius, y1,
            x2 - radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1 + radius,
            x1, y1]


def create_notification(text, bg):
    notification_text.config(text=text, bg=bg)
    notification_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    canvas_notification.grid(row=2, column=0, sticky="nsew")
    root.update()


def clear_notification():
    notification_text.config(text="", bg="white")
    notification_text.pack_forget()
    canvas_notification.grid_forget()
    root.update()


def make_api_call(spotify_access_token, code_directory):
    global last_api_call_time
    spotify_playing = spotifyapi_get_playing(spotify_access_token)
    spotify_state = spotifyapi_get_playback_state(spotify_access_token)
    last_api_call_time = time.time()
    # print(f"\033[90m{spotify_playing}\033[0m")

    if spotify_playing is None and spotify_state is None:
        returns = {}
    else:
        returns = {
            "api_call_timestamp": time.time(),
            "spotify_playing": spotify_playing,
            "spotify_state": spotify_state,
            "last_updated_time": last_api_call_time,
            "returns_received": False
        }

    with open(f"{code_directory}\\api_data.json", "w+") as file:
        json.dump(returns, file, indent=4)
    return


def get_api_data():
    try:
        with open(f"{code_directory}\\api_data.json", "r+") as file:
            data = json.load(file)
    except json.decoder.JSONDecodeError:  # Occurs during the time when file is being written to
        time.sleep(0.1)
        print("Data retrieval reattempt")
        data = get_api_data()  # Reattempts to get data
    return data


def create_rectangle(x1, y1, x2, y2):
    global images

    canvas_synced_lyrics.delete("rectangle")
    images.clear()

    x1 = int(x1)
    y1 = int(y1)
    x2 = int(x2)
    y2 = int(y2)

    alpha = int(.3 * 255)  # .5 alpha
    fill = root.winfo_rgb("#000000") + (alpha,)
    x = max(x2 - x1, 0)
    y = max(y2 - y1, 0)
    image = Image.new("RGBA", (x, y), fill)
    images.append(ImageTk.PhotoImage(image))
    rectangle = canvas_synced_lyrics.create_image(x1, y1, image=images[-1], anchor="nw", tags="rectangle")
    root.update()
    return rectangle


def update_synced_lyrics(lyrics, duration):  # sourcery skip: low-code-quality
    global selected_lyric_line, rectangle_created, rectangle_status, rectangle, original_rect, rect_x1, rect_y1, rect_x2, rect_y2, target_x1, target_y1, target_x2, target_y2
    global automatic_scroll, previous_auto_scroll_fraction
    
    lyric_sync_buffer = -50  # Buffer in ms. Negative for earlier, positive for later.
    duration = duration - lyric_sync_buffer

    # rectangle_status: "creating" / "moving" / "teleporting" / "destroying" / None

    if selected_lyric_line is None:  # Song changed
        print("Song changed, resetting lyric lines")
        selected_lyric_line = 0

        automatic_scroll = True
        previous_auto_scroll_fraction = 0
        canvas_synced_lyrics.yview_moveto(0)

    for index, lyric_data in enumerate(lyrics):  # Loop through lyric ranges
        if lyric_data[0][0] <= duration <= lyric_data[0][1]:  # If duration is in range, index is the current lyric line
            if selected_lyric_line != index and rectangle_status is None:  # If line changed, rectangle_status is None ensures animation is finished before continuing
                target_text = lyrics_text_list[index]  # May raise index error?
                if canvas_synced_lyrics.itemcget(lyrics_text_list[index], "text").strip() == "":
                    target_x1, target_y1, target_x2, target_y2 = 5, canvas_synced_lyrics.bbox(target_text)[1], 5, canvas_synced_lyrics.bbox(target_text)[3]  # Target location/bbox of the text
                else:
                    target_x1, target_y1, target_x2, target_y2 = canvas_synced_lyrics.bbox(target_text)[0], canvas_synced_lyrics.bbox(target_text)[1], canvas_synced_lyrics.bbox(target_text)[2] + 2, canvas_synced_lyrics.bbox(target_text)[3]  # Target location/bbox of the text

                if rectangle_created and canvas_synced_lyrics.itemcget(lyrics_text_list[index], "text").strip() == "":
                    print("Blank line, destroying")
                    rectangle_status = "destroying"

                # Rectangle not created and current line is not blank, create rectangle
                if not rectangle_created and canvas_synced_lyrics.itemcget(lyrics_text_list[index], "text").strip() != "":  # First line, start starting animation
                    print("Preparing to create")
                    rectangle_status = "creating"

                elif rectangle_created and canvas_synced_lyrics.itemcget(lyrics_text_list[index], "text").strip() == "":
                    print("Blank line, destroying")
                    rectangle_status = "destroying"

                # Expected lyric line, move down
                elif index == selected_lyric_line + 1:
                    print(f"Next lyric line ({selected_lyric_line} -> {index})")
                    print("Moving rectangle down")
                    rectangle_status = "moving"

                    rect_x1 = canvas_synced_lyrics.bbox(rectangle)[0]
                    rect_y1 = canvas_synced_lyrics.bbox(rectangle)[1]
                    rect_x2 = canvas_synced_lyrics.bbox(rectangle)[2]
                    rect_y2 = canvas_synced_lyrics.bbox(rectangle)[3]
                    original_rect = (rect_x1, rect_y1, rect_x2, rect_y2)

                # Unexpected jump, remove and create new rectangle
                else:
                    print(f"Lyric line jumped ({selected_lyric_line} -> {index})")
                    print("Lyrics jumped, teleporting rectangle")
                    rectangle_status = "teleporting"

                print(f"New lyric hover: \"{lyrics[index][1]}\"")
                print(f"New lyric time range: {lyrics[index][0]}")

                selected_lyric_line = index
            break

    if rectangle_status is not None:
        if rectangle_status == "moving":
            # x1 never changes, y1 changes for movement, x2 changes for line length, y2 changes for movement

            # Move rectangle
            # Movement push down y1
            if round(rect_y1) >= target_y1:  # Down movement is completed
                rect_y1 = target_y1
            else:
                animation_completion = 1 - (target_y1 - rect_y1) / (target_y1 - original_rect[1])  # Animation completion percentage: 1 - Distance from current rectangle to target rectangle / Distance from original rectangle to target rectangle
                animation_completion_percentage = int(min(round(animation_completion * 100, -1), 90))

                move_pixels = (animation_acceleration[animation_completion_percentage] / 100) / 2 * (target_y1 - original_rect[1])
                try:
                    rect_y1 = canvas_synced_lyrics.bbox(rectangle)[1] + math.ceil(move_pixels)
                except TypeError:
                    rectangle_status = None
                    print("TypeError raised: moving > push down y1")

            # Movement push down y2
            if round(rect_y2) >= target_y2:  # Down movement is completed
                rect_y2 = target_y2
            else:
                animation_completion = 1 - (target_y2 - rect_y2) / (target_y2 - original_rect[3])  # Animation completion percentage: 1 - Distance from current rectangle to target rectangle / Distance from original rectangle to target rectangle
                animation_completion_percentage = int(min(round(animation_completion * 100, -1), 90))

                move_pixels = (animation_acceleration[animation_completion_percentage] / 100) / 2 * (target_y2 - original_rect[3])
                try:
                    rect_y2 = canvas_synced_lyrics.bbox(rectangle)[3] + math.ceil(move_pixels)
                except TypeError:
                    rectangle_status = None
                    print("TypeError raised: moving > push down y2")

            # Calculate rectangle shape change
            # Resize by adjusting x2
            # sourcery skip: merge-duplicate-blocks, merge-else-if-into-elif
            if original_rect[2] >= target_x2:  # If rectangle has to shrink
                if round(rect_x2) <= target_x2:
                    rect_x2 = target_x2
                else:
                    animation_completion = 1 - (rect_x2 - target_x2) / (original_rect[2] - target_x2)  # Animation completion percentage: 1 - Distance from current rectangle to target rectangle / Distance from original rectangle to target rectangle
                    animation_completion_percentage = int(min(round(animation_completion * 100, -1), 90))

                    move_pixels = (animation_acceleration[animation_completion_percentage] / 100) / 2 * (original_rect[2] - target_x2)
                    rect_x2 = canvas_synced_lyrics.bbox(rectangle)[2] - math.ceil(move_pixels)
            else:  # If rectangle has to expand
                if round(rect_x2) >= target_x2:
                    rect_x2 = target_x2
                else:
                    animation_completion = 1 - (target_x2 - rect_x2) / (target_x2 - original_rect[2])  # Animation completion percentage: 1 - Distance from current rectangle to target rectangle / Distance from original rectangle to target rectangle
                    animation_completion_percentage = int(min(round(animation_completion * 100, -1), 90))

                    move_pixels = (animation_acceleration[animation_completion_percentage] / 100) / 2 * (target_x2 - original_rect[2])
                    rect_x2 = canvas_synced_lyrics.bbox(rectangle)[2] + math.ceil(move_pixels)

            rectangle = create_rectangle(rect_x1, rect_y1, rect_x2, rect_y2)  # Create the rectangle

            if rect_x1 == target_x1 and rect_y1 == target_y1 and rect_x2 == target_x2 and rect_y2 == target_y2:  # If rectangle matches text box
                print("Moving animation done")
                rectangle_status = None

        if rectangle_status == "teleporting":
            rectangle = create_rectangle(target_x1, target_y1, target_x2, target_y2)  # Create the rectangle
            print("Teleport done")
            rectangle_status = None

        if rectangle_status == "destroying":
            # Rectangle is created, prepare to destroy
            if rectangle_created:
                rectangle_created = False
                rect_x1 = canvas_synced_lyrics.bbox(rectangle)[0]
                rect_y1 = canvas_synced_lyrics.bbox(rectangle)[1]
                rect_x2 = canvas_synced_lyrics.bbox(rectangle)[2]
                rect_y2 = canvas_synced_lyrics.bbox(rectangle)[3]

                original_rect = (rect_x1, rect_y1, rect_x2, rect_y2)

                target_x1, target_y1, target_x2, target_y2 = (rect_x1 + rect_x2) / 2, rect_y1, (rect_x1 + rect_x2) / 2, rect_y2

            # Rectangle being removed, continue to destroy
            else:
                # Movement up and down are not required because rectangle destroy pushes from both sides

                # Movement push left
                if round(rect_x1) >= target_x1:  # Left movement is completed
                    rect_x1 = target_x1
                else:
                    animation_completion = 1 - (target_x1 - rect_x1) / (target_x1 - original_rect[0])  # Animation completion percentage: 1 - Distance from current rectangle to target rectangle / Distance from original rectangle to target rectangle
                    animation_completion_percentage = int(min(round(animation_completion * 100, -1), 90))

                    move_pixels = (animation_acceleration[animation_completion_percentage] / 100) / 2 * (target_x1 - original_rect[0])
                    rect_x1 = canvas_synced_lyrics.bbox(rectangle)[0] + math.ceil(move_pixels)

                # Movement push right
                if round(rect_x2) <= target_x2:  # Right movement is completed
                    rect_x2 = target_x2
                else:
                    animation_completion = 1 - (rect_x2 - target_x2) / (original_rect[2] - target_x2)  # Animation completion percentage: 1 - Distance from current rectangle to target rectangle / Distance from original rectangle to target rectangle
                    animation_completion_percentage = int(min(round(animation_completion * 100, -1), 90))

                    move_pixels = (animation_acceleration[animation_completion_percentage] / 100) / 2 * (original_rect[2] - target_x2)
                    rect_x2 = canvas_synced_lyrics.bbox(rectangle)[2] - math.ceil(move_pixels)

                rectangle = create_rectangle(rect_x1, rect_y1, rect_x2, rect_y2)  # Create the rectangle

                if rect_x1 == target_x1 and rect_y1 == target_y1 and rect_x2 == target_x2 and rect_y2 == target_y2:  # If rectangle matches text box
                    print("Destroy animation done")
                    canvas_synced_lyrics.delete("rectangle")
                    rectangle_status = None

        if rectangle_status == "creating":
            # Rectangle is not created, create a new rectangle
            if not rectangle_created:
                rectangle_created = True

                rectangle = create_rectangle((target_x1 + target_x2) / 2, target_y1, (target_x1 + target_x2) / 2 + 1, target_y2)  # Create first rectangle

                rect_x1 = canvas_synced_lyrics.bbox(rectangle)[0]
                rect_y1 = canvas_synced_lyrics.bbox(rectangle)[1]  # Equal to target_y1
                rect_x2 = canvas_synced_lyrics.bbox(rectangle)[2]
                rect_y2 = canvas_synced_lyrics.bbox(rectangle)[3]  # Equal to target_y2

                original_rect = (rect_x1, rect_y1, rect_x2, rect_y2)

            # Rectangle has already been created, expand rectangle
            else:
                # Movement up and down are not required because rectangle creation starts at y1 - y2

                # Movement push left
                if round(rect_x1) <= target_x1:  # Left movement is completed
                    rect_x1 = target_x1
                else:
                    animation_completion = 1 - (rect_x1 - target_x1) / (original_rect[0] - target_x1)  # Animation completion percentage: 1 - Distance from current rectangle to target rectangle / Distance from original rectangle to target rectangle
                    animation_completion_percentage = int(min(round(animation_completion * 100, -1), 90))

                    move_pixels = (animation_acceleration[animation_completion_percentage] / 100) / 2 * (original_rect[0] - target_x1)
                    rect_x1 = canvas_synced_lyrics.bbox(rectangle)[0] - math.ceil(move_pixels)

                # Movement push right
                if round(rect_x2) >= target_x2:  # Right movement is completed
                    rect_x2 = target_x2
                else:
                    animation_completion = 1 - (target_x2 - rect_x2) / (target_x2 - original_rect[2])  # Animation completion percentage: 1 - Distance from current rectangle to target rectangle / Distance from original rectangle to target rectangle
                    animation_completion_percentage = int(min(round(animation_completion * 100, -1), 90))

                    move_pixels = (animation_acceleration[animation_completion_percentage] / 100) / 2 * (target_x2 - original_rect[2])
                    rect_x2 = canvas_synced_lyrics.bbox(rectangle)[2] + math.ceil(move_pixels)

                rectangle = create_rectangle(rect_x1, rect_y1, rect_x2, rect_y2)  # Create the rectangle

                # Rectangle matches the size of text box, create animation completed
                if rect_x1 == target_x1 and rect_y1 == target_y1 and rect_x2 == target_x2 and rect_y2 == target_y2:  # If rectangle matches text box
                    print("Creation animation done")
                    rectangle_status = None

    # Automatic scroll
    if lyrics_height is not None and lyrics_height > canvas_middle.winfo_height():  # If all lyrics cannot be displayed/lyrics are covered
        # print("Scroll needed")  # DEBUG
        # print(canvas_synced_lyrics.winfo_reqheight())
        if automatic_scroll:  # If automatic scroll is enabled
            if not synced_lyrics_scrollbar.winfo_ismapped():  # If scroll bar is not packed, pack
                canvas_synced_lyrics.pack_forget()
                synced_lyrics_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)  # Scrollbar must be packed before lyrics canvas
                canvas_synced_lyrics.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            # Center rectangle to the middle of the screen
            with contextlib.suppress(TypeError, tk.TclError):  # TypeError caused by non-existent rectangle/rectangle has been destroyed. TclError unknown cause, occurs after advertisement.
                rectangle_height = canvas_synced_lyrics.bbox(rectangle)[3] - canvas_synced_lyrics.bbox(rectangle)[1]
                rectangle_y_pos = canvas_synced_lyrics.bbox(rectangle)[1]  # y1 (Top left of rectangle)
                rectangle_y_center = rectangle_y_pos + (rectangle_height / 2)
                visible_canvas_height = canvas_middle.winfo_height()
                # noinspection PyTypeChecker
                fraction = (rectangle_y_center - (visible_canvas_height / 2)) / lyrics_height  # (Center of rectangle - half of visible canvas height) / height of lyrics.

                # If scroll wants to jump more than x pixels
                fraction_per_pixel = 1 / visible_canvas_height
                max_jump_range = 3  # Maximum jump in pixels
                if previous_auto_scroll_fraction is not None and not previous_auto_scroll_fraction - (fraction_per_pixel * max_jump_range) < fraction < previous_auto_scroll_fraction + (fraction_per_pixel * max_jump_range):  # If previous is not in range of current by 5 pixels
                    global target_fraction, start_fraction
                    # Start jump
                    target_fraction = float(fraction)
                    start_fraction = float(previous_auto_scroll_fraction)

                # If currently jumping
                if previous_auto_scroll_fraction is not None and target_fraction is not None and start_fraction is not None:
                    if target_fraction > start_fraction:  # Going down
                        animation_completion = 1 - (target_fraction - previous_auto_scroll_fraction) / (target_fraction - start_fraction)  # Animation completion percentage: 1 - Distance from current rectangle to target rectangle / Distance from original rectangle to target rectangle
                        animation_completion_percentage = int(min(round(animation_completion * 100, -1), 90))

                        if previous_auto_scroll_fraction >= target_fraction:
                            print("Jump down completed")
                            target_fraction = None
                            start_fraction = None
                        else:
                            fraction_change = (animation_acceleration[animation_completion_percentage] / 100) * (target_fraction - start_fraction) * 2  # x2 for double speed
                            fraction = previous_auto_scroll_fraction + fraction_change

                    elif target_fraction < start_fraction:  # Going up
                        animation_completion = 1 - (previous_auto_scroll_fraction - target_fraction) / (start_fraction - target_fraction)  # Animation completion percentage: 1 - Distance from current rectangle to target rectangle / Distance from original rectangle to target rectangle
                        animation_completion_percentage = int(min(round(animation_completion * 100, -1), 90))

                        if previous_auto_scroll_fraction <= target_fraction:
                            print("Jump up completed")
                            target_fraction = None
                            start_fraction = None
                        else:
                            fraction_change = (animation_acceleration[animation_completion_percentage] / 100) * (start_fraction - target_fraction) * 2  # x2 for double speed
                            fraction = previous_auto_scroll_fraction - fraction_change

                previous_auto_scroll_fraction = float(fraction)
                canvas_synced_lyrics.yview_moveto(fraction)

    elif synced_lyrics_scrollbar.winfo_ismapped():  # If scroll bar is packed, unpack
        synced_lyrics_scrollbar.pack_forget()


def updater():  # sourcery skip: low-code-quality
    global track_info, lyrics, previous_track_info, previous_not_playing, track_start_time, playing, shuffle, repeat
    global track_progress
    global text_track_title_slide_completed, text_track_title_slide_queued, text_artists_slide_completed, text_artists_slide_queued, text_next_slide
    global last_api_call_time, spotify_access_token, spotify_last_refresh_time, schedule_retry_lyric_fetch_time, lyric_fetch_attempt
    global selected_lyric_line, rectangle_status, rectangle_created, lyrics_height
    global root_after_id, multiprocessing_process_id

    if override_cancel:
        root_after_id = root.after(15, updater)
        return

    # Expected timing for in between API calls
    with contextlib.suppress(TypeError):  # TypeError: First run, track_info & playing = None
        if playing:  # If previously playing, playing starts as None
            track_progress = ((time.time() - track_start_time) * 1000)
            progress_bar["value"] = track_progress / track_info["duration_ms"] * 100
            text_progress_start.config(text=datetime.datetime.fromtimestamp(track_progress / 1000).strftime("%M:%S"))
            text_progress_end.config(text=datetime.datetime.fromtimestamp(track_info["duration_ms"] / 1000).strftime("%M:%S"))
            root.update()

    # Update synced lyrics
    # noinspection PyUnresolvedReferences
    if playing and lyrics is not None and lyrics["synced_lyrics"] is not None and lyrics["lyrics"] is not ["Instrumental"]:
        try:
            update_synced_lyrics(lyrics["synced_lyrics"], track_progress)
        except TypeError:
            # print("TypeError exception unhandled:")
            # traceback.print_exc()
            pass

    # Sliding track title
    if (text_track_title.winfo_width() > canvas_topbar.winfo_width() - exit_button.winfo_width() - minimize_button.winfo_width()) and (text_next_slide is None or time.time() >= text_next_slide):  # If text track title does not fit and next slide is not queued or queued time is up
        y_pos = text_track_title.winfo_y()
        x_pos = text_track_title.winfo_x()
        text_track_title.place_forget()

        text_next_slide = None

        if 6 >= x_pos >= 5 and not text_track_title_slide_queued:  # If slide has completed a rotation
            text_track_title.place(x=5, y=y_pos)  # Fix minor differences
            text_track_title_slide_completed = True
            if text_track_title_slide_completed and text_artists_slide_completed and text_next_slide is None:  # If both texts have finished sliding and next slide is not queued
                text_next_slide = time.time() + 3  # Text stays for 3 seconds before sliding again
                text_track_title_slide_queued = True
                text_artists_slide_queued = True

        elif (x_pos + text_track_title.winfo_width()) < 0:  # If right side of text if past left side of parent, then restart slide
            text_track_title.place(x=root.winfo_width() - exit_button.winfo_width(), y=y_pos)

        else:  # Slide text
            text_track_title.place(x=x_pos - 1, y=y_pos)  # Speed of text slide (int)
            text_track_title_slide_queued = False
            text_track_title_slide_completed = False

    elif text_track_title.winfo_x() != 5:  # Track title text does not need to slide but is not in correct position
        y_pos = text_track_title.winfo_y()
        text_track_title.place_forget()
        text_track_title.place(x=5, y=y_pos)

    # Sliding artists text
    if (text_artists.winfo_width() > canvas_topbar.winfo_width() - exit_button.winfo_width()) and (text_next_slide is None or time.time() >= text_next_slide):  # If text track title does not fit and next slide is not queued or queued time is up
        y_pos = text_artists.winfo_y()
        x_pos = text_artists.winfo_x()
        text_artists.place_forget()

        text_next_slide = None

        if 6 >= x_pos >= 5 and not text_artists_slide_queued:  # If slide has completed a rotation
            text_artists.place(x=5, y=y_pos)  # Fix minor differences
            text_artists_slide_completed = True
            if text_track_title_slide_completed and text_artists_slide_completed and text_next_slide is None:  # If both texts have finished sliding and next slide is not queued
                text_next_slide = time.time() + 3  # Text stays for 3 seconds before sliding again
                text_track_title_slide_queued = True
                text_artists_slide_queued = True

        elif (x_pos + text_artists.winfo_width()) < 0:  # If right side of text if past left side of parent, then restart slide
            text_artists.place(x=root.winfo_width(), y=y_pos)  # Exit button slide is not included because it is covering the text

        else:  # Slide text
            text_artists.place(x=x_pos - 1, y=y_pos)  # Speed of text slide (int)
            text_artists_slide_queued = False
            text_artists_slide_completed = False

    elif text_artists.winfo_x() != 5:  # Track title text does not need to slide but is not in correct position
        y_pos = text_artists.winfo_y()
        text_artists.place_forget()
        text_artists.place(x=5, y=y_pos)
    root.update()

    # Create/Remove automatic scroll button
    if not automatic_scroll:  # If automatic scroll is disabled
        if not lyrics_enable_auto_scroll.winfo_ismapped():  # If enable automatic scroll button is not placed
            if synced_lyrics_scrollbar.winfo_ismapped():
                lyrics_enable_auto_scroll.place(relx=1.0, rely=1.0, x=-20, y=-5, anchor="se")
            else:
                lyrics_enable_auto_scroll.place(relx=1.0, rely=1.0, x=-5, y=-5, anchor="se")
    else:  # If automatic scroll is enabled
        if lyrics_enable_auto_scroll.winfo_ismapped():  # If enable automatic scroll button is placed
            lyrics_enable_auto_scroll.place_forget()

    # Refresh Spotify access token if necessary
    if spotify_last_refresh_time < int(time.time()) - 1800:
        print("Refreshing spotify token due to time out")
        spotify_access_token = spotifyapi_refresh_token()
        spotify_last_refresh_time = time.time()

    # API call update every 1.5 seconds
    if time.time() > last_api_call_time + 1.5:
        last_api_call_time = time.time()
        multiprocessing_process_id = multiprocessing.Process(target=make_api_call, args=(spotify_access_token, code_directory))
        multiprocessing_process_id.start()

    api_data = get_api_data()

    if api_data != {} and not api_data["returns_received"]:
        # Set returns_received to True to retrieve file after every update
        with open(f"{code_directory}\\api_data.json", "r+") as file:
            data = json.load(file)
            data["returns_received"] = True
            file.seek(0)
            file.truncate(0)
            json.dump(data, file, indent=4)
        try:
            api_call_timestamp = api_data["api_call_timestamp"]
            spotify_playing = api_data["spotify_playing"]
            spotify_state = api_data["spotify_state"]

            track_info = {
                "track_name": spotify_playing["item"]["name"],
                "artists": [artist["name"] for artist in list(spotify_playing["item"]["artists"])],
                "artist_names": ", ".join(artist["name"] for artist in list(spotify_playing["item"]["artists"])),
                "album": spotify_playing["item"]["album"]["name"],
                "album_cover_link": spotify_playing["item"]["album"]["images"][-1]["url"],
                "duration_ms": spotify_playing["item"]["duration_ms"],
                "link": spotify_playing["item"]["external_urls"]["spotify"],
                "uri": spotify_playing["item"]["uri"]
            }
            track_progress = spotify_playing["progress_ms"]
            playing = spotify_playing["is_playing"]
            shuffle = spotify_state["shuffle_state"]
            repeat = spotify_state["repeat_state"]

            track_start_time = api_call_timestamp - (track_progress / 1000)  # Use api_call_timestamp to prevent file save/recall delay

            # Track Title and Artists Text
            text_track_title.config(text=track_info["track_name"])
            text_artists.config(text=track_info["artist_names"])
            # Progress bar
            progress_bar["value"] = track_progress / track_info["duration_ms"] * 100
            # Progress texts
            text_progress_start.config(text=datetime.datetime.fromtimestamp(track_progress / 1000).strftime("%M:%S"))
            text_progress_end.config(text=datetime.datetime.fromtimestamp(track_info["duration_ms"] / 1000).strftime("%M:%S"))
            # Play button
            if playing:
                image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/pause.png").resize((35, 35), Image.Resampling.LANCZOS))
            else:
                image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/play.png").resize((35, 35), Image.Resampling.LANCZOS))
            button_play.config(image=image)
            button_play.photo = image
            # Shuffle button
            if shuffle:
                image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/shuffle_selected.png").resize((15, 15), Image.Resampling.LANCZOS))
            else:
                image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/shuffle.png").resize((15, 15), Image.Resampling.LANCZOS))
            button_shuffle.config(image=image)
            button_shuffle.photo = image
            # Repeat button
            if repeat is not None:
                image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/repeat_{repeat}.png").resize((15, 15), Image.Resampling.LANCZOS))
            else:
                image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/repeat_off.png").resize((15, 15), Image.Resampling.LANCZOS))
            button_repeat.config(image=image)
            button_repeat.photo = image

            root.update()

            previous_not_playing = False

        except (TypeError, json.decoder.JSONDecodeError, KeyError) as exception:
            # TypeError: Advertisement playing
            # JSONDecodeError: Not playing Spotify
            # KeyError: Unknown cause
            if not previous_not_playing:
                print("Currently not playing")
                previous_not_playing = True
                playing = False

            track_info = None
            previous_track_info = None

            # Track Title and Artists Text
            if type(exception) == TypeError:
                text_track_title.config(text="[Advertisement]")
            else:
                text_track_title.config(text="[Not Playing]")
            text_artists.config(text="")
            # Progress bar
            progress_bar["value"] = 0
            # Progress texts
            text_progress_start.config(text="--:--")
            text_progress_end.config(text="--:--")
            # Lyrics
            canvas_synced_lyrics.delete("all")
            canvas_synced_lyrics.pack_forget()
            synced_lyrics_scrollbar.pack_forget()
            scroll_lyrics_listbox.delete(0, tk.END)
            scroll_lyrics_listbox.pack_forget()
            scroll_lyrics_scrollbar.pack_forget()
            frame_lyrics_info.place_forget()

            root.update()
            root_after_id = root.after(15, updater)
            return

        # Song is different from previously/Song has changed
        # noinspection PyTypeChecker
        if track_info != previous_track_info or (schedule_retry_lyric_fetch_time is not None and time.time() >= schedule_retry_lyric_fetch_time):
            schedule_retry_lyric_fetch_time = None

            if track_info != previous_track_info:
                previous_track_info = track_info.copy()
                print("Song changed:")
                print(f"\033[90m{track_info}\033[0m")
                lyric_fetch_attempt = None
            else:
                print(f"Retrying lyric fetch... (Attempt {lyric_fetch_attempt})")

            canvas_synced_lyrics.delete("all")
            canvas_synced_lyrics.pack_forget()
            synced_lyrics_scrollbar.pack_forget()
            scroll_lyrics_listbox.delete(0, tk.END)
            scroll_lyrics_listbox.pack_forget()
            scroll_lyrics_scrollbar.pack_forget()
            lyrics_center_text.config(text="Loading lyrics...")
            if lyric_fetch_attempt is not None:
                lyrics_center_subtitle.config(text=f"Attempt {lyric_fetch_attempt}")
            frame_lyrics_info.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

            root.update()

            lyrics = get_lyrics(Song(track_info["artist_names"], track_info["track_name"]))
            print(f"\033[90m{lyrics}\033[0m")

            lyrics_center_subtitle.config(text="")
            frame_lyrics_info.place_forget()

            # Instrumental song
            # noinspection PyTypeChecker
            if lyrics is not None and (lyrics["song_info"])["is_instrumental"]:
                lyrics_center_text.config(text="Instrumental")
                frame_lyrics_info.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

            # Synced lyrics
            elif lyrics is not None and lyrics["synced_lyrics"] is not None:
                print("Creating synced lyrics")

                selected_lyric_line = None
                rectangle_status = None
                rectangle_created = False

                lyrics_text_list.clear()

                lyrics_height = 0

                for i in range(len(lyrics["synced_lyrics"])):
                    if i == 0 or i + 1 == len(lyrics["synced_lyrics"]):  # First and last item in list
                        font_size = 1
                    else:
                        font_size = 9
                    text = lyrics["synced_lyrics"][i][1]
                    lyrics_text = canvas_synced_lyrics.create_text(5, lyrics_height, text=text, font=(tk.font.nametofont("TkDefaultFont").actual()["family"], font_size), anchor=tk.NW, justify=tk.LEFT, width=canvas_synced_lyrics.winfo_width() - 10)  # Max text width (-10 px for scroll bar)
                    lyrics_text_list.append(lyrics_text)
                    lyrics_height += canvas_synced_lyrics.bbox(lyrics_text)[3] - canvas_synced_lyrics.bbox(lyrics_text)[1]
                    lyrics_height += 2  # 2 px line spacing
                root.update()

                # Set scroll region
                canvas_synced_lyrics_bbox = list(canvas_synced_lyrics.bbox("all"))
                canvas_synced_lyrics_bbox[0] = canvas_synced_lyrics_bbox[0] - 5  # 5 px margin left
                canvas_synced_lyrics_bbox[1] = canvas_synced_lyrics_bbox[1] - 5  # 5 px margin top
                canvas_synced_lyrics_bbox = tuple(canvas_synced_lyrics_bbox)  # Tuple needs to be converted to list then back to be edited
                canvas_synced_lyrics.configure(scrollregion=canvas_synced_lyrics_bbox)

                synced_lyrics_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)  # Scrollbar must be packed before lyrics canvas
                canvas_synced_lyrics.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            elif lyrics is not None and lyrics["lyrics"] is not None:
                print("Creating scrollable lyrics")
                scroll_lyrics_listbox.insert(tk.END, "These lyrics are not synced yet.")
                scroll_lyrics_listbox.insert(tk.END, "-------------------------------------")
                for line in lyrics["lyrics"]:
                    scroll_lyrics_listbox.insert(tk.END, line)
                scroll_lyrics_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
                scroll_lyrics_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            else:
                print("No lyrics")
                lyrics_center_text.config(text="Lyrics Unavailable")
                frame_lyrics_info.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

            root.update()

    root_after_id = root.after(15, updater)


if __name__ == "__main__":
    # Code start
    code_directory = os.path.dirname(os.path.realpath(__file__))

    load_dotenv()

    musixmatch_base_url = "https://apic-desktop.musixmatch.com/ws/1.1/macro.subtitles.get?format=json&namespace=lyrics_richsynched&subtitle_format=musixmatchm&app_id=web-desktop-app-v1.0&"
    # noinspection SpellCheckingInspection
    musixmatch_headers = {"authority": "apic-desktop.musixmatch.com", "cookie": "x-musixmatchm-token-guid="}
    custom_musixmatch_token = os.getenv("MUSIXMATCH_TOKEN")
    # noinspection SpellCheckingInspection
    # If you do not have a musixmatch token, then use the following public token. This may not work 100% of the time.
    musixmatch_token = custom_musixmatch_token if custom_musixmatch_token else "2203269256ff7abcb649269df00e14c833dbf4ddfb5b36a1aae8b0"
    spotify_refresh_token = os.getenv("SPOTIFY_REFRESH_TOKEN")
    spotify_base64_token = os.getenv("SPOTIFY_BASE64_TOKEN")
    spotify_access_token = spotifyapi_refresh_token()
    spotify_last_refresh_time = time.time()

    track_info = None
    lyrics = None
    previous_track_info = None
    previous_not_playing = False
    track_start_time = time.time()
    playing = None
    shuffle = None
    repeat = None

    track_progress = 0

    text_track_title_slide_completed = True
    text_track_title_slide_queued = False
    text_artists_slide_completed = True
    text_artists_slide_queued = False
    text_next_slide = None

    last_api_call_time = 0

    lyric_fail_reattempt_time = 10  # Lyric failed reattempt time in seconds
    schedule_retry_lyric_fetch_time = None  # None if retry not scheduled. Integer (time in epoch) if fetch is scheduled
    lyric_fetch_attempt = None  # None if completed or not fetched. Integer if fetch needed

    selected_lyric_line = None
    rectangle_created = False
    rectangle_status = None
    rectangle = None
    original_rect = None
    rect_x1, rect_y1, rect_x2, rect_y2 = 0, 0, 0, 0
    target_x1, target_y1, target_x2, target_y2 = 0, 0, 0, 0
    lyrics_height = None

    automatic_scroll = True
    previous_auto_scroll_fraction = None
    target_fraction = None
    start_fraction = None

    # The speed of which animations play
    animation_acceleration = {
        # At x percent completed, the animation will move y percent.
        # Values must add up to 100
        # e.g. At 10% animation completed, the animation will move 6% of the total distance required.
        0: 4,
        10: 6,
        20: 10,
        30: 12,
        40: 18,
        50: 18,
        60: 12,
        70: 10,
        80: 6,
        90: 4,
    }
    if sum(dict.values(animation_acceleration)) != 100:
        print("Animation acceleration invalid. Values do not add up to 100.")
        if sum(dict.values(animation_acceleration)) < 100:
            print("Acceleration will be slower than excepted. Values towards the end will be used more than expected.")
        else:
            print("Acceleration will be faster than excepted. Values towards the end will not be used.")

    images = []
    lyrics_text_list = []

    root_after_id = None  # Unused
    multiprocessing_process_id = None  # Ends multiprocessing thread on exit
    override_cancel = False  # Cancel updater if True

    # GUI creation start
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.resizable(True, True)
    root.title("Spotify Surface")

    root.config(background="#f0f0f0")  # Previously: white
    root.attributes("-transparentcolor", "grey")
    root.wm_attributes("-transparentcolor", "grey")

    sv_ttk.set_theme("light")

    # Get monitor resolution
    monitor_width = 1920
    monitor_height = 1080
    for monitor in get_monitors():
        if monitor.is_primary:
            monitor_width = monitor.width
            monitor_height = monitor.height

    # Default window size
    geometry = (250, 325)

    taskbar_offset = 60  # Taskbar size is 60 pixels

    # Set window size and move to bottom right
    root.geometry(f"{geometry[0]}x{geometry[1]}+{monitor_width - geometry[0]}+{monitor_height - geometry[1] - taskbar_offset}")
    root.minsize(175, 225)
    root.update()

    root.grid_columnconfigure(0, weight=1)  # Force whole column to be the same as root

    # Create top bar canvas
    canvas_topbar = tk.Canvas(root, bg="white", highlightthickness=0)
    canvas_topbar.grid(row=0, column=0, sticky="nsew")
    root.update()

    # Create Track Title
    text_total_height = 0
    text_track_title = tk.Label(canvas_topbar, text="[Not Playing]", font=("Josefin Sans SemiBold", 13, "bold"), fg="#000000", bg="white", anchor="w", highlightthickness=0, borderwidth=0, pady=0)
    text_track_title.place(x=5, y=0)
    root.update_idletasks()  # Required to find height of widget
    text_total_height += text_track_title.winfo_height()

    # Create Track Artists
    text_total_height += -2  # Negative 2 pixel margin bottom
    text_artists = tk.Label(canvas_topbar, text="", font=("Josefin Sans SemiBold", 9, "bold"), fg="#93959a", bg="white", anchor="w", highlightthickness=0, borderwidth=0, pady=0)
    text_artists.place(x=5, y=text_total_height)
    root.update_idletasks()  # Required to find height of widget
    text_total_height += text_artists.winfo_height()

    # Re-adjust top bar canvas size
    canvas_topbar.config(height=text_total_height)

    # Create Minimize Button
    def minimize_button_on_hover():
        minimize_button.config(background="white", foreground="#5f6368")
        canvas_topbar.config(cursor="hand2")

    def minimize_button_on_unhover():
        minimize_button.config(background="white", foreground="#b2acab")
        canvas_topbar.config(cursor="")

    def minimize_button_on_click():
        print("=======================")
        print("Minimizing")
        root.withdraw()
        root.overrideredirect(False)
        root.iconify()

    minimize_button_pixel = tk.PhotoImage(width=1, height=1)  # Pixel 1 by 1 for easier button scaling
    minimize_button = tk.Button(canvas_topbar, text="-", font=("Josefin Sans SemiBold", 16, "bold"), borderwidth=0, bg="white", fg="#b2acab", image=minimize_button_pixel, compound="center", command=minimize_button_on_click)
    minimize_button["font"] = tk_font.Font(size=16)
    minimize_button.config(height=16, width=16)
    minimize_button.bind("<Enter>", lambda event: minimize_button_on_hover())
    minimize_button.bind("<Leave>", lambda event: minimize_button_on_unhover())
    minimize_button.place(anchor=tk.NE, x=-16, y=6, rely=0, relx=1.0)
    root.update()

    # Create Exit Button
    def exit_button_on_hover():
        exit_button.config(background="white", foreground="#5f6368")
        canvas_topbar.config(cursor="hand2")

    def exit_button_on_unhover():
        exit_button.config(background="white", foreground="#b2acab")
        canvas_topbar.config(cursor="")

    def exit_button_on_click():
        print("=======================")
        print("Started exit procedure")
        if multiprocessing_process_id is not None:
            # noinspection PyUnresolvedReferences
            multiprocessing_process_id.terminate()
            print("Terminated multiprocessing thread")
        # Clear json file
        print("Clearing API data file")
        with open(f"{code_directory}\\api_data.json", "w+") as file:
            json.dump({}, file, indent=4)
        # Destroy root and exit
        print("Destroying root and exiting...")
        root.destroy()
        exit()

    exit_button_pixel = tk.PhotoImage(width=1, height=1)  # Pixel 1 by 1 for easier button scaling
    exit_button = tk.Button(canvas_topbar, text="×", font=("Josefin Sans SemiBold", 16, "bold"), borderwidth=0, bg="white", fg="#b2acab", image=exit_button_pixel, compound="center", command=exit_button_on_click)
    exit_button["font"] = tk_font.Font(size=16)
    exit_button.config(height=16, width=16)
    exit_button.bind("<Enter>", lambda event: exit_button_on_hover())
    exit_button.bind("<Leave>", lambda event: exit_button_on_unhover())
    exit_button.place(anchor=tk.NE, x=0, y=6, rely=0, relx=1.0)
    root.update()

    # Create middle canvas
    canvas_middle = tk.Canvas(root, bg="#f0f0f0", highlightthickness=0)
    canvas_middle.grid(row=1, column=0, sticky="nsew")
    root.grid_rowconfigure(1, weight=1)  # Expand row
    root.update()

    # Create synced lyrics
    # noinspection PyUnusedLocal
    def resize(event):
        global lyrics_height, rectangle_status
        lyrics_height = 0

        for text in lyrics_text_list:
            canvas_synced_lyrics.itemconfig(text, width=canvas_synced_lyrics.winfo_width() - 10)  # Max text width (-10 px for scroll bar)
            text_coordinates = canvas_synced_lyrics.bbox(text)
            canvas_synced_lyrics.coords(text, 5, lyrics_height)
            lyrics_height += canvas_synced_lyrics.bbox(text)[3] - canvas_synced_lyrics.bbox(text)[1]
            lyrics_height += 2  # 2 px line spacing
        root.update()

        # Set scroll region
        canvas_synced_lyrics_bbox = list(canvas_synced_lyrics.bbox("all"))
        canvas_synced_lyrics_bbox[0] = canvas_synced_lyrics_bbox[0] - 5  # 5 px margin left
        canvas_synced_lyrics_bbox[1] = canvas_synced_lyrics_bbox[1] - 5  # 5 px margin top
        canvas_synced_lyrics_bbox = tuple(canvas_synced_lyrics_bbox)  # Tuple needs to be converted to list then back to be edited
        canvas_synced_lyrics.configure(scrollregion=canvas_synced_lyrics_bbox)

        # TODO Re-render rectangle

    def on_mouse_wheel(event):
        canvas_synced_lyrics.yview_scroll(int(-1 * (event.delta / 120)), "units")
        cancel_automatic_scroll()

    # noinspection PyUnusedLocal
    def cancel_automatic_scroll(event=None):
        global automatic_scroll
        if automatic_scroll:
            print("Cancelling automatic scroll")
            automatic_scroll = False

    canvas_synced_lyrics = tk.Canvas(canvas_middle, bg="#f0f0f0", highlightthickness=0)
    canvas_synced_lyrics.bind("<Configure>", resize)
    canvas_synced_lyrics.bind("<MouseWheel>", on_mouse_wheel)

    synced_lyrics_scrollbar = tk.Scrollbar(canvas_middle, orient=tk.VERTICAL)
    synced_lyrics_scrollbar.config(command=canvas_synced_lyrics.yview)
    canvas_synced_lyrics.config(yscrollcommand=synced_lyrics_scrollbar.set)
    synced_lyrics_scrollbar.bind("<Button-1>", cancel_automatic_scroll)

    # Create scroll lyrics
    scroll_lyrics_scrollbar = tk.Scrollbar(canvas_middle)
    scroll_lyrics_listbox = tk.Listbox(canvas_middle, yscrollcommand=scroll_lyrics_scrollbar.set, font=(tk.font.nametofont("TkDefaultFont").actual()["family"], 9), highlightthickness=0, borderwidth=0)
    scroll_lyrics_scrollbar.config(command=scroll_lyrics_listbox.yview())

    # Create lyrics text frame
    frame_lyrics_info = tk.Frame(canvas_middle, bg="white")

    # Create lyrics title
    lyrics_center_text = tk.Label(frame_lyrics_info, text="", font=("Josefin Sans SemiBold", 11, "bold"), fg="#000000", bg="#f0f0f0", anchor="w", highlightthickness=0, borderwidth=0, pady=0)
    lyrics_center_text.grid(row=0, column=0, sticky="nsew")

    # Create lyrics subtitle
    lyrics_center_subtitle = tk.Label(frame_lyrics_info, text="", font=("Josefin Sans SemiBold", 9, ""), fg="#93959a", bg="#f0f0f0", anchor="w", highlightthickness=0, borderwidth=0, pady=0)
    lyrics_center_subtitle.grid(row=1, column=0, sticky="nsew")

    def auto_scroll_button_on_hover():
        image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/scroll_hover.png").resize((25, 25), Image.Resampling.LANCZOS))
        lyrics_enable_auto_scroll.config(image=image)
        lyrics_enable_auto_scroll.photo = image
        if lyrics_enable_auto_scroll["state"] == tk.DISABLED:
            canvas_middle.config(cursor="no")
        else:
            canvas_middle.config(cursor="hand2")

    def auto_scroll_button_on_unhover():
        image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/scroll.png").resize((25, 25), Image.Resampling.LANCZOS))
        lyrics_enable_auto_scroll.config(image=image)
        lyrics_enable_auto_scroll.photo = image
        canvas_middle.config(cursor="")

    def auto_scroll_button_on_click():
        global automatic_scroll
        print("Enabling automatic scroll")
        automatic_scroll = True
        lyrics_enable_auto_scroll.place_forget()

    temp_image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/scroll.png").resize((25, 25), Image.Resampling.LANCZOS))
    lyrics_enable_auto_scroll = tk.Button(canvas_middle, image=temp_image, borderwidth=0, bg="#ffffff", compound="center", command=auto_scroll_button_on_click)
    lyrics_enable_auto_scroll.bind("<Enter>", lambda event: auto_scroll_button_on_hover())
    lyrics_enable_auto_scroll.bind("<Leave>", lambda event: auto_scroll_button_on_unhover())

    # Create notification canvas
    canvas_notification = tk.Canvas(root, bg="white", highlightthickness=0, height=0)
    canvas_notification.grid_forget()
    root.grid_rowconfigure(2, weight=0)  # Shrink if possible
    root.update()

    notification_text = tk.Label(canvas_notification, text="", bg="white", anchor="w")
    # notification_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    root.update()

    # Create bottom bar canvas
    canvas_bottompanel = tk.Canvas(root, bg="white", highlightthickness=0)
    canvas_bottompanel.grid(row=3, column=0, sticky="nsew")
    root.update()

    progress_bar = ttk.Progressbar(canvas_bottompanel, value=0, mode="determinate")
    progress_bar.pack(side=tk.TOP, fill=tk.X, expand=True, padx=5, pady=1)

    frame_controls = tk.Frame(canvas_bottompanel, bg="white")
    frame_controls.grid_columnconfigure(0, weight=1)
    frame_controls.grid_columnconfigure(1, weight=0)
    frame_controls.grid_columnconfigure(2, weight=1)
    frame_controls.pack(fill=tk.X, expand=True, padx=5)
    root.update()

    # Create a frame for 3 playback buttons: backward, play, forward. A grid is placed into this frame.
    frame_playbackbuttons = tk.Frame(frame_controls, bg="white")
    frame_playbackbuttons.grid(row=0, column=1, sticky=tk.N)
    root.update()

    # Backward button
    def backward_button_on_hover():
        image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/backward_hover.png").resize((15, 15), Image.Resampling.LANCZOS))
        button_backward.config(image=image)
        button_backward.photo = image
        if button_backward["state"] == tk.DISABLED:
            frame_playbackbuttons.config(cursor="no")
        else:
            frame_playbackbuttons.config(cursor="hand2")

    def backward_button_on_unhover():
        image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/backward.png").resize((15, 15), Image.Resampling.LANCZOS))
        button_backward.config(image=image)
        button_backward.photo = image
        frame_playbackbuttons.config(cursor="")

    def backward_button_on_click():
        # Playing on current device
        current_media_info = asyncio.run(get_media_info())
        print(f"Reading current media info: {current_media_info}")
        # noinspection PyUnresolvedReferences
        if current_media_info is not None and track_info is not None and current_media_info["title"] == track_info["track_name"]:
            print("Sending previous track keypress directly from device...")
            win32api.keybd_event(win32con.VK_MEDIA_PREV_TRACK, 0, win32con.KEYEVENTF_EXTENDEDKEY, 0)  # Next track button, from numerical keypad
        # Not playing on current device
        else:
            print("Sending request to play previous song...")
            response = requests.post("https://api.spotify.com/v1/me/player/previous",
                                     headers={"Authorization": f"Bearer {spotify_access_token}"})
            print("Posted request with response:")
            print(f"\033[90mCode {response.status_code}: {response.reason}\033[0m")
            with contextlib.suppress(json.decoder.JSONDecodeError):
                print(f"\033[90m{response.json()}\033[0m")
            # Success code 204

    image_backward = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/backward.png").resize((15, 15), Image.Resampling.LANCZOS))
    button_backward = tk.Button(frame_playbackbuttons, image=image_backward, borderwidth=0, bg="white", compound="center", command=backward_button_on_click)
    button_backward.bind("<Enter>", lambda event: backward_button_on_hover())
    button_backward.bind("<Leave>", lambda event: backward_button_on_unhover())
    button_backward.grid(row=0, column=0, sticky=tk.E, padx=(0, 10))

    # Play button
    def play_button_on_hover():
        if playing:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/pause_hover.png").resize((35, 35), Image.Resampling.LANCZOS))
        else:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/play_hover.png").resize((35, 35), Image.Resampling.LANCZOS))
        button_play.config(image=image)
        button_play.photo = image
        if button_play["state"] == tk.DISABLED:
            frame_playbackbuttons.config(cursor="no")
        else:
            frame_playbackbuttons.config(cursor="hand2")

    def play_button_on_unhover():
        if playing:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/pause.png").resize((35, 35), Image.Resampling.LANCZOS))
        else:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/play.png").resize((35, 35), Image.Resampling.LANCZOS))
        button_play.config(image=image)
        button_play.photo = image
        frame_playbackbuttons.config(cursor="")

    def play_button_on_click():
        # Playing on current device
        current_media_info = asyncio.run(get_media_info())
        print(f"Reading current media info: {current_media_info}")
        # noinspection PyUnresolvedReferences
        if current_media_info is not None and track_info is not None and current_media_info["title"] == track_info["track_name"]:
            print("Sending play/pause track keypress directly from device...")
            win32api.keybd_event(win32con.VK_MEDIA_PLAY_PAUSE, 0, win32con.KEYEVENTF_EXTENDEDKEY, 0)  # Play/Pause button, from numerical keypad
        # Not playing on current device
        else:
            if playing:  # Currently playing, pause playback
                print("Currently playing, pausing playback...")
                response = requests.put("https://api.spotify.com/v1/me/player/pause",
                                        headers={"Authorization": f"Bearer {spotify_access_token}"})
            else:  # Currently paused, start playback
                print("Currently paused, starting playback...")
                response = requests.put("https://api.spotify.com/v1/me/player/play",
                                        headers={"Authorization": f"Bearer {spotify_access_token}"})
            print("Posted request with response:")
            print(f"\033[90mCode {response.status_code}: {response.reason}\033[0m")
            with contextlib.suppress(json.decoder.JSONDecodeError):
                print(f"\033[90m{response.json()}\033[0m")
            # Success code 204

            if response.status_code == 403:
                print("403 Forbidden, attempting to retry using Musixmatch API")
                if playing:  # Currently playing, pause playback
                    print("Currently playing, pausing playback...")
                    # noinspection SpellCheckingInspection
                    response = requests.put(f"https://apic-desktop.musixmatch.com/ws/1.1/spotify.resource?app_id=web-desktop-app-v1.0&usertoken={musixmatch_token}&resource=me%2Fplayer%2Fpause",
                                            headers=musixmatch_headers)
                else:  # Currently paused, start playback
                    print("Currently paused, starting playback...")
                    # noinspection SpellCheckingInspection
                    response = requests.put(f"https://apic-desktop.musixmatch.com/ws/1.1/spotify.resource?app_id=web-desktop-app-v1.0&usertoken={musixmatch_token}&resource=me%2Fplayer%2Fplay",
                                            headers=musixmatch_headers)
                print("Posted request with response:")
                print(f"\033[90mCode {response.status_code}: {response.reason}\033[0m")
                with contextlib.suppress(json.decoder.JSONDecodeError):
                    print(f"\033[90m{response.json()}\033[0m")

    image_play = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/play.png").resize((35, 35), Image.Resampling.LANCZOS))
    button_play = tk.Button(frame_playbackbuttons, image=image_play, borderwidth=0, bg="white", compound="center", command=play_button_on_click)
    button_play.bind("<Enter>", lambda event: play_button_on_hover())
    button_play.bind("<Leave>", lambda event: play_button_on_unhover())
    grid = button_play.grid(row=0, column=1, sticky=tk.N)

    # Forward button
    def forward_button_on_hover():
        image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/forward_hover.png").resize((15, 15), Image.Resampling.LANCZOS))
        button_forward.config(image=image)
        button_forward.photo = image
        if button_forward["state"] == tk.DISABLED:
            frame_playbackbuttons.config(cursor="no")
        else:
            frame_playbackbuttons.config(cursor="hand2")

    def forward_button_on_unhover():
        image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/forward.png").resize((15, 15), Image.Resampling.LANCZOS))
        button_forward.config(image=image)
        button_forward.photo = image
        frame_playbackbuttons.config(cursor="")

    def forward_button_on_click():
        # Playing on current device
        current_media_info = asyncio.run(get_media_info())
        print(f"Reading current media info: {current_media_info}")
        # noinspection PyUnresolvedReferences
        if current_media_info is not None and track_info is not None and current_media_info["title"] == track_info["track_name"]:
            print("Sending next track keypress directly from device...")
            win32api.keybd_event(win32con.VK_MEDIA_NEXT_TRACK, 0, win32con.KEYEVENTF_EXTENDEDKEY, 0)  # Next track button, from numerical keypad
        # Not playing on current device
        else:
            print("Sending request to play next song...")
            response = requests.post("https://api.spotify.com/v1/me/player/next",
                                     headers={"Authorization": f"Bearer {spotify_access_token}"})
            print("Posted request with response:")
            print(f"\033[90mCode {response.status_code}: {response.reason}\033[0m")
            with contextlib.suppress(json.decoder.JSONDecodeError):
                print(f"\033[90m{response.json()}\033[0m")
            # Success code 204

    image_forward = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/forward.png").resize((15, 15), Image.Resampling.LANCZOS))
    button_forward = tk.Button(frame_playbackbuttons, image=image_forward, borderwidth=0, bg="white", compound="center", command=forward_button_on_click)
    button_forward.bind("<Enter>", lambda event: forward_button_on_hover())
    button_forward.bind("<Leave>", lambda event: forward_button_on_unhover())
    button_forward.grid(row=0, column=2, sticky=tk.E, padx=(10, 0))

    # Left controls: Shuffle and current progress time
    frame_controls_left = tk.Frame(frame_controls, bg="white")
    frame_controls_left.grid(row=0, column=0, sticky=tk.NW)

    text_progress_start = tk.Label(frame_controls_left, text="--:--", bg="white", highlightthickness=0, borderwidth=0, pady=0)
    text_progress_start.grid(row=0, column=0, sticky=tk.NW)

    def shuffle_button_on_hover():
        if shuffle:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/shuffle_selected_hover.png").resize((15, 15), Image.Resampling.LANCZOS))
        else:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/shuffle_hover.png").resize((15, 15), Image.Resampling.LANCZOS))
        button_shuffle.config(image=image)
        button_shuffle.photo = image
        if button_shuffle["state"] == tk.DISABLED:
            frame_controls_left.config(cursor="no")
        else:
            frame_controls_left.config(cursor="hand2")

    def shuffle_button_on_unhover():
        if shuffle:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/shuffle_selected.png").resize((15, 15), Image.Resampling.LANCZOS))
        else:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/shuffle.png").resize((15, 15), Image.Resampling.LANCZOS))
        button_shuffle.config(image=image)
        button_shuffle.photo = image
        frame_playbackbuttons.config(cursor="")

    def shuffle_button_on_click():
        if shuffle:  # Currently shuffle enabled, disable shuffle
            print("Currently shuffle enabled, disabling shuffle...")
            response = requests.put("https://api.spotify.com/v1/me/player/shuffle",
                                    headers={"Authorization": f"Bearer {spotify_access_token}"},
                                    params={"state": False})
        else:  # Currently shuffle disabled, enabled shuffle
            print("Currently shuffle disabled, enabling shuffle...")
            response = requests.put("https://api.spotify.com/v1/me/player/shuffle",
                                    headers={"Authorization": f"Bearer {spotify_access_token}"},
                                    params={"state": True})
        print("Posted request with response:")
        print(f"\033[90mCode {response.status_code}: {response.reason}\033[0m")
        with contextlib.suppress(json.decoder.JSONDecodeError):
            print(f"\033[90m{response.json()}\033[0m")
        # Success code 204

    image_shuffle = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/shuffle.png").resize((15, 15), Image.Resampling.LANCZOS))
    button_shuffle = tk.Button(frame_controls_left, image=image_shuffle, borderwidth=0, bg="white", compound="center", command=shuffle_button_on_click)
    button_shuffle.bind("<Enter>", lambda event: shuffle_button_on_hover())
    button_shuffle.bind("<Leave>", lambda event: shuffle_button_on_unhover())
    button_shuffle.grid(row=1, column=0, sticky=tk.W, padx=(7, 0))

    # Right controls: Repeat and end progress time
    frame_controls_right = tk.Frame(frame_controls, bg="white")
    frame_controls_right.grid(row=0, column=2, sticky=tk.NE)

    text_progress_end = tk.Label(frame_controls_right, text="--:--", bg="white", highlightthickness=0, borderwidth=0, pady=0)
    text_progress_end.grid(row=0, column=0, sticky=tk.NE, pady=0, ipady=0)

    def repeat_button_on_hover():
        if repeat is not None:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/repeat_{repeat}_hover.png").resize((15, 15), Image.Resampling.LANCZOS))
        else:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/repeat_off_hover.png").resize((15, 15), Image.Resampling.LANCZOS))
        button_repeat.config(image=image)
        button_repeat.photo = image
        if button_repeat["state"] == tk.DISABLED:
            frame_controls_right.config(cursor="no")
        else:
            frame_controls_right.config(cursor="hand2")

    def repeat_button_on_unhover():
        if repeat is not None:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/repeat_{repeat}_hover.png").resize((15, 15), Image.Resampling.LANCZOS))
        else:
            image = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/repeat_off_hover.png").resize((15, 15), Image.Resampling.LANCZOS))
        button_repeat.config(image=image)
        button_repeat.photo = image
        frame_controls_right.config(cursor="")

    def repeat_button_on_click():
        if repeat == "off":  # Currently repeat off, set repeat to context
            print("Currently repeat off, setting repeat to context...")
            response = requests.put("https://api.spotify.com/v1/me/player/repeat",
                                    headers={"Authorization": f"Bearer {spotify_access_token}"},
                                    params={"state": "context"})
        elif repeat == "context":  # Currently repeat context, set repeat to track
            print("Currently repeat context, set repeat to track...")
            response = requests.put("https://api.spotify.com/v1/me/player/repeat",
                                    headers={"Authorization": f"Bearer {spotify_access_token}"},
                                    params={"state": "track"})
        else:  # Currently repeat track, set repeat to off
            print("Currently repeat track, setting repeat to off...")
            response = requests.put("https://api.spotify.com/v1/me/player/repeat",
                                    headers={"Authorization": f"Bearer {spotify_access_token}"},
                                    params={"state": "off"})
        print("Posted request with response:")
        print(f"\033[90mCode {response.status_code}: {response.reason}\033[0m")
        with contextlib.suppress(json.decoder.JSONDecodeError):
            print(f"\033[90m{response.json()}\033[0m")
        # Success code 204

    image_repeat = ImageTk.PhotoImage(Image.open(f"{code_directory}/assets/repeat_off.png").resize((15, 15), Image.Resampling.LANCZOS))
    button_repeat = tk.Button(frame_controls_right, image=image_repeat, borderwidth=0, bg="white", compound="center", command=repeat_button_on_click)
    button_repeat.bind("<Enter>", lambda event: repeat_button_on_hover())
    button_repeat.bind("<Leave>", lambda event: repeat_button_on_unhover())
    button_repeat.grid(row=1, column=0, sticky=tk.E, padx=(0, 7))

    # Create size grip to change window size
    size_grip = ttk.Sizegrip(canvas_bottompanel)
    size_grip.place(anchor=tk.SE, x=0, y=0, rely=1.0, relx=1.0)

    # Set up window dragging
    def start_drag(event):
        global last_click_x, last_click_y, override_cancel
        last_click_x = event.x
        last_click_y = event.y

        print("Starting drag")
        # override_cancel = True  # Disable root updates while dragging

    # noinspection PyUnusedLocal
    def end_drag(event):
        global override_cancel
        print("Ending drag")
        # override_cancel = False
        root.update()

    def drag(event):
        x, y = event.x - last_click_x + root.winfo_x(), event.y - last_click_y + root.winfo_y()

        window_size = (root.winfo_width(), root.winfo_height())

        # Lock to side of screen
        if -15 <= x <= 15:  # Align to left of screen
            x = 0
        if -15 <= y <= 15:  # Align to top of screen
            y = 0
        if monitor_width - window_size[0] - 15 <= x <= monitor_width - window_size[0] + 15:  # Align to right of screen
            x = monitor_width - window_size[0]
        if monitor_height - window_size[1] - 15 <= y <= monitor_height - window_size[1] + 15:  # Align to bottom of screen
            y = monitor_height - window_size[1]
        if monitor_height - window_size[1] - taskbar_offset - 15 <= y <= monitor_height - window_size[1] - taskbar_offset + 15:  # Align to above taskbar/bottom of screen
            y = monitor_height - window_size[1] - taskbar_offset

        root.geometry(f"+{x}+{y}")
        # root.update()  # Causes RecursionError after a lot of movement, not needed

    def canvas_topbar_on_hover():
        canvas_topbar.config(cursor="fleur")

    def canvas_topbar_on_unhover():
        canvas_topbar.config(cursor="")

    last_click_x = 0
    last_click_y = 0
    topbar_components = [canvas_topbar, text_track_title, text_artists]
    for component in topbar_components:
        component.bind("<Button-1>", start_drag)
        component.bind("<ButtonRelease-1>", end_drag)
        component.bind("<B1-Motion>", drag)
        component.bind("<Enter>", lambda event: canvas_topbar_on_hover())
        component.bind("<Leave>", lambda event: canvas_topbar_on_unhover())

    # Override redirect on window restore
    def on_window_restore(event):
        if str(event) == "<Map event>":
            root.overrideredirect(True)
    root.bind("<Map>", on_window_restore)

    root_after_id = root.after(0, updater)

    root.mainloop()
