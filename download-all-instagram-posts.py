#!/usr/bin/env python3

import json
import codecs
import os
from datetime import datetime
import urllib.request
from instagram_private_api import Client, ClientCookieExpiredError, ClientLoginRequiredError, ClientLoginError, \
    ClientError
# Instagram API documentation: https://instagram-private-api.readthedocs.io/en/latest/usage.html
import piexif

from file_io import open_file

LOGIN_FILE_PATH = "login_details.txt"
SETTINGS_FILE_PATH = "settings.txt"
POSTS_FILE_PATH = "posts.json"
MAX_FILE_LENGTH = 180


def to_json(python_object):
    if isinstance(python_object, bytes):
        return {'__class__': 'bytes',
                '__value__': codecs.encode(python_object, 'base64').decode()}
    raise TypeError(repr(python_object) + ' is not JSON serializable')


def from_json(json_object):
    if '__class__' in json_object and json_object['__class__'] == 'bytes':
        return codecs.decode(json_object['__value__'].encode(), 'base64')
    return json_object


def on_login_callback(api, new_settings_file):
    cache_settings = api.settings
    with open(new_settings_file, 'w') as outfile:
        json.dump(cache_settings, outfile, default=to_json)
        print('SAVED: {0!s}'.format(new_settings_file))


def login():
    """ Logs in using details in login_details.txt """
    settings_file_path = SETTINGS_FILE_PATH
    username, password = open_file(LOGIN_FILE_PATH)
    username = username.strip()
    password = password.strip()
    device_id = None

    try:
        settings_file = settings_file_path
        if not os.path.isfile(settings_file):
            # settings file does not exist
            print('Unable to find file: {0!s}'.format(settings_file))

            # login new
            api = Client(username, password, on_login=lambda x: on_login_callback(x, settings_file_path))
        else:
            with open(settings_file) as file_data:
                cached_settings = json.load(file_data, object_hook=from_json)
            print('Reusing settings: {0!s}'.format(settings_file))

            device_id = cached_settings.get('device_id')
            # reuse auth settings
            api = Client(username, password, settings=cached_settings)

    except (ClientCookieExpiredError, ClientLoginRequiredError) as e:
        print('ClientCookieExpiredError/ClientLoginRequiredError: {0!s}'.format(e))

        # Login expired
        # Do relogin but use default ua, keys and such
        api = Client(username, password, device_id=device_id,
                     on_login=lambda x: on_login_callback(x, settings_file_path))

    except ClientLoginError as e:
        print('ClientLoginError {0!s}'.format(e))
        exit(9)
    except ClientError as e:
        print('ClientError {0!s} (Code: {1:d}, Response: {2!s})'.format(e.msg, e.code, e.error_response))
        exit(9)
    except Exception as e:
        print('Unexpected Exception: {0!s}'.format(e))
        exit(99)

    return api


def main():
    api = login()

    username = input("Download all posts from which user? (Enter a . to load from posts.json file) @")

    if username == '.':
        with open(POSTS_FILE_PATH, 'r') as fp:
            posts = json.load(fp)

    else:
        user_info = api.username_info(username)
        user_id = user_info['user']['pk']

        more_available_key = 'more_available'
        next_max_id_key = 'next_max_id'
        items_key = 'items'

        feed = api.user_feed(user_id)
        posts = feed[items_key]

        while feed[more_available_key]:
            print(f"Getting more posts ({len(posts)} so far)...")
            max_id = feed[next_max_id_key]
            feed = api.user_feed(user_id, max_id=max_id)
            posts.extend(feed[items_key])

        print(f"Number of posts: {len(posts)}")

        with open(POSTS_FILE_PATH, 'w') as fp:
            json.dump(posts, fp, indent=2)

    title_key = 'title'
    caption_key = 'caption'
    text_key = 'text'
    taken_at_key = 'taken_at'
    video_versions_key = 'video_versions'
    image_versions_key = 'image_versions2'
    candidates_key = 'candidates'
    url_key = 'url'

    for i, post in enumerate(posts):
        if title_key in post:
            title = post[title_key]
        elif caption_key in post and post[caption_key] is None:
            title = ''
        elif caption_key in post and text_key in post[caption_key]:
            title = post[caption_key][text_key]
        else:
            title = "ERROR"

        if video_versions_key in post and url_key in post[video_versions_key][0]:
            url = post[video_versions_key][0][url_key]
        elif image_versions_key in post and candidates_key in post[image_versions_key] and \
                url_key in post[image_versions_key][candidates_key][0]:
            url = post[image_versions_key][candidates_key][0][url_key]
        else:
            url = "ERROR"

        time = datetime.fromtimestamp(post[taken_at_key])
        time_string = time.strftime('%Y_%m_%d %I.%M%p').replace('_', '-')
        time_string = time_string.replace("AM", "am").replace("PM", "pm").replace(" 0", " ")

        # print(f"{i}: {title}, taken at {time}")

        post_filename = "".join([c for c in title if c.isalpha() or c.isdigit() or c == ' ']).rstrip()[:MAX_FILE_LENGTH]
        extension = url.split('?')[0].split('.')[-1]
        post_filename = os.path.join("output", f"{time_string} {post_filename}.{extension}")

        print(f"Downloading file {i + 1}...")
        try:
            urllib.request.urlretrieve(url, post_filename)

            if extension == "jpg":
                exif_dict = piexif.load(post_filename)
                exif_dict['Exif'] = {piexif.ExifIFD.DateTimeOriginal: time.strftime("%Y:%m:%d %H:%M:%S")}
                exif_bytes = piexif.dump(exif_dict)
                piexif.insert(exif_bytes, post_filename)
            elif extension == "mp4" or extension == "jpg":
                os.utime(post_filename, (post[taken_at_key], post[taken_at_key]))
        except Exception as e:
            print(e)


if __name__ == '__main__':
    main()
