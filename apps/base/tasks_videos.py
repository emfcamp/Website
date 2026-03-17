import re
from typing import ClassVar

import click
import requests
from flask import current_app as app

from main import db
from models.cfp import Proposal

from . import base


@base.cli.command("match_youtube")
@click.option("--dry-run/--no-dry-run", default=True)
@click.option("--force/--no-force", default=False)
@click.option("--thumbnails", type=click.Choice(["none", "youtube", "c3voc"]), default="none")
def match_youtube(dry_run, force, thumbnails):
    MatchYouTube(dry_run, force, thumbnails).run()


class MatchYouTube:
    yt_url = "https://www.googleapis.com/youtube/v3/"

    # https://developers.google.com/youtube/v3/docs/playlistItems/list
    data: ClassVar = {
        "part": "snippet,status",
        "fields": "items(snippet(description,resourceId/videoId,thumbnails/high),status),nextPageToken",
        "maxResults": "50",
    }

    c3voc_slug = "emf2024"  # 2024

    video_re = re.compile(r"(?P<url>https://media.ccc.de/v/(?P<prefix>emf[0-9]+)-(?P<id>[0-9]+)-\S+)")

    playlists = (
        # 'PL1Hr6VkuONaHy8EZtLIXIMZQ858315pmt',  # 2014
        # 'PL1Hr6VkuONaHIKlU5hqVU28jGyK6qAfjX',  # 2016
        # "PL1Hr6VkuONaE4XM52ThiV-s3vXAUT0JCR",  # 2018
        # "PL1Hr6VkuONaECQTb0-TxGPVrQomXTWhbm",  # 2022
        "PL1Hr6VkuONaHvvLPgjFn3uUEl4xH6xUhQ",  # 2024
    )

    def __init__(self, dry_run=True, force=False, thumbnails="none"):
        self.dry_run = dry_run
        self.force = force
        self.thumbnails = thumbnails
        self.num_processed = 0
        self.num_matched = 0
        self.num_updated = 0

    def run(self):
        for playlist in self.playlists:
            self.match_playlist(playlist)

    def match_playlist(self, playlist):
        data = self.data.copy()
        data["playlistId"] = playlist
        data["key"] = app.config["GOOGLE_API_KEY"]
        app.logger.info(
            f"Matching for playlist {playlist}",
        )

        if self.thumbnails == "c3voc":
            app.logger.debug("Fetching schedule from c3voc")
            c3voc_data = requests.get(f"https://media.ccc.de/public/conferences/{self.c3voc_slug}").json()
            self.c3voc_thumbnails = {e["frontend_link"]: e["poster_url"] for e in c3voc_data["events"]}

        while True:
            result = requests.get(self.yt_url + "playlistItems", data).json()
            if result.get("error"):
                app.logger.error(f"Error fetching playlist: {result['error']}")
                raise Exception("Error fetching playlist")

            for video in result["items"]:
                self.match_video(video)
                self.num_processed += 1

            if "nextPageToken" not in result:
                break

            data["pageToken"] = result["nextPageToken"]

        app.logger.info(f"Matching for playlist {playlist} complete.")
        app.logger.info(
            f"Found {self.num_processed} videos, matched {self.num_matched}, updated {self.num_updated}."
        )

    def match_video(self, video):
        video_id = video["snippet"]["resourceId"]["videoId"]
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"

        desc = video["snippet"]["description"]
        if desc == "This video is unavailable.":
            app.logger.warning(f"Ignoring unavailable video {youtube_url}")
            return

        if desc == "This video is private.":
            app.logger.warning(f"Ignoring private video {youtube_url}")
            return

        matches = self.video_re.search(desc)
        if not matches:
            app.logger.warning(f"Could not find c3voc URL for {youtube_url} ({desc})")
            return

        groups = matches.groupdict()
        app.logger.info(f"Matched {youtube_url} to proposal {int(groups['id'])}")
        self.num_matched += 1
        c3voc_url = groups["url"]

        if self.thumbnails == "c3voc":
            thumbnail_url = self.c3voc_thumbnails.get(c3voc_url)

        elif self.thumbnails == "youtube":
            thumbnail_url = video.get("snippet", {}).get("thumbnails", {}).get("high", {}).get("url")

        else:
            thumbnail_url = None

        status = video["status"]["privacyStatus"]

        if status != "public":
            # A video's been taken down temporarily
            youtube_url = None
            c3voc_url = None
            thumbnail_url = None

        proposal_id = int(groups["id"])
        proposal = Proposal.query.get(proposal_id)

        if not proposal:
            app.logger.warning(f"Could not find proposal {proposal_id}")
            app.logger.warning(f"Would have updated to {youtube_url}, {thumbnail_url}, {c3voc_url}")
            return

        old = (proposal.youtube_url, proposal.c3voc_url)
        new = (youtube_url, c3voc_url)
        if self.thumbnails != "none":
            old += (proposal.thumbnail_url,)
            new += (thumbnail_url,)

        if old == new:
            app.logger.info(f"No changes for proposal {proposal.id}")
            return

        if not self.force and proposal.youtube_url and proposal.youtube_url != youtube_url:
            app.logger.warning("Proposal already has different youtube_url, not updating")
        else:
            proposal.youtube_url = youtube_url

        if self.thumbnail:
            if not self.force and proposal.thumbnail_url and proposal.thumbnail_url != thumbnail_url:
                app.logger.warning("Proposal already has different thumbnail_url, not updating")
            else:
                proposal.thumbnail_url = thumbnail_url

        if not self.force and proposal.c3voc_url and proposal.c3voc_url != c3voc_url:
            app.logger.warning("Proposal already has different c3voc_url, not updating")
        else:
            proposal.c3voc_url = c3voc_url

        if self.dry_run:
            app.logger.info(f"Would save URLs for {proposal.id}")
            db.session.rollback()
            self.num_updated += 1

        else:
            app.logger.info(f"Saved URLs for {proposal.id}")
            db.session.commit()

        self.num_updated += 1
