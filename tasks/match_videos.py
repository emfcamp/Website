import re
import requests

from flask import current_app as app
from flask_script import Command

from main import db
from models.cfp import Proposal


class MatchYouTube(Command):
    yt_url = "https://www.googleapis.com/youtube/v3/"

    # https://developers.google.com/youtube/v3/docs/playlistItems/list
    data = {
        "part": "snippet,status",
        "fields": "items(snippet(description,resourceId/videoId,thumbnails/high),status),nextPageToken",
        "maxResults": "50",
    }

    video_re = re.compile(
        r"https://media.ccc.de/v/(?P<prefix>emf[0-9]+)-(?P<id>[0-9]+)-\S+"
    )

    playlists = [
        # 'PL1Hr6VkuONaHy8EZtLIXIMZQ858315pmt',  # 2014
        # 'PL1Hr6VkuONaHIKlU5hqVU28jGyK6qAfjX',  # 2016
        "PL1Hr6VkuONaE4XM52ThiV-s3vXAUT0JCR"  # 2018
    ]

    def run(self):
        for playlist in self.playlists:
            self.match_playlist(playlist)

    def match_playlist(self, playlist):
        data = self.data.copy()
        data["playlistId"] = playlist
        data["key"] = app.config["GOOGLE_API_KEY"]
        app.logger.info("Matching for playlist %s", playlist)

        while True:
            result = requests.get(self.yt_url + "playlistItems", data).json()
            if result.get("error"):
                app.logging.error("Error fetching playlist: %s", result["error"])
                raise Exception("Error fetching playlist")

            for video in result["items"]:

                video_id = video["snippet"]["resourceId"]["videoId"]
                youtube_url = "https://www.youtube.com/watch?v={}".format(video_id)

                status = video["status"]["privacyStatus"]

                desc = video["snippet"]["description"]
                if desc == "This video is unavailable.":
                    continue

                if "thumbnails" in video["snippet"]:
                    thumbnail_url = video["snippet"]["thumbnails"]["high"]["url"]
                else:
                    thumbnail_url = None

                if status != "public":
                    # A video's been taken down temporarily
                    youtube_url = None
                    thumbnail_url = None

                match = self.video_re.search(desc)
                if match:
                    groups = match.groupdict()
                    proposal = Proposal.query.get(int(groups["id"]))

                    if (proposal.youtube_url, proposal.thumbnail_url) != (
                        youtube_url,
                        thumbnail_url,
                    ):
                        app.logger.info(
                            "Updating URLs for %s (%s)", proposal.id, video_id
                        )
                        proposal.youtube_url = youtube_url
                        proposal.thumbnail_url = thumbnail_url

            if "nextPageToken" not in result:
                break

            data["pageToken"] = result["nextPageToken"]

        db.session.commit()
        app.logger.info("Matching for playlist %s complete", playlist)
