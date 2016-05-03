KwBot
=====

See [KwBot’s site](https://chriswarrick.com/kwbot/) for docs.

GitHub Issues support
---------------------

To activate, add a webhook to ``http://HOST:5944/`` that takes
``application/json`` input and only the *Issues* event. For the *secret*
field, use a randomly generated value (out of printable ASCII characters). You
also need to put that secret in a file named ``tokens`` in the KwBot
home. Its format is `#channel:token` (each channel on a separate line).

Factoids
--------

Factoids are stored in a JSON file (``factoids.json`` in KwBot home). It’s a dict of dicts that looks like this:

    {
        "!global": {
            "factoid", "message for the factoid"
            "second", "another message"
        },
        "#channel": {
            "factoid": "Per-channel factoids go here (overrides global)",
            "third": "Channel-only factoid"
        }
    }
