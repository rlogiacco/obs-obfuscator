from os import listdir
from os.path import isfile, join, dirname, realpath, exists, isdir, isfile
import time
import json
from functools import partial
import logging
import click
from screeninfo import get_monitors

from obswebsocket import obsws, requests
import numpy
import cv2
from mss import mss

logging.basicConfig(level=logging.ERROR)

host = "localhost"

print = partial(print, flush=True)

currently_in_default_scene = False
def execute_tick(screen_capture, monitor_to_capture, image_mask, image_descriptors, feature_detector, feature_matcher, num_good_matches_required, obs, default_scene_name, target_scene_name, show_debug_window):
    global currently_in_default_scene
    try:
        start_time = time.time()
        frame = numpy.array(screen_capture.grab(screen_capture.monitors[monitor_to_capture]))
        masked_frame = cv2.bitwise_and(frame, frame, mask=image_mask)
        
        image_is_in_frame, matches = frame_contains_one_or_more_matching_images(masked_frame, image_mask, image_descriptors, feature_detector, feature_matcher, num_good_matches_required, show_debug_window)

        tick_time = None
        if image_is_in_frame:
            if currently_in_default_scene:
                obs.call(requests.SetCurrentScene(target_scene_name))
                tick_time = round(time.time() - start_time, 2)

                currently_in_default_scene = False
        elif not currently_in_default_scene:
            tick_time = round(time.time() - start_time, 2)
            time.sleep(0.1)
            obs.call(requests.SetCurrentScene(default_scene_name))
            
            currently_in_default_scene = True
        return (tick_time, matches)
    except Exception as e:
        print(e)
    return (None, -1)

def get_valid_camera_indices():
    # checks the first 10 indexes.
    index = 0
    arr = []
    max_to_check = 10
    while index <= max_to_check:
        cap = cv2.VideoCapture(index)
        ret, frame = cap.read()
        if ret:
            arr.append(index)
            cap.release()
        index += 1
    indices_cache = arr
    return indices_cache

def frame_contains_one_or_more_matching_images(frame, mask, image_descriptors, feature_detector, feature_matcher, num_good_matches_required, show_debug_window):
    if frame is not None:
        keypoints, keypoint_descriptors = feature_detector.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), mask)

        for image_descriptor in image_descriptors:
            matches = feature_matcher.knnMatch(keypoint_descriptors, image_descriptor, k=2)
            # Apply ratio test
            good = []
            for m,n in matches:
                if m.distance < 0.75*n.distance:
                    good.append([m])

            if show_debug_window:
                cv2.drawKeypoints(frame, keypoints, frame)
                cv2.imshow("OBS Obfuscator - Debug Window", cv2.resize(frame, (0, 0), fx=0.5, fy=0.5))
                cv2.waitKey(1)
                print("Num matches: {}".format(len(good)))
            
            if len(good) > num_good_matches_required:
                return (True, len(good))
    return (False, len(good))

@click.command()
@click.option('--show-debug-window', is_flag=True)
@click.option('--monitor', default=1, show_default=True, help='Index of the screen to capture', metavar='<int>')
@click.option('--format', required=True, type=click.Choice(['720p','960p','1080p', '1440p', '2160p'], case_sensitive=False), help='Screen format', prompt='Your game resolution')
@click.option('--scene-on', default="Live Gaming (Map Covered)", show_default=True, help='Scene to activate when triggered (use quotes if necessary)', metavar='<text>')
@click.option('--scene-off', default="Live Gaming", show_default=True, help='Scene to activate when not triggered (use quotes if necessary)', metavar='<text>')
@click.option('--features', default=500, show_default=True, help='Number of features to detect', metavar='<int>')
@click.option('--matches', default=20, show_default=True, help='Number of matches required for triggering', metavar='<int>')
@click.option('--port', default=4444, show_default=True, help='OBS websocket listening port', metavar='<int>')
@click.argument('resource-dir', type=click.Path(exists=True,file_okay=False, dir_okay=True))
def main(resource_dir, monitor, format, scene_on, scene_off, features, matches, port, show_debug_window):
    image_directory = resource_dir + "/" + format
    mask_file = resource_dir + "/mask-" + format + ".png"

    if not exists(image_directory) or not isdir(image_directory) or not exists(mask_file) or not isfile(mask_file):
        print("Format {} is not supported by the game resources".format(format))
        exit(1)

    try:
        image_files_to_search_for = [cv2.cvtColor(cv2.imread(join(image_directory, f)), cv2.COLOR_BGR2GRAY) for f in listdir(image_directory) if isfile(join(image_directory, f))]
        image_mask = cv2.imread(mask_file, cv2.IMREAD_GRAYSCALE)
    except Exception as e:
        print(e)

    obs = obsws(host, port)
    obs.connect()

    scenes = obs.call(requests.GetSceneList()).getScenes()
    print("Detected scenes in OBS: " + str([scene["name"] for scene in scenes]))

    feature_detector = cv2.ORB_create(nfeatures=features, scoreType=cv2.ORB_FAST_SCORE, nlevels=1, fastThreshold=10)
    image_descriptors = [feature_detector.detectAndCompute(image, None)[1] for image in image_files_to_search_for]

    feature_matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    if show_debug_window:
        cv2.startWindowThread()
        cv2.namedWindow("OBS Obfuscator - Debug Window")

    with mss() as screen_capture:
        while True:
            try:
                tick_time, num_matches = execute_tick(screen_capture, monitor, image_mask, image_descriptors, feature_detector, feature_matcher, matches, obs, scene_off, scene_on, show_debug_window)
                if tick_time:
                    print("Tick took {} seconds. Suggested OBS source delay: {}ms. Num good matches: {}".format(tick_time, round(tick_time, 2) * 1000, num_matches))
            except Exception as e:
                print(e)


if __name__ == "__main__":
    with open(dirname(realpath(__file__)) + "/settings.json") as settings_file:
        application_settings = json.load(settings_file)
    main(auto_envvar_prefix='OBFUSCATOR', default_map=application_settings)