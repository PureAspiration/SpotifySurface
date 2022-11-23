<br>
<div align="center">
  <img src="https://i.imgur.com/qvdqtsc.png" alt="Logo" width="150" height="150">

  <h3 align="center">Spotify Surface</h3>

  <p align="center">
    A minimalistic window with lyrics synced to Spotify<br>on the surface of your screen
    <br>
    <br>
    <a href="#usage-and-features">Usage and Features</a>
    ·
    <a href="https://github.com/PureAspiration/SpotifySurface/issues">Report Bug</a>
    ·
    <a href="https://github.com/PureAspiration/SpotifySurface/issues">Request Feature</a>
  </p>
</div>

---

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li><a href="#about">About</a></li>
    <li><a href="#usage-and-features">Usage and Features</a></li>
    <li><a href="#installationdownloading">Installation/Downloading</a></li>
    <li>
      <a href="#setup">Setup</a>
      <ul>
        <li><a href="#tokens-and-environment-variables">Tokens and Environment Variables</a></li>
        <li><a href="#spotify-tokens">Spotify Tokens</a></li>
        <li><a href="#musixmatch-token">Musixmatch Token</a></li>
      </ul>
    </li>
    <li><a href="#acknowledgments-and-credits">Acknowledgments and Credits</a></li>
    <li><a href="#developer">Developer</a></li>
    <li><a href="#license">License</a></li>
  </ol>
</details>

---

## About
A minimalistic window that shows you the current song playing on Spotify with synced lyrics.<br>
The application is non-distracting with all the information you need about the song you are listening to.
This window is pinned to the top of the screen for all your lyrics needs.
<br>

## Usage and Features
<strong>Synced Lyrics</strong><br>
Lyrics are shown at the center of the interface, with a following rectangle.<br>
<img src="https://i.imgur.com/3fp5ObV.gif" alt="Synced Lyrics Demo" height=200>

<strong>Automatic Lyric Scrolling</strong><br>
The lyrics scroll down automatically.<br>
But what if you want to read the lyrics? Then just scroll.<br>
Once you're done, just click the follow button, and the lyrics will scroll automatically once again.<br>
<img src="https://i.imgur.com/sSYJV18.gif" alt="Automatic Lyric Scrolling Demo" height=200>

<strong>Live Lyrics Fetching</strong><br>
The application searches for lyrics immediately after you change songs on Spotify.<br>
<img src="https://i.imgur.com/f0GOJy4.gif" alt="Logo" height=200>

<strong>Quick Access Controls *</strong><br>
With the quick access controls, you can play/pause, skip, return, shuffle, and repeat songs with the click of a singular button.<br>
&ast; Note that some of these functions require Spotify Premium to work. If you do not have Spotify Premium, the play/pause, skip, and return buttons will attempt to skip directly from the device. This function will only work on Windows machines.<br>
<img src="https://i.imgur.com/3fp5ObV.gif" alt="Quick Access Controls Demo" height=200>

<strong>Window Dragging, Resize, and Alignment Lock</strong><br>
The window can be dragged and resized like a normal window, but when dragging the window near the side of the screen, the window locks and aligns to the side or at the taskbar.<br>
<img src="https://i.imgur.com/i6Pao1A.gif" alt="Window Dragging and Alignment Lock Demo" height=200>

<br><br>

---

## Installation/Downloading
* Clone or download this repo
* Install the required dependencies with pip command:
```pip install -r requirements.txt```
<br>

## Setup

#### Tokens and Environment Variables
The following 3 tokens can be put into an environment variable.

To do this, create a file named `.env` in your folder containing the `main.py` file.

In the file, enter the following, replacing `<TOKEN>` with your respective token.
```
SPOTIFY_REFRESH_TOKEN=<TOKEN>
SPOTIFY_BASE64_TOKEN=<TOKEN>
MUSIXMATCH_TOKEN=<TOKEN>
```
<br>

#### Spotify Tokens
Follow [this Youtube video](https://youtu.be/-FsFT6OwE1A?t=83) from 1:22 to 14:32.<br>
You will only need to save 2 tokens from this video:
 * <strong>Spotify Refresh Token</strong> (14:25)
 * <strong>Spotify Base64 Token</strong> (10:50)
<br><br>

#### Musixmatch Token
You may remove the `MUSIXMATCH_TOKEN` variable from the `.env` file if you do not have a Musixmatch token.<br>
Do not leave the variable unfilled.

Keep in mind that the default token provided may not work 100% of the time and is likely rate limited.

In order to get a new Musixmatch token, follow steps 1 - 5 with the guide [here](https://spicetify.app/docs/faq#sometimes-popup-lyrics-andor-lyrics-plus-seem-to-not-work).
<br><br>

---

## Acknowledgments and Credits
* [`MxLRC` by fashni](https://github.com/fashni/MxLRC)
* [Musixmatch](https://www.musixmatch.com/)
<br>

## Developer
This project was developed by [`PureAspiration`](https://github.com/PureAspiration).
<br>

## License
Distributed under the MIT License. See [`LICENSE`](./LICENSE.md) for more information.
<br><br>
