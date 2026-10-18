# Prompts

This bot was written with [Claude Code](https://claude.com/claude-code). These are
the prompts it was built from, in order.

## 1

> This folder here should become a bot that runs on a GitHub action. The action sould edit `image` links that go to wikimedia commons like https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Strassenschild_Kirchbergerstrasse.jpg/800px-Strassenschild_Kirchbergerstrasse.jpg (and *only* those). These `image` links should be corrected to https://commons.wikimedia.org/wiki/File:Strassenschild_Kirchbergerstrasse.jpg. It should work with minimal impact on both the Overpass API (to find the image links) and the Wikimedia API (to find the correct image).

## 2

> Links from Wikimedia are served only for certain widhts. Replace those that don't work anymore with the correct Wikimedia *description* site, not the direct thumbnail. This is also due to licensing issues with the Wikimedia pages.

## 3

> Thumbnail sizes are given on https://www.mediawiki.org/wiki/Common_thumbnail_sizes

## 4

> Make this here a git repository, and add the prompts to a markdown file in the repository.

## 5

> Keep the prompts file updated, so the history is *always* kept. Now upload the repository to Github, to a new repo (habi/osm-wikimedia-thumbnails-correction-bot)

(Asked whether public or private: **public**.)

## 7

> Please output what is done (or would be done) in the github action log, so it can be checked.
