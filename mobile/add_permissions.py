"""Adds microphone + network permissions to the generated Android project.

Run once, right after `npx cap add android`. The app listens with the browser's
speech recognition, and that needs RECORD_AUDIO on Android.
"""
import pathlib
import sys

MANIFEST = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "android/app/src/main/AndroidManifest.xml")
s = MANIFEST.read_text()

PERMS = """    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
    <uses-permission android:name="android.permission.VIBRATE" />
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
"""

if 'RECORD_AUDIO' not in s:
    s = s.replace('<manifest', '<manifest', 1)
    # insert right after the opening <manifest ...> tag
    end = s.index('>', s.index('<manifest')) + 1
    s = s[:end] + '\n' + PERMS + s[end:]

if 'usesCleartextTraffic' not in s:
    s = s.replace('<application', '<application android:usesCleartextTraffic="true"', 1)

MANIFEST.write_text(s)
print("permissions added to", MANIFEST)
