# Unhook Tanha

Information on the internet often comes via a trade:
- Give away your attentional agency and get interesting info

But get hooked on feeds etc.
Yet Attention is your scarcest resouce. Can we unhook our attention and still get important social media information?
The simplest way is to not have an endless feed and protect yourself from takesmanship.
E.g., when using Bluesky, parse the feed periodicially and save the data. Same with RSS, blogposts, substack etc.
Then, based on some general preferences (which can be written down in some text file), select from your social media, blog, article, news feed the information that is actually helpful.
Then, compile a digest that can be sent via email and also supports e-reader format.

So three parts of the implementation.
- Get feed content and save it.
- Create digest from feed.
- Send digest via e-mail.

In the beginning, to make this simple, just use Bluesky (with an user account and the default feed for that user) and once a week get all content and create a digest.

## Installation

You can install _Unhook Tanha_ via [uv].

```console
$ pipx install uv
$ uv sync
```
